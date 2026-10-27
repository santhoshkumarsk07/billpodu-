"""Receipt layout as plain text lines, shared by the Windows-driver printout,
raw ESC/POS printing and the PDF copy. 58 mm paper = 32 characters, 80 mm = 48."""
from __future__ import annotations

import textwrap
from dataclasses import dataclass

from ..money import fmt, fmt_percent

WIDTH_CHARS = {"58": 32, "80": 48}
METHOD_NAMES = {"CASH": "Cash", "UPI": "UPI", "CARD": "Card", "EXCHANGE": "Exchange credit"}


@dataclass
class Line:
    text: str
    bold: bool = False
    center: bool = False
    big: bool = False


def _lr(left: str, right: str, width: int) -> str:
    space = width - len(left) - len(right)
    if space < 1:
        left = left[: max(0, width - len(right) - 1)]
        space = 1
    return left + " " * space + right


def _wrap(text: str, width: int, indent: str = "") -> list[str]:
    return textwrap.wrap(text, width=width, subsequent_indent=indent) or [""]


def _ascii(text: str) -> str:
    """Thermal printers in raw mode only know basic characters."""
    return (text or "").replace("₹", "Rs.").replace("’", "'").replace("‘", "'")


def build_receipt(sale: dict, shop: dict, width_chars: int = 48, duplicate: bool = False) -> list[Line]:
    """`sale` is from sales.get_sale(); `shop` holds shop_name, shop_address, shop_phone, shop_gstin,
    receipt_footer, return_policy."""
    w = width_chars
    out: list[Line] = []
    sep = "-" * w

    def add(text="", bold=False, center=False, big=False):
        text = _ascii(text)
        parts = [text] if len(text) <= w else _wrap(text, w, "  ")
        for part in parts:
            out.append(Line(part.center(w).rstrip() if center else part, bold, center, big))

    add(shop.get("shop_name") or "83 MEN'S WEAR", bold=True, center=True, big=True)
    for ln in (shop.get("shop_address") or "").splitlines():
        if ln.strip():
            add(ln.strip(), center=True)
    if shop.get("shop_phone"):
        add(f"Ph: {shop['shop_phone']}", center=True)
    gstin = sale.get("shop_gstin") or ""
    if gstin:
        add(f"GSTIN: {gstin}", center=True)
    add(sep)
    title = "TAX INVOICE" if sale.get("gst_enabled") and gstin else "INVOICE"
    add(title, bold=True, center=True)
    if duplicate:
        add("** DUPLICATE COPY **", bold=True, center=True)
    if sale.get("status") == "CANCELLED":
        add("*** CANCELLED BILL ***", bold=True, center=True)
    dt = sale["created_at"]
    add(_lr(f"Bill: {sale['invoice_no']}", f"{dt[8:10]}-{dt[5:7]}-{dt[0:4]} {dt[11:16]}", w))
    if sale.get("customer_name"):
        cust = sale["customer_name"] + (f" ({sale['customer_phone']})" if sale.get("customer_phone") else "")
        add(f"Customer: {cust}")
    if sale.get("inter_state") and sale.get("customer_state"):
        add(f"Place of supply: {sale['customer_state']}")
    add(sep)
    add(_lr("Item", "Qty x Rate      Amount", w) if w >= 40 else _lr("Item", "Amount", w), bold=True)
    add(sep)
    for it in sale["items"]:
        desc = it["product_name"]
        extra = " / ".join(x for x in (it["size"], it["colour"]) if x)
        if extra:
            desc += f" ({extra})"
        add(desc)
        gross = it["unit_price_paise"] * it["qty"]
        qty_rate = f"{it['qty']} x {fmt(it['unit_price_paise'])}"
        add(_lr("  " + qty_rate, fmt(gross), w))
        disc = it["item_discount_paise"]
        if disc:
            label = "  Discount"
            if it["item_discount_type"] == "PERCENT":
                label += f" {fmt_percent(it['item_discount_value'])}%"
            add(_lr(label, "-" + fmt(disc), w))
        if sale.get("gst_enabled") and it["gst_rate_bp"]:
            hsn = f" HSN {it['hsn_code']}" if it["hsn_code"] else ""
            add(f"  GST {fmt_percent(it['gst_rate_bp'])}%{hsn}")
    add(sep)
    item_count = sum(it["qty"] for it in sale["items"])
    add(_lr(f"Items: {len(sale['items'])}  Qty: {item_count}", "", w))
    add(_lr("Subtotal", fmt(sale["gross_paise"]), w))
    if sale["item_discount_paise"]:
        add(_lr("Item discounts", "-" + fmt(sale["item_discount_paise"]), w))
    if sale["bill_discount_paise"]:
        label = "Bill discount"
        if sale["bill_discount_type"] == "PERCENT":
            label += f" {fmt_percent(sale['bill_discount_value'])}%"
        add(_lr(label, "-" + fmt(sale["bill_discount_paise"]), w))
    total_disc = sale["item_discount_paise"] + sale["bill_discount_paise"]
    if total_disc:
        add(_lr("Total discount", fmt(total_disc), w))
        if sale.get("discount_reason"):
            add(f"  ({sale['discount_reason']})")
    if sale.get("gst_enabled"):
        tax = sale["cgst_paise"] + sale["sgst_paise"] + sale["igst_paise"]
        add(_lr("Taxable value", fmt(sale["taxable_paise"]), w))
        if sale["igst_paise"]:
            add(_lr("IGST", fmt(sale["igst_paise"]), w))
        else:
            add(_lr("CGST", fmt(sale["cgst_paise"]), w))
            add(_lr("SGST", fmt(sale["sgst_paise"]), w))
        if sale.get("prices_include_tax") and tax:
            add("(Prices include GST)")
    if sale.get("round_off_paise"):
        add(_lr("Round off", fmt(sale["round_off_paise"]), w))
    add(sep)
    add(_lr("TOTAL  Rs.", fmt(sale["total_paise"]), w), bold=True, big=True)
    add(sep)
    for p in sale["payments"]:
        name = METHOD_NAMES.get(p["method"], p["method"])
        ref = f" ({p['reference']})" if p.get("reference") else ""
        add(_lr(f"Paid by {name}{ref}", fmt(p["amount_paise"]), w))
    if any(p["method"] == "CASH" for p in sale["payments"]) or sale["tendered_paise"]:
        add(_lr("Cash received", fmt(sale["tendered_paise"]), w))
        add(_lr("Change", fmt(sale["change_paise"]), w), bold=True)
    if sale.get("gst_enabled") and (sale["cgst_paise"] or sale["igst_paise"]) and w >= 40:
        add(sep)
        add(_lr("GST%  Taxable", "CGST     SGST     IGST", w))
        by_rate: dict[int, list[int]] = {}
        for it in sale["items"]:
            r = by_rate.setdefault(it["gst_rate_bp"], [0, 0, 0, 0])
            r[0] += it["taxable_paise"]
            r[1] += it["cgst_paise"]
            r[2] += it["sgst_paise"]
            r[3] += it["igst_paise"]
        for rate, (tx, c, s, i) in sorted(by_rate.items()):
            add(_lr(f"{fmt_percent(rate):>4} {fmt(tx):>9}", f"{fmt(c):>8} {fmt(s):>8} {fmt(i):>8}", w))
    if sale.get("note"):
        add(sep)
        add(f"Note: {sale['note']}")
    add(sep)
    if shop.get("receipt_footer"):
        add(shop["receipt_footer"], center=True)
    if shop.get("return_policy"):
        add(shop["return_policy"], center=True)
    return out


def build_test_receipt(shop: dict, width_chars: int) -> list[Line]:
    w = width_chars
    lines = [Line((shop.get("shop_name") or "83 MEN'S WEAR").center(w).rstrip(), True, True, True),
             Line("PRINTER TEST".center(w).rstrip(), True, True), Line("-" * w),
             Line(_lr("Left", "Right", w)), Line("0123456789" * (w // 10) + "0123456789"[: w % 10]),
             Line(_lr("TOTAL  Rs.", "1,234.50", w), True, False, True), Line("-" * w),
             Line("If every line fits and nothing is cut", False),
             Line("off, the paper width setting is right.", False)]
    return lines


def as_text(lines: list[Line]) -> str:
    return "\n".join(ln.text for ln in lines)
