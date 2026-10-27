"""Reports built from real data only. Functions take a plain sqlite3 connection so
they can run on a background thread with their own read-only connection.

Only COMPLETED bills count as sales. Returns count on the day they were made.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..money import fmt
from .inventory import MOVEMENT_LABELS


@dataclass
class Report:
    title: str
    headers: list[str]
    rows: list[list]
    money_cols: set[int] = field(default_factory=set)
    totals: list | None = None
    subtitle: str = ""

    def formatted_rows(self, with_totals: bool = True) -> list[list[str]]:
        out = []
        rows = self.rows + ([self.totals] if with_totals and self.totals else [])
        for r in rows:
            out.append([fmt(v) if i in self.money_cols and isinstance(v, int) else ("" if v is None else str(v))
                        for i, v in enumerate(r)])
        return out


def _range(date_from: str, date_to: str) -> tuple[str, str]:
    return date_from + " 00:00:00", date_to + " 23:59:59"


def _sum_cols(rows: list[list], cols: set[int], label_col: int = 0, label: str = "TOTAL", width: int = 0) -> list:
    width = width or (len(rows[0]) if rows else 0)
    tot: list = [""] * width
    if width:
        tot[label_col] = label
    for c in cols:
        tot[c] = sum(int(r[c] or 0) for r in rows)
    return tot


def _sales_grouped(conn: sqlite3.Connection, date_from: str, date_to: str, length: int, title: str) -> Report:
    a, b = _range(date_from, date_to)
    sales = {r[0]: list(r[1:]) for r in conn.execute(
        "SELECT substr(created_at, 1, ?) AS d, COUNT(*), SUM(gross_paise),"
        " SUM(item_discount_paise + bill_discount_paise), SUM(cgst_paise + sgst_paise + igst_paise), SUM(total_paise) "
        "FROM sales WHERE status = 'COMPLETED' AND created_at BETWEEN ? AND ? GROUP BY d", (length, a, b))}
    items = dict(conn.execute(
        "SELECT substr(s.created_at, 1, ?) AS d, SUM(i.qty) FROM sale_items i JOIN sales s ON s.id = i.sale_id "
        "WHERE s.status = 'COMPLETED' AND s.created_at BETWEEN ? AND ? GROUP BY d", (length, a, b)).fetchall())
    refunds = dict(conn.execute(
        "SELECT substr(created_at, 1, ?) AS d, SUM(refund_paise) FROM returns "
        "WHERE created_at BETWEEN ? AND ? GROUP BY d", (length, a, b)).fetchall())
    rows = []
    for d in sorted(set(sales) | set(refunds)):
        bills, gross, disc, tax, total = sales.get(d, [0, 0, 0, 0, 0])
        ref = int(refunds.get(d) or 0)
        rows.append([d, bills, int(items.get(d) or 0), gross, disc, tax, total, ref, total - ref])
    rep = Report(title, ["Period", "Bills", "Items", "Gross", "Discount", "Tax", "Sales", "Refunds", "Net"],
                 rows, {3, 4, 5, 6, 7, 8}, subtitle=f"{date_from} to {date_to}")
    if rows:
        rep.totals = _sum_cols(rows, {1, 2, 3, 4, 5, 6, 7, 8})
    return rep


def daily_sales(conn, date_from: str, date_to: str) -> Report:
    return _sales_grouped(conn, date_from, date_to, 10, "Daily sales")


def monthly_sales(conn, date_from: str, date_to: str) -> Report:
    return _sales_grouped(conn, date_from, date_to, 7, "Monthly sales")


def sales_by_category(conn, date_from: str, date_to: str) -> Report:
    a, b = _range(date_from, date_to)
    rows = [list(r) for r in conn.execute(
        "SELECT CASE WHEN i.category_name = '' THEN '(none)' ELSE i.category_name END, SUM(i.qty),"
        " SUM(i.item_discount_paise + i.bill_discount_paise), SUM(i.line_total_paise) "
        "FROM sale_items i JOIN sales s ON s.id = i.sale_id WHERE s.status='COMPLETED' AND s.created_at BETWEEN ? AND ? "
        "GROUP BY 1 ORDER BY 4 DESC", (a, b))]
    rep = Report("Sales by category", ["Category", "Qty", "Discount", "Sales"], rows, {2, 3},
                 subtitle=f"{date_from} to {date_to}")
    if rows:
        rep.totals = _sum_cols(rows, {1, 2, 3})
    return rep


def top_products(conn, date_from: str, date_to: str, limit: int = 50) -> Report:
    a, b = _range(date_from, date_to)
    rows = [list(r) for r in conn.execute(
        "SELECT i.product_name, i.category_name, SUM(i.qty) AS q, SUM(i.line_total_paise) "
        "FROM sale_items i JOIN sales s ON s.id = i.sale_id WHERE s.status='COMPLETED' AND s.created_at BETWEEN ? AND ? "
        "GROUP BY i.product_name, i.category_name ORDER BY q DESC, 4 DESC LIMIT ?", (a, b, int(limit)))]
    return Report("Top-selling products", ["Product", "Category", "Qty sold", "Sales"], rows, {3},
                  subtitle=f"{date_from} to {date_to}")


def payment_summary(conn, date_from: str, date_to: str) -> Report:
    a, b = _range(date_from, date_to)
    got = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT p.method, COUNT(DISTINCT p.sale_id), SUM(p.amount_paise) FROM sale_payments p JOIN sales s "
        "ON s.id = p.sale_id WHERE s.status='COMPLETED' AND s.created_at BETWEEN ? AND ? GROUP BY p.method", (a, b))}
    refunds = dict(conn.execute(
        "SELECT refund_method, SUM(refund_paise) FROM returns WHERE created_at BETWEEN ? AND ? GROUP BY refund_method",
        (a, b)).fetchall())
    rows = []
    for m in ("CASH", "UPI", "CARD", "EXCHANGE"):
        bills, amt = got.get(m, (0, 0))
        ref = int(refunds.get(m) or 0)
        if bills or ref:
            rows.append([m, bills, int(amt or 0), ref, int(amt or 0) - ref])
    rep = Report("Payment-method summary", ["Method", "Bills", "Received", "Refunded", "Net"], rows, {2, 3, 4},
                 subtitle=f"{date_from} to {date_to}. EXCHANGE = credit from returned items.")
    if rows:
        rep.totals = _sum_cols(rows, {2, 3, 4})
    return rep


def low_stock(conn, default_min: int) -> Report:
    rows = [list(r) for r in conn.execute(
        "SELECT p.name, v.size, v.colour, v.sku, v.stock, COALESCE(p.min_stock, ?) "
        "FROM variants v JOIN products p ON p.id = v.product_id WHERE v.active = 1 AND p.active = 1 "
        "AND v.stock <= COALESCE(p.min_stock, ?) ORDER BY v.stock, p.name COLLATE NOCASE", (default_min, default_min))]
    for r in rows:
        r.append("OUT OF STOCK" if r[4] == 0 else "Low")
    return Report("Low-stock report", ["Product", "Size", "Colour", "SKU", "Stock", "Minimum", "Status"], rows,
                  subtitle=f"As of {date.today().isoformat()}")


def stock_movement_report(conn, date_from: str, date_to: str) -> Report:
    a, b = _range(date_from, date_to)
    rows = []
    for r in conn.execute(
            "SELECT m.created_at, p.name, v.size, v.colour, v.sku, m.movement_type, m.qty_change, m.balance_after,"
            " m.ref_text, m.reason FROM stock_movements m JOIN variants v ON v.id = m.variant_id "
            "JOIN products p ON p.id = v.product_id WHERE m.created_at BETWEEN ? AND ? ORDER BY m.id", (a, b)):
        r = list(r)
        r[5] = MOVEMENT_LABELS.get(r[5], r[5])
        rows.append(r)
    return Report("Stock movement report", ["Date/time", "Product", "Size", "Colour", "SKU", "Type", "Change",
                                            "Balance", "Reference", "Reason"], rows,
                  subtitle=f"{date_from} to {date_to}")


def returns_report(conn, date_from: str, date_to: str) -> Report:
    a, b = _range(date_from, date_to)
    rows = [list(r) for r in conn.execute(
        "SELECT r.created_at, r.return_no, s.invoice_no, i.product_name, i.size, i.colour, ri.qty,"
        " CASE ri.restocked WHEN 1 THEN 'Yes' ELSE 'No' END, r.refund_method, r.reason, ri.refund_paise "
        "FROM return_items ri JOIN returns r ON r.id = ri.return_id JOIN sales s ON s.id = r.sale_id "
        "JOIN sale_items i ON i.id = ri.sale_item_id WHERE r.created_at BETWEEN ? AND ? ORDER BY r.id", (a, b))]
    rep = Report("Return report", ["Date/time", "Return no", "Bill", "Product", "Size", "Colour", "Qty", "Restocked",
                                   "Refund via", "Reason", "Refund"], rows, {10},
                 subtitle=f"{date_from} to {date_to}")
    if rows:
        rep.totals = _sum_cols(rows, {6, 10})
    return rep


def profit_estimate(conn, date_from: str, date_to: str) -> Report:
    """Estimate only: sales value (before GST) minus purchase cost of the items sold."""
    a, b = _range(date_from, date_to)
    sold = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in conn.execute(
        "SELECT substr(s.created_at,1,10), SUM(i.taxable_paise), SUM(i.unit_cost_paise * i.qty) FROM sale_items i "
        "JOIN sales s ON s.id = i.sale_id WHERE s.status='COMPLETED' AND s.created_at BETWEEN ? AND ? GROUP BY 1",
        (a, b))}
    back = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in conn.execute(
        "SELECT substr(r.created_at,1,10), SUM(ri.taxable_paise),"
        " SUM(CASE WHEN ri.restocked = 1 THEN i.unit_cost_paise * ri.qty ELSE 0 END) FROM return_items ri "
        "JOIN returns r ON r.id = ri.return_id JOIN sale_items i ON i.id = ri.sale_item_id "
        "WHERE r.created_at BETWEEN ? AND ? GROUP BY 1", (a, b))}
    rows = []
    for d in sorted(set(sold) | set(back)):
        rev, cost = sold.get(d, (0, 0))
        rrev, rcost = back.get(d, (0, 0))
        net_rev, net_cost = rev - rrev, cost - rcost
        rows.append([d, net_rev, net_cost, net_rev - net_cost])
    rep = Report("Profit estimate", ["Date", "Sales (before GST)", "Purchase cost", "Estimated profit"], rows,
                 {1, 2, 3}, subtitle=f"{date_from} to {date_to}. Estimate only: uses purchase cost saved on each "
                                     "product at the time of sale; excludes rent, salaries and other expenses.")
    if rows:
        rep.totals = _sum_cols(rows, {1, 2, 3})
    return rep


REPORTS = {
    "Daily sales": ("range", daily_sales),
    "Monthly sales": ("range", monthly_sales),
    "Sales by category": ("range", sales_by_category),
    "Top-selling products": ("range", top_products),
    "Payment-method summary": ("range", payment_summary),
    "Low-stock report": ("stock", low_stock),
    "Stock movement report": ("range", stock_movement_report),
    "Return report": ("range", returns_report),
    "Profit estimate": ("range", profit_estimate),
}


def dashboard(conn, day: str, default_min: int) -> dict:
    a, b = _range(day, day)
    s = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_paise),0), COALESCE(SUM(item_discount_paise + bill_discount_paise),0) "
        "FROM sales WHERE status='COMPLETED' AND created_at BETWEEN ? AND ?", (a, b)).fetchone()
    items = conn.execute(
        "SELECT COALESCE(SUM(i.qty),0) FROM sale_items i JOIN sales s ON s.id = i.sale_id "
        "WHERE s.status='COMPLETED' AND s.created_at BETWEEN ? AND ?", (a, b)).fetchone()[0]
    pays = dict(conn.execute(
        "SELECT p.method, SUM(p.amount_paise) FROM sale_payments p JOIN sales s ON s.id = p.sale_id "
        "WHERE s.status='COMPLETED' AND s.created_at BETWEEN ? AND ? GROUP BY p.method", (a, b)).fetchall())
    refunds = dict(conn.execute(
        "SELECT refund_method, SUM(refund_paise) FROM returns WHERE created_at BETWEEN ? AND ? GROUP BY refund_method",
        (a, b)).fetchall())
    low = conn.execute(
        "SELECT COUNT(*) FROM variants v JOIN products p ON p.id = v.product_id WHERE v.active=1 AND p.active=1 "
        "AND v.stock <= COALESCE(p.min_stock, ?)", (default_min,)).fetchone()[0]
    val = conn.execute(
        "SELECT COALESCE(SUM(v.stock * COALESCE(v.cost_paise, p.cost_paise)),0),"
        " COALESCE(SUM(v.stock * COALESCE(v.price_paise, p.price_paise)),0), COALESCE(SUM(v.stock),0) "
        "FROM variants v JOIN products p ON p.id = v.product_id WHERE v.active=1 AND p.active=1").fetchone()
    return {
        "bills": s[0], "sales": s[1], "discounts": s[2], "items": items,
        "cash": int(pays.get("CASH") or 0) - int(refunds.get("CASH") or 0),
        "upi": int(pays.get("UPI") or 0) - int(refunds.get("UPI") or 0),
        "card": int(pays.get("CARD") or 0) - int(refunds.get("CARD") or 0),
        "refunds": sum(int(v or 0) for v in refunds.values()),
        "low_stock": low, "stock_cost": val[0], "stock_sale": val[1], "stock_units": val[2],
    }
