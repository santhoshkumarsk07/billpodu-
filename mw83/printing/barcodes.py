"""Barcode encoding via python-barcode. We only take the bar pattern and draw it
ourselves, so bars stay sharp at any printer resolution."""
from __future__ import annotations

import barcode
from barcode.errors import BarcodeError

from ..errors import ValidationError


def ean13_check_digit(first12: str) -> int:
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("need 12 digits")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return (10 - total % 10) % 10


def is_valid_ean13(code: str) -> bool:
    return len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == int(code[12])


def modules(code: str, kind: str = "CODE128") -> str:
    """Return the bar pattern as a string of '1' (bar) and '0' (space) modules.

    EAN-13 is only used when the code is a valid EAN-13; everything else is Code 128.
    """
    code = (code or "").strip()
    if not code:
        raise ValidationError("There is no barcode to print.")
    try:
        if kind == "EAN13":
            if not is_valid_ean13(code):
                raise ValidationError(f"'{code}' is not a valid EAN-13 barcode. Use Code 128 for this item.")
            # python-barcode wants the first 12 digits and adds the checksum itself.
            pattern = barcode.get("ean13", code[:12]).build()[0]
        else:
            if any(ord(ch) < 32 or ord(ch) > 126 for ch in code):
                raise ValidationError("Barcode contains characters that Code 128 cannot print.")
            pattern = barcode.get("code128", code).build()[0]
    except BarcodeError as exc:
        raise ValidationError(f"Cannot make a barcode from '{code}': {exc}") from None
    if not pattern or set(pattern) - {"0", "1"}:
        raise ValidationError("Barcode could not be generated.")
    return pattern


def effective_kind(code: str, preferred: str) -> str:
    """EAN-13 if requested and valid, otherwise Code 128."""
    return "EAN13" if preferred == "EAN13" and is_valid_ean13(code) else "CODE128"
