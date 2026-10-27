"""Pure bill calculations: discounts, GST, round-off and payment settlement.

No database or UI code here, so it is fast and easy to test. All money is
integer paise and all percentages are basis points (100 bp = 1 %).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..errors import ValidationError
from ..money import allocate, fmt, fmt_percent, round_div

NONE, PERCENT, AMOUNT = "NONE", "PERCENT", "AMOUNT"
MAX_QTY = 9999


@dataclass
class CartLine:
    variant_id: int
    product_name: str
    size: str
    colour: str
    sku: str
    barcode: str
    unit_price: int
    mrp: int = 0
    unit_cost: int = 0
    hsn_code: str = ""
    category_name: str = ""
    gst_mode: str = "DEFAULT"   # DEFAULT / FIXED / SLAB / EXEMPT
    gst_rate_bp: int = 0        # used when gst_mode == FIXED
    qty: int = 1
    disc_type: str = NONE
    disc_value: int = 0         # bp for PERCENT, paise for AMOUNT (whole line)
    stock: int = 0              # stock when added; re-checked when saving

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CartLine":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def description(self) -> str:
        extra = " / ".join(x for x in (self.size, self.colour) if x)
        return f"{self.product_name} ({extra})" if extra else self.product_name


@dataclass
class BillDiscount:
    type: str = NONE
    value: int = 0
    reason: str = ""


@dataclass
class TaxConfig:
    enabled: bool = False
    inclusive: bool = True
    inter_state: bool = False
    default_rate_bp: int = 500
    slab_threshold: int = 250000
    slab_low_bp: int = 500
    slab_high_bp: int = 1800


@dataclass
class LineResult:
    gross: int
    item_discount: int
    bill_discount: int
    net: int
    gst_rate_bp: int
    taxable: int
    cgst: int
    sgst: int
    igst: int
    line_total: int


@dataclass
class BillTotals:
    lines: list[LineResult] = field(default_factory=list)
    gross: int = 0
    item_discount: int = 0
    bill_discount: int = 0
    taxable: int = 0
    cgst: int = 0
    sgst: int = 0
    igst: int = 0
    round_off: int = 0
    total: int = 0
    item_count: int = 0

    @property
    def total_discount(self) -> int:
        return self.item_discount + self.bill_discount

    @property
    def tax(self) -> int:
        return self.cgst + self.sgst + self.igst


def discount_amount(base: int, disc_type: str, value: int, what: str) -> int:
    if disc_type == NONE or value == 0:
        return 0
    if value < 0:
        raise ValidationError(f"{what} cannot be negative.")
    if disc_type == PERCENT:
        if value > 10000:
            raise ValidationError(f"{what} cannot be more than 100%.")
        return round_div(base * value, 10000)
    if disc_type == AMOUNT:
        if value > base:
            raise ValidationError(f"{what} ({fmt(value)}) is more than the amount ({fmt(base)}).")
        return value
    raise ValidationError(f"Unknown discount type for {what}.")


def line_rate(line: CartLine, net: int, cfg: TaxConfig) -> int:
    if not cfg.enabled or line.gst_mode == "EXEMPT":
        return 0
    if line.gst_mode == "FIXED":
        return line.gst_rate_bp
    if line.gst_mode == "SLAB":
        unit_net = round_div(net, line.qty) if line.qty else 0
        unit_value = round_div(unit_net * 10000, 10000 + cfg.slab_low_bp) if cfg.inclusive else unit_net
        return cfg.slab_low_bp if unit_value <= cfg.slab_threshold else cfg.slab_high_bp
    return cfg.default_rate_bp


def split_tax(net: int, rate_bp: int, inclusive: bool, inter_state: bool) -> tuple[int, int, int, int, int]:
    """Return (taxable, cgst, sgst, igst, line_total) for a discounted line amount."""
    if rate_bp <= 0:
        return net, 0, 0, 0, net
    if inclusive:
        taxable = round_div(net * 10000, 10000 + rate_bp)
        tax = net - taxable
        total = net
    else:
        taxable = net
        tax = round_div(net * rate_bp, 10000)
        total = net + tax
    if inter_state:
        return taxable, 0, 0, tax, total
    cgst = tax // 2
    return taxable, cgst, tax - cgst, 0, total


def validate_line(line: CartLine) -> None:
    if not isinstance(line.qty, int) or line.qty <= 0:
        raise ValidationError(f"Quantity for {line.description} must be at least 1.")
    if line.qty > MAX_QTY:
        raise ValidationError(f"Quantity for {line.description} is too large.")
    if line.unit_price < 0:
        raise ValidationError(f"Price for {line.description} cannot be negative.")


def compute(lines: list[CartLine], bill: BillDiscount, cfg: TaxConfig,
            round_off: bool = False, max_discount_bp: int = 10000) -> BillTotals:
    t = BillTotals()
    if not lines:
        if bill.type != NONE and bill.value:
            raise ValidationError("Add items before giving a bill discount.")
        return t
    gross_list, after_item = [], []
    for ln in lines:
        validate_line(ln)
        gross = ln.unit_price * ln.qty
        disc = discount_amount(gross, ln.disc_type, ln.disc_value, f"Discount on {ln.description}")
        gross_list.append(gross)
        after_item.append(gross - disc)
    base = sum(after_item)
    bill_disc = discount_amount(base, bill.type, bill.value, "Bill discount")
    if bill_disc > 0 and base == 0:
        raise ValidationError("Bill discount is more than the amount.")
    shares = allocate(bill_disc, after_item) if bill_disc else [0] * len(lines)

    t.gross = sum(gross_list)
    t.item_discount = t.gross - base
    t.bill_discount = bill_disc
    if t.gross and t.total_discount * 10000 > t.gross * max_discount_bp:
        raise ValidationError(
            f"Total discount ({fmt(t.total_discount)}) is above the allowed limit of "
            f"{fmt_percent(max_discount_bp)}% set in Settings."
        )
    for ln, gross, ai, share in zip(lines, gross_list, after_item, shares, strict=True):
        net = ai - share
        rate = line_rate(ln, net, cfg)
        taxable, cgst, sgst, igst, total = split_tax(net, rate, cfg.inclusive, cfg.inter_state)
        t.lines.append(LineResult(gross, gross - ai, share, net, rate, taxable, cgst, sgst, igst, total))
        t.taxable += taxable
        t.cgst += cgst
        t.sgst += sgst
        t.igst += igst
        t.item_count += ln.qty
    before_round = sum(r.line_total for r in t.lines)
    if round_off:
        rounded = round_div(before_round, 100) * 100
        t.round_off = rounded - before_round
    t.total = before_round + t.round_off
    return t


@dataclass
class Settlement:
    payments: list[tuple[str, int, str]]  # (method, amount, reference)
    tendered: int
    change: int
    cash_due: int


def settle(total: int, upi: int = 0, card: int = 0, exchange: int = 0, cash_received: int = 0,
           upi_ref: str = "", card_ref: str = "", exchange_ref: str = "") -> Settlement:
    """Work out the payment split. Whatever UPI/card/exchange does not cover is cash."""
    for name, v in (("UPI amount", upi), ("Card amount", card), ("Exchange credit", exchange),
                    ("Amount received", cash_received)):
        if v < 0:
            raise ValidationError(f"{name} cannot be negative.")
    if exchange > total:
        raise ValidationError(
            f"Exchange credit ({fmt(exchange)}) is more than this bill ({fmt(total)}). "
            "Add more items, or refund the return in cash instead."
        )
    non_cash = upi + card + exchange
    if non_cash > total:
        raise ValidationError(f"UPI + card + exchange ({fmt(non_cash)}) is more than the bill ({fmt(total)}).")
    cash_due = total - non_cash
    if cash_received < cash_due:
        raise ValidationError(
            f"Cash received ({fmt(cash_received)}) is less than the cash due ({fmt(cash_due)})."
        )
    payments: list[tuple[str, int, str]] = []
    if cash_due:
        payments.append(("CASH", cash_due, ""))
    if upi:
        payments.append(("UPI", upi, upi_ref.strip()[:60]))
    if card:
        payments.append(("CARD", card, card_ref.strip()[:60]))
    if exchange:
        payments.append(("EXCHANGE", exchange, exchange_ref))
    return Settlement(payments, cash_received, cash_received - cash_due, cash_due)
