"""Completing, cancelling, finding and holding bills.

A completed bill is never edited or deleted. Saving a bill is one database
transaction: if anything fails, nothing is saved. Printing happens only after
the transaction has committed, so a printer failure can never duplicate a sale.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from ..db import Database, now_str
from ..errors import NotFoundError, StockError, ValidationError
from ..money import fmt
from . import cart as cartmod
from .cart import BillDiscount, CartLine, TaxConfig
from .catalog import get_variant
from .customers import walkin_id
from .inventory import record_movement
from .settings import Settings


def tax_config(settings: Settings, inter_state: bool = False) -> TaxConfig:
    return TaxConfig(
        enabled=settings.get_bool("gst_enabled"),
        inclusive=settings.get_bool("prices_include_tax"),
        inter_state=inter_state and settings.get_bool("gst_enabled"),
        default_rate_bp=settings.get_int("default_gst_rate_bp"),
        slab_threshold=settings.get_int("slab_threshold_paise"),
        slab_low_bp=settings.get_int("slab_low_rate_bp"),
        slab_high_bp=settings.get_int("slab_high_rate_bp"),
    )


def compute_for(settings: Settings, lines: list[CartLine], bill: BillDiscount, inter_state: bool = False):
    return cartmod.compute(lines, bill, tax_config(settings, inter_state),
                           round_off=settings.get_bool("round_off_total"),
                           max_discount_bp=settings.get_int("max_discount_percent_bp"))


def line_from_variant(v: dict) -> CartLine:
    return CartLine(
        variant_id=v["variant_id"], product_name=v["product_name"], size=v["size"], colour=v["colour"],
        sku=v["sku"], barcode=v["barcode"], unit_price=v["price"], mrp=v["mrp"], unit_cost=v["cost"],
        hsn_code=v["hsn_code"], category_name=v["category_name"] or "", gst_mode=v["gst_mode"],
        gst_rate_bp=v["gst_rate_bp"], qty=1, stock=v["stock"])


def check_sellable(v: dict | None, code: str = "") -> None:
    """Raise a clear error if a scanned item cannot be sold."""
    if v is None:
        raise NotFoundError(f"Unknown barcode '{code}'. No product has this barcode or SKU.")
    name = v["product_name"] + (f" ({' / '.join(x for x in (v['size'], v['colour']) if x)})"
                                if (v["size"] or v["colour"]) else "")
    if not v["variant_active"] or not v["product_active"]:
        raise ValidationError(f"{name} is archived (inactive) and cannot be sold.", "Inactive item")
    if v["stock"] <= 0:
        raise StockError(f"{name} is out of stock.")


@dataclass
class PaymentInput:
    upi: int = 0
    card: int = 0
    cash_received: int = 0
    upi_ref: str = ""
    card_ref: str = ""
    exchange_return_id: int | None = None


@dataclass
class SaleRequest:
    lines: list[CartLine]
    bill_discount: BillDiscount = field(default_factory=BillDiscount)
    customer_id: int | None = None
    payment: PaymentInput = field(default_factory=PaymentInput)
    note: str = ""
    inter_state: bool = False
    customer_state: str = ""
    client_ref: str = field(default_factory=lambda: uuid.uuid4().hex)


def invoice_number(db: Database, settings: Settings) -> str:
    prefix = settings.get("invoice_prefix") or "83MW"
    fy = settings.get("financial_year").strip()
    digits = settings.get_int("invoice_digits") or 4
    seq_name = f"invoice:{prefix}:{fy}"
    while True:
        n = db.next_sequence(seq_name)
        number = f"{prefix}-{fy}-{n:0{digits}d}" if fy else f"{prefix}-{n:0{digits}d}"
        if not db.scalar("SELECT 1 FROM sales WHERE invoice_no = ?", (number,)):
            return number


def complete_sale(db: Database, settings: Settings, req: SaleRequest) -> int:
    """Validate, recalculate, check stock and save the whole bill atomically. Returns sale id.

    Calling it again with the same client_ref returns the already-saved sale instead of a duplicate.
    """
    if not req.lines:
        raise ValidationError("The bill is empty. Scan or add an item first.")
    if req.note and len(req.note) > 300:
        raise ValidationError("Bill note is too long (300 characters max).")
    existing = db.scalar("SELECT id FROM sales WHERE client_ref = ?", (req.client_ref,))
    if existing:
        return int(existing)
    totals = compute_for(settings, req.lines, req.bill_discount, req.inter_state)

    with db.transaction():
        existing = db.scalar("SELECT id FROM sales WHERE client_ref = ?", (req.client_ref,))
        if existing:
            return int(existing)

        # Re-check every item against the database inside the transaction.
        needed: dict[int, int] = defaultdict(int)
        for ln in req.lines:
            needed[ln.variant_id] += ln.qty
        problems = []
        for vid, qty in needed.items():
            v = get_variant(db, vid)
            if not v["variant_active"] or not v["product_active"]:
                raise ValidationError(f"{v['product_name']} has been archived and cannot be sold.")
            if v["stock"] < qty:
                extra = " / ".join(x for x in (v["size"], v["colour"]) if x)
                problems.append(f"• {v['product_name']} {extra}: need {qty}, only {v['stock']} in stock")
        if problems:
            raise StockError("Not enough stock to complete this bill:\n" + "\n".join(problems)
                             + "\n\nReceive the stock in Inventory first, or reduce the quantity.")

        customer_id = req.customer_id or walkin_id(db)
        cust = db.one("SELECT id, name, phone, is_walkin FROM customers WHERE id = ?", (customer_id,))
        if cust is None:
            raise ValidationError("The selected customer no longer exists.")

        exchange_amount, exchange_ref = 0, ""
        if req.payment.exchange_return_id:
            ret = db.one("SELECT return_no, refund_paise, refund_method, exchange_sale_id FROM returns WHERE id = ?",
                         (req.payment.exchange_return_id,))
            if ret is None or ret["refund_method"] != "EXCHANGE":
                raise ValidationError("That exchange return was not found.")
            if ret["exchange_sale_id"] is not None:
                raise ValidationError(f"Exchange credit from {ret['return_no']} has already been used.")
            exchange_amount, exchange_ref = int(ret["refund_paise"]), ret["return_no"]

        st = cartmod.settle(totals.total, upi=req.payment.upi, card=req.payment.card, exchange=exchange_amount,
                            cash_received=req.payment.cash_received, upi_ref=req.payment.upi_ref,
                            card_ref=req.payment.card_ref, exchange_ref=exchange_ref)

        invoice_no = invoice_number(db, settings)
        cfg = tax_config(settings, req.inter_state)
        bd = req.bill_discount
        sale_id = db.execute(
            "INSERT INTO sales(invoice_no, client_ref, created_at, customer_id, customer_name, customer_phone,"
            " status, gross_paise, item_discount_paise, bill_discount_type, bill_discount_value,"
            " bill_discount_paise, discount_reason, gst_enabled, prices_include_tax, inter_state, taxable_paise,"
            " cgst_paise, sgst_paise, igst_paise, round_off_paise, total_paise, tendered_paise, change_paise,"
            " note, shop_gstin, shop_state, customer_state)"
            " VALUES (?,?,?,?,?,?,'COMPLETED',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (invoice_no, req.client_ref, now_str(), customer_id,
             "" if cust["is_walkin"] else cust["name"], "" if cust["is_walkin"] else cust["phone"],
             totals.gross, totals.item_discount, bd.type if totals.bill_discount else "NONE",
             bd.value if totals.bill_discount else 0, totals.bill_discount, (bd.reason or "").strip()[:120],
             int(cfg.enabled), int(cfg.inclusive), int(cfg.inter_state), totals.taxable, totals.cgst,
             totals.sgst, totals.igst, totals.round_off, totals.total, st.tendered, st.change,
             (req.note or "").strip(), settings.get("shop_gstin"), settings.get("shop_state"),
             (req.customer_state or "").strip()[:60]),
        ).lastrowid

        for no, (ln, r) in enumerate(zip(req.lines, totals.lines, strict=True), start=1):
            db.execute(
                "INSERT INTO sale_items(sale_id, line_no, variant_id, product_name, size, colour, sku, barcode,"
                " hsn_code, category_name, qty, unit_price_paise, mrp_paise, unit_cost_paise, item_discount_type,"
                " item_discount_value, item_discount_paise, bill_discount_paise, gst_rate_bp, taxable_paise,"
                " cgst_paise, sgst_paise, igst_paise, line_total_paise)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sale_id, no, ln.variant_id, ln.product_name, ln.size, ln.colour, ln.sku, ln.barcode,
                 ln.hsn_code, ln.category_name, ln.qty, ln.unit_price, ln.mrp, ln.unit_cost,
                 ln.disc_type if r.item_discount else "NONE", ln.disc_value if r.item_discount else 0,
                 r.item_discount, r.bill_discount, r.gst_rate_bp, r.taxable, r.cgst, r.sgst, r.igst,
                 r.line_total))
            record_movement(db, ln.variant_id, "SALE", -ln.qty, ref_type="SALE", ref_id=sale_id,
                            ref_text=invoice_no, description=ln.description)

        for method, amount, ref in st.payments:
            db.execute("INSERT INTO sale_payments(sale_id, method, amount_paise, reference) VALUES (?,?,?,?)",
                       (sale_id, method, amount, ref))
        if exchange_amount:
            db.execute("UPDATE returns SET exchange_sale_id = ? WHERE id = ? AND exchange_sale_id IS NULL",
                       (sale_id, req.payment.exchange_return_id))
        return int(sale_id)


def cancel_sale(db: Database, sale_id: int, reason: str) -> None:
    """Cancel a bill with a reversal record. Stock comes back through SALE_CANCEL movements."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Please enter a reason for cancelling the bill.")
    with db.transaction():
        sale = db.one("SELECT id, invoice_no, status FROM sales WHERE id = ?", (sale_id,))
        if sale is None:
            raise NotFoundError("Bill not found.")
        if sale["status"] != "COMPLETED":
            raise ValidationError(f"Bill {sale['invoice_no']} is already cancelled.")
        if db.scalar("SELECT COUNT(*) FROM returns WHERE sale_id = ?", (sale_id,)):
            raise ValidationError(
                f"Bill {sale['invoice_no']} has returns against it, so it cannot be cancelled. "
                "Use Returns for the remaining items instead.")
        db.execute("INSERT INTO sale_cancellations(sale_id, reason, created_at) VALUES (?,?,?)",
                   (sale_id, reason[:200], now_str()))
        db.execute("UPDATE sales SET status = 'CANCELLED' WHERE id = ?", (sale_id,))
        for it in db.all("SELECT variant_id, qty FROM sale_items WHERE sale_id = ?", (sale_id,)):
            record_movement(db, it["variant_id"], "SALE_CANCEL", it["qty"], ref_type="SALE", ref_id=sale_id,
                            ref_text=sale["invoice_no"], reason=reason[:200])
        # Exchange credit used by this bill becomes available again.
        db.execute("UPDATE returns SET exchange_sale_id = NULL WHERE exchange_sale_id = ?", (sale_id,))


def get_sale(db: Database, sale_id: int) -> dict:
    row = db.one("SELECT * FROM sales WHERE id = ?", (sale_id,))
    if row is None:
        raise NotFoundError("Bill not found.")
    sale = dict(row)
    sale["items"] = [dict(r) for r in db.all(
        "SELECT i.*, COALESCE((SELECT SUM(ri.qty) FROM return_items ri WHERE ri.sale_item_id = i.id), 0)"
        " AS returned_qty FROM sale_items i WHERE i.sale_id = ? ORDER BY i.line_no", (sale_id,))]
    sale["payments"] = [dict(r) for r in db.all(
        "SELECT method, amount_paise, reference FROM sale_payments WHERE sale_id = ? ORDER BY id", (sale_id,))]
    sale["returns"] = [dict(r) for r in db.all(
        "SELECT id, return_no, created_at, refund_method, refund_paise, reason FROM returns WHERE sale_id = ? "
        "ORDER BY id", (sale_id,))]
    canc = db.one("SELECT reason, created_at FROM sale_cancellations WHERE sale_id = ?", (sale_id,))
    sale["cancellation"] = dict(canc) if canc else None
    return sale


def sale_id_by_invoice(db: Database, invoice_no: str) -> int | None:
    return db.scalar("SELECT id FROM sales WHERE invoice_no = ? COLLATE NOCASE", ((invoice_no or "").strip(),))


def search_sales(db: Database, invoice: str = "", date_from: str = "", date_to: str = "",
                 customer: str = "", product: str = "", code: str = "", method: str = "",
                 status: str = "", limit: int = 1000) -> list[dict]:
    sql = [
        "SELECT s.id, s.invoice_no, s.created_at, s.status, s.total_paise,",
        " s.item_discount_paise + s.bill_discount_paise AS discount_paise,",
        " s.cgst_paise + s.sgst_paise + s.igst_paise AS tax_paise,",
        " CASE WHEN c.is_walkin = 1 THEN 'Walk-in' ELSE c.name END AS customer,",
        " (SELECT COALESCE(SUM(qty),0) FROM sale_items i WHERE i.sale_id = s.id) AS items,",
        " (SELECT GROUP_CONCAT(method, ' + ') FROM sale_payments p WHERE p.sale_id = s.id) AS methods,",
        " (SELECT COUNT(*) FROM returns r WHERE r.sale_id = s.id) AS return_count",
        "FROM sales s JOIN customers c ON c.id = s.customer_id WHERE 1=1",
    ]
    params: list = []
    if invoice.strip():
        sql.append("AND s.invoice_no LIKE ?")
        params.append(f"%{invoice.strip()}%")
    if date_from:
        sql.append("AND s.created_at >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        sql.append("AND s.created_at <= ?")
        params.append(date_to + " 23:59:59")
    if customer.strip():
        like = f"%{customer.strip()}%"
        sql.append("AND (c.name LIKE ? OR c.phone LIKE ?)")
        params += [like, like]
    if product.strip():
        sql.append("AND EXISTS (SELECT 1 FROM sale_items i WHERE i.sale_id = s.id AND i.product_name LIKE ?)")
        params.append(f"%{product.strip()}%")
    if code.strip():
        sql.append("AND EXISTS (SELECT 1 FROM sale_items i WHERE i.sale_id = s.id AND (i.barcode = ? OR i.sku = ?"
                   " COLLATE NOCASE))")
        params += [code.strip(), code.strip()]
    if method:
        sql.append("AND EXISTS (SELECT 1 FROM sale_payments p WHERE p.sale_id = s.id AND p.method = ?)")
        params.append(method)
    if status:
        sql.append("AND s.status = ?")
        params.append(status)
    sql.append("ORDER BY s.id DESC LIMIT ?")
    params.append(limit)
    return [dict(r) for r in db.all(" ".join(sql), tuple(params))]


# --------------------------------------------------------------- held bills
def hold_bill(db: Database, label: str, state: dict) -> int:
    if not state.get("lines"):
        raise ValidationError("There is nothing to hold. The bill is empty.")
    label = (label or "").strip()[:60] or f"Held at {now_str()[11:16]}"
    with db.transaction():
        return db.execute("INSERT INTO held_bills(label, data_json, created_at) VALUES (?,?,?)",
                          (label, json.dumps(state), now_str())).lastrowid


def list_held(db: Database) -> list[dict]:
    out = []
    for r in db.all("SELECT id, label, data_json, created_at FROM held_bills ORDER BY id"):
        try:
            data = json.loads(r["data_json"])
            lines = data.get("lines", [])
            count = sum(int(x.get("qty", 0)) for x in lines)
            value = sum(int(x.get("unit_price", 0)) * int(x.get("qty", 0)) for x in lines)
        except (ValueError, TypeError, AttributeError):
            count, value = 0, 0
        out.append({"id": r["id"], "label": r["label"], "created_at": r["created_at"], "items": count,
                    "value": value})
    return out


def resume_held(db: Database, held_id: int) -> dict:
    """Load a held bill and remove it from the held list (in one step)."""
    with db.transaction():
        row = db.one("SELECT data_json FROM held_bills WHERE id = ?", (held_id,))
        if row is None:
            raise NotFoundError("That held bill was already resumed or removed.")
        db.execute("DELETE FROM held_bills WHERE id = ?", (held_id,))
    try:
        data = json.loads(row["data_json"])
        if not isinstance(data, dict):
            raise ValueError
        return data
    except ValueError:
        raise ValidationError("The held bill could not be read.") from None


def delete_held(db: Database, held_id: int) -> None:
    with db.transaction():
        db.execute("DELETE FROM held_bills WHERE id = ?", (held_id,))


def describe_payments(payments: list[dict]) -> str:
    return " + ".join(f"{p['method']} {fmt(p['amount_paise'])}" for p in payments) or "No payment (zero bill)"
