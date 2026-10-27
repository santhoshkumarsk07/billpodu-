"""Returns and exchanges against a saved bill. The original bill is never changed."""
from __future__ import annotations

from dataclasses import dataclass

from ..db import Database, now_str
from ..errors import NotFoundError, ValidationError
from .inventory import record_movement
from .settings import Settings

REFUND_METHODS = ("CASH", "UPI", "CARD", "EXCHANGE")
RETURN_REASONS = ["Size issue", "Colour not liked", "Defective / damaged", "Wrong item", "Customer changed mind",
                  "Other"]


@dataclass
class ReturnLine:
    sale_item_id: int
    qty: int
    restock: bool = True   # False for damaged items that cannot be sold again


def returnable_items(db: Database, sale_id: int) -> list[dict]:
    rows = db.all(
        "SELECT i.id AS sale_item_id, i.line_no, i.variant_id, i.product_name, i.size, i.colour, i.sku, i.qty,"
        " i.unit_price_paise, i.line_total_paise,"
        " COALESCE((SELECT SUM(ri.qty) FROM return_items ri WHERE ri.sale_item_id = i.id), 0) AS returned "
        "FROM sale_items i WHERE i.sale_id = ? ORDER BY i.line_no", (sale_id,))
    out = []
    for r in rows:
        d = dict(r)
        d["remaining"] = d["qty"] - d["returned"]
        out.append(d)
    return out


def refund_share(total: int, qty_sold: int, before: int, now: int) -> int:
    """Portion of a line amount for `now` units, given `before` units already returned.

    Computed cumulatively so all returns of a line add up to exactly the line amount.
    """
    def upto(n: int) -> int:
        return (total * n * 2 + qty_sold) // (2 * qty_sold)
    return upto(before + now) - upto(before)


def create_return(db: Database, settings: Settings, sale_id: int, lines: list[ReturnLine], reason: str,
                  refund_method: str, reference: str = "", note: str = "") -> int:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Please choose a return reason.")
    if refund_method not in REFUND_METHODS:
        raise ValidationError("Choose a refund method: cash, UPI, card or exchange.")
    lines = [ln for ln in lines if ln.qty]
    if not lines:
        raise ValidationError("Enter the quantity being returned for at least one item.")
    seen = set()
    for ln in lines:
        if not isinstance(ln.qty, int) or ln.qty < 0:
            raise ValidationError("Return quantity must be a whole number.")
        if ln.sale_item_id in seen:
            raise ValidationError("The same bill line is listed twice.")
        seen.add(ln.sale_item_id)

    with db.transaction():
        sale = db.one("SELECT id, invoice_no, status FROM sales WHERE id = ?", (sale_id,))
        if sale is None:
            raise NotFoundError("Original bill not found.")
        if sale["status"] != "COMPLETED":
            raise ValidationError(f"Bill {sale['invoice_no']} is cancelled; nothing can be returned.")
        items = {r["sale_item_id"]: r for r in returnable_items(db, sale_id)}
        prefix = settings.get("invoice_prefix") or "83MW"
        return_no = f"{prefix}-R-{db.next_sequence('return:' + prefix):04d}"
        computed = []
        for ln in lines:
            it = db.one("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?", (ln.sale_item_id, sale_id))
            if it is None:
                raise ValidationError("A returned item does not belong to this bill.")
            remaining = items[ln.sale_item_id]["remaining"]
            already = items[ln.sale_item_id]["returned"]
            if ln.qty > remaining:
                raise ValidationError(
                    f"Cannot return {ln.qty} of {it['product_name']}: only {remaining} left to return "
                    f"(sold {it['qty']}, already returned {already}).")
            vals = {k: refund_share(it[k + "_paise"], it["qty"], already, ln.qty)
                    for k in ("line_total", "taxable", "cgst", "sgst", "igst")}
            computed.append((ln, it, vals))
        refund_total = sum(v["line_total"] for _, _, v in computed)
        return_id = db.execute(
            "INSERT INTO returns(return_no, sale_id, created_at, refund_method, refund_paise, reason, note, reference)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (return_no, sale_id, now_str(), refund_method, refund_total, reason[:120], (note or "").strip()[:300],
             (reference or "").strip()[:60])).lastrowid
        for ln, it, v in computed:
            db.execute(
                "INSERT INTO return_items(return_id, sale_item_id, variant_id, qty, refund_paise, taxable_paise,"
                " cgst_paise, sgst_paise, igst_paise, restocked) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (return_id, it["id"], it["variant_id"], ln.qty, v["line_total"], v["taxable"], v["cgst"],
                 v["sgst"], v["igst"], 1 if ln.restock else 0))
            if ln.restock:
                record_movement(db, it["variant_id"], "RETURN", ln.qty, ref_type="RETURN", ref_id=return_id,
                                ref_text=f"{return_no} (bill {sale['invoice_no']})", reason=reason[:200])
        return int(return_id)


def get_return(db: Database, return_id: int) -> dict:
    row = db.one("SELECT r.*, s.invoice_no, x.invoice_no AS exchange_invoice FROM returns r "
                 "JOIN sales s ON s.id = r.sale_id LEFT JOIN sales x ON x.id = r.exchange_sale_id WHERE r.id = ?",
                 (return_id,))
    if row is None:
        raise NotFoundError("Return not found.")
    d = dict(row)
    d["items"] = [dict(r) for r in db.all(
        "SELECT ri.*, i.product_name, i.size, i.colour, i.sku, i.unit_price_paise FROM return_items ri "
        "JOIN sale_items i ON i.id = ri.sale_item_id WHERE ri.return_id = ? ORDER BY ri.id", (return_id,))]
    return d


def list_returns(db: Database, date_from: str = "", date_to: str = "", text: str = "", limit: int = 1000) -> list[dict]:
    sql = ("SELECT r.id, r.return_no, r.created_at, s.invoice_no, r.refund_method, r.refund_paise, r.reason,"
           " x.invoice_no AS exchange_invoice,"
           " (SELECT SUM(qty) FROM return_items ri WHERE ri.return_id = r.id) AS items "
           "FROM returns r JOIN sales s ON s.id = r.sale_id LEFT JOIN sales x ON x.id = r.exchange_sale_id WHERE 1=1 ")
    params: list = []
    if date_from:
        sql += "AND r.created_at >= ? "
        params.append(date_from + " 00:00:00")
    if date_to:
        sql += "AND r.created_at <= ? "
        params.append(date_to + " 23:59:59")
    if text.strip():
        like = f"%{text.strip()}%"
        sql += "AND (r.return_no LIKE ? OR s.invoice_no LIKE ?) "
        params += [like, like]
    sql += "ORDER BY r.id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.all(sql, tuple(params))]


def open_exchange_credits(db: Database) -> list[dict]:
    return [dict(r) for r in db.all(
        "SELECT r.id, r.return_no, r.refund_paise, r.created_at, s.invoice_no FROM returns r "
        "JOIN sales s ON s.id = r.sale_id WHERE r.refund_method = 'EXCHANGE' AND r.exchange_sale_id IS NULL "
        "AND r.refund_paise > 0 ORDER BY r.id DESC")]
