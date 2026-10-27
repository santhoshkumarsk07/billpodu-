"""Owner-editable settings stored in the `settings` table as text."""
from __future__ import annotations

import re

from ..db import Database
from ..errors import ValidationError

DEFAULTS: dict[str, str] = {
    # shop
    "shop_name": "83 MEN'S WEAR",
    "shop_address": "",
    "shop_phone": "",
    "shop_gstin": "",
    "shop_state": "",
    "invoice_prefix": "83MW",
    "financial_year": "",
    "receipt_footer": "Thank you! Visit again.",
    "return_policy": "",
    # billing
    "default_payment": "CASH",
    "max_discount_percent_bp": "10000",  # discount limit (100 % = no limit)
    "auto_print_receipt": "1",
    "round_off_total": "0",
    # gst
    "gst_enabled": "0",
    "prices_include_tax": "1",
    "default_gst_rate_bp": "500",
    "slab_threshold_paise": "250000",
    "slab_low_rate_bp": "500",
    "slab_high_rate_bp": "1800",
    # printers
    "receipt_printer": "",
    "receipt_width_mm": "80",
    "receipt_mode": "DRIVER",  # DRIVER (Windows driver) or RAW (ESC/POS text)
    "receipt_font_pt": "8",
    "receipt_cut": "1",
    "tag_printer": "",
    "tag_width_mm": "50",
    "tag_height_mm": "25",
    "tag_margin_mm": "1.5",
    "tag_font_pt": "7",
    "tag_barcode_type": "CODE128",
    "tag_show_shop": "1",
    "tag_show_name": "1",
    "tag_show_size": "1",
    "tag_show_colour": "1",
    "tag_show_sku": "0",
    "tag_show_mrp": "1",
    "tag_show_price": "1",
    # inventory
    "default_min_stock": "2",
    "confirm_adjustments": "1",
    "large_adjustment_qty": "20",
    # backup
    "backup_dir": "",
    "auto_backup": "1",
    "backups_to_keep": "30",
    "last_auto_backup": "",
    # ui
    "invoice_digits": "4",
}

PAYMENT_METHODS = ["CASH", "UPI", "CARD"]

INDIAN_STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
    "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9/_-]{1,12}$")


class Settings:
    def __init__(self, db: Database):
        self.db = db
        self._cache: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._cache is None:
            rows = self.db.all("SELECT key, value FROM settings")
            self._cache = {r["key"]: r["value"] for r in rows}
        return self._cache

    def invalidate(self) -> None:
        self._cache = None

    def get(self, key: str) -> str:
        return self._load().get(key, DEFAULTS.get(key, ""))

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except ValueError:
            return int(DEFAULTS.get(key, "0") or 0)

    def get_float(self, key: str) -> float:
        try:
            return float(self.get(key))
        except ValueError:
            return float(DEFAULTS.get(key, "0") or 0)

    def get_bool(self, key: str) -> bool:
        return self.get(key) == "1"

    def set_many(self, values: dict[str, str]) -> None:
        values = {k: ("1" if v is True else "0" if v is False else str(v)) for k, v in values.items()}
        self.validate(values)
        with self.db.transaction():
            for k, v in values.items():
                if k not in DEFAULTS:
                    raise ValidationError(f"Unknown setting '{k}'.")
                self.db.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, v),
                )
        self.invalidate()

    def set(self, key: str, value) -> None:
        self.set_many({key: value})

    @staticmethod
    def validate(values: dict[str, str]) -> None:
        if "shop_name" in values and not values["shop_name"].strip():
            raise ValidationError("Shop name cannot be empty.")
        if "invoice_prefix" in values and not PREFIX_RE.match(values["invoice_prefix"]):
            raise ValidationError(
                "Invoice prefix may use letters, digits, '-', '/' or '_' (up to 12 characters)."
            )
        gstin = values.get("shop_gstin", "").strip().upper()
        if gstin and not GSTIN_RE.match(gstin):
            raise ValidationError("GSTIN should be 15 characters, for example 33ABCDE1234F1Z5.")
        if values.get("gst_enabled") == "1" and "shop_state" in values and not values["shop_state"]:
            raise ValidationError("Please choose the shop's state when GST is enabled.")
        if "receipt_width_mm" in values and values["receipt_width_mm"] not in ("58", "80"):
            raise ValidationError("Receipt width must be 58 mm or 80 mm.")
        if "receipt_mode" in values and values["receipt_mode"] not in ("DRIVER", "RAW"):
            raise ValidationError("Unknown receipt print mode.")
        if "default_payment" in values and values["default_payment"] not in PAYMENT_METHODS:
            raise ValidationError("Unknown payment method.")
        for key, lo, hi in (
            ("tag_width_mm", 15, 150), ("tag_height_mm", 10, 150), ("tag_margin_mm", 0, 20),
            ("tag_font_pt", 4, 30), ("receipt_font_pt", 5, 20), ("backups_to_keep", 1, 365),
            ("default_min_stock", 0, 100000), ("large_adjustment_qty", 1, 100000),
            ("max_discount_percent_bp", 0, 10000), ("default_gst_rate_bp", 0, 10000),
            ("slab_low_rate_bp", 0, 10000), ("slab_high_rate_bp", 0, 10000),
            ("slab_threshold_paise", 0, 10**10), ("invoice_digits", 1, 8),
        ):
            if key in values:
                try:
                    num = float(values[key])
                except ValueError:
                    raise ValidationError(f"Setting '{key}' must be a number.") from None
                if not lo <= num <= hi:
                    raise ValidationError(f"Setting '{key}' must be between {lo} and {hi}.")
