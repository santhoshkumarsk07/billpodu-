"""Money is always an integer number of paise. Never use floats for money.

Percentages are stored as integer basis points (1250 = 12.50 %).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import ValidationError

MAX_AMOUNT_PAISE = 10_000_000_00  # Rs 1 crore per field is far above any real bill


def parse_rupees(text: str | int | float | Decimal | None, field: str = "Amount",
                 allow_zero: bool = True) -> int:
    """Convert user text like '1,299.50' into paise. Raises ValidationError."""
    if text is None:
        raise ValidationError(f"{field} is required.")
    s = str(text).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    if s == "":
        raise ValidationError(f"{field} is required.")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValidationError(f"{field} must be a number, for example 499 or 499.50.") from None
    if not d.is_finite():
        raise ValidationError(f"{field} must be a number.")
    if d < 0:
        raise ValidationError(f"{field} cannot be negative.")
    if d != d.quantize(Decimal("0.01")):
        raise ValidationError(f"{field} can have at most 2 decimal places.")
    paise = int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))
    if paise > MAX_AMOUNT_PAISE:
        raise ValidationError(f"{field} is too large.")
    if not allow_zero and paise == 0:
        raise ValidationError(f"{field} must be more than zero.")
    return paise


def parse_percent(text: str | int | float | Decimal | None, field: str = "Percentage") -> int:
    """'12.5' -> 1250 basis points. Must be between 0 and 100."""
    s = str(text if text is not None else "").strip().replace("%", "")
    if s == "":
        return 0
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValidationError(f"{field} must be a number.") from None
    if not d.is_finite() or d < 0 or d > 100:
        raise ValidationError(f"{field} must be between 0 and 100.")
    if d != d.quantize(Decimal("0.01")):
        raise ValidationError(f"{field} can have at most 2 decimal places.")
    return int(d * 100)


def fmt(paise: int, symbol: str = "") -> str:
    """12345 -> '123.45' (Indian digit grouping is not used to keep receipts narrow)."""
    sign = "-" if paise < 0 else ""
    p = abs(int(paise))
    return f"{sign}{symbol}{p // 100:,}.{p % 100:02d}"


def fmt_plain(paise: int) -> str:
    """Like fmt but without thousands separators (for edit boxes and CSV)."""
    sign = "-" if paise < 0 else ""
    p = abs(int(paise))
    return f"{sign}{p // 100}.{p % 100:02d}"


def fmt_percent(bp: int) -> str:
    whole, frac = divmod(int(bp), 100)
    return f"{whole}" if frac == 0 else f"{whole}.{frac:02d}".rstrip("0")


def round_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half-up (for non-negative values)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0:
        return -round_div(-numerator, denominator)
    return (2 * numerator + denominator) // (2 * denominator)


def allocate(total: int, weights: list[int]) -> list[int]:
    """Split `total` across `weights` proportionally so the parts add up exactly.

    Uses the largest-remainder method. All inputs are non-negative integers.
    """
    if total == 0 or not weights:
        return [0] * len(weights)
    wsum = sum(weights)
    if wsum <= 0:
        raise ValueError("cannot allocate across zero weights")
    base = [total * w // wsum for w in weights]
    remainders = [(total * w % wsum, i) for i, w in enumerate(weights)]
    left = total - sum(base)
    for _, i in sorted(remainders, key=lambda r: (-r[0], r[1]))[:left]:
        base[i] += 1
    return base
