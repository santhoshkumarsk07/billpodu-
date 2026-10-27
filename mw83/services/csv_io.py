"""CSV import/export for products and variants.

Import is all-or-nothing: every row is checked first and nothing is saved if
any row has a problem. Exported text cells are protected against spreadsheet
formula injection.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..db import Database
from ..errors import ValidationError
from ..money import fmt_percent, fmt_plain, parse_percent, parse_rupees
from . import catalog
from .catalog import ProductInput, VariantInput

COLUMNS = ["product_name", "category", "brand", "product_sku", "hsn_code", "gst_mode", "gst_rate", "size",
           "colour", "sku", "barcode", "purchase_cost", "selling_price", "mrp", "opening_stock", "min_stock"]
REQUIRED = {"product_name", "selling_price"}
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 50_000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def safe_cell(value) -> str:
    """Stop Excel from treating exported text as a formula."""
    if value is None:
        return ""
    s = str(value)
    if s.startswith(_FORMULA_START) and not _NUMBER_RE.match(s):
        return "'" + s
    return s


def _unsafe_cell(s: str) -> str:
    s = (s or "").strip()
    if len(s) > 1 and s[0] == "'" and s[1] in "=+-@":
        return s[1:]
    return s


def write_csv(path: str | Path, headers: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([safe_cell(h) for h in headers])
        for r in rows:
            w.writerow([safe_cell(c) for c in r])


def export_products(db: Database, path: str | Path, include_archived: bool = False) -> int:
    sql = ("SELECT p.name, c.name AS category, p.brand, p.sku AS product_sku, p.hsn_code, p.gst_mode, p.gst_rate_bp,"
           " v.size, v.colour, v.sku, v.barcode, COALESCE(v.cost_paise, p.cost_paise) AS cost,"
           " COALESCE(v.price_paise, p.price_paise) AS price, COALESCE(v.mrp_paise, p.mrp_paise) AS mrp,"
           " v.stock, p.min_stock FROM variants v JOIN products p ON p.id = v.product_id"
           " LEFT JOIN categories c ON c.id = p.category_id ")
    if not include_archived:
        sql += "WHERE v.active = 1 AND p.active = 1 "
    sql += "ORDER BY p.name COLLATE NOCASE, v.id"
    rows = []
    for r in db.all(sql):
        rows.append([r["name"], r["category"] or "", r["brand"], r["product_sku"] or "", r["hsn_code"],
                     r["gst_mode"], fmt_percent(r["gst_rate_bp"]), r["size"], r["colour"], r["sku"],
                     r["barcode"], fmt_plain(r["cost"]), fmt_plain(r["price"]), fmt_plain(r["mrp"]), r["stock"],
                     "" if r["min_stock"] is None else r["min_stock"]])
    write_csv(path, COLUMNS, rows)
    return len(rows)


def template_csv(path: str | Path) -> None:
    write_csv(path, COLUMNS, [
        ["Classic Cotton Shirt", "Shirts", "", "CCS", "6205", "DEFAULT", "", "M", "Black", "CCS-M-BLK", "",
         "450", "899", "1199", "10", "2"],
        ["Classic Cotton Shirt", "Shirts", "", "CCS", "6205", "DEFAULT", "", "L", "Black", "CCS-L-BLK", "",
         "450", "899", "1199", "8", "2"],
    ])


@dataclass
class ImportResult:
    errors: list[tuple[int, str]] = field(default_factory=list)
    products: int = 0
    variants: int = 0
    new_categories: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _read(path: str | Path) -> list[dict]:
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise ValidationError("The CSV file is too large (20 MB max).")
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValidationError("Cannot read the file's text encoding. Save it as CSV UTF-8.")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError("The CSV file is empty.")
    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    missing = REQUIRED - headers
    if missing:
        raise ValidationError("The CSV file is missing column(s): " + ", ".join(sorted(missing)) +
                              ".\nUse 'Download template' to get the correct columns.")
    rows = []
    for row in reader:
        rows.append({(k or "").strip().lower(): _unsafe_cell(v if isinstance(v, str) else "")
                     for k, v in row.items()})
        if len(rows) > MAX_ROWS:
            raise ValidationError(f"Too many rows (max {MAX_ROWS}).")
    return rows


def _int(value: str, field_name: str) -> int | None:
    if value == "":
        return None
    if not re.fullmatch(r"\d{1,6}", value):
        raise ValidationError(f"{field_name} must be a whole number.")
    return int(value)


def import_products(db: Database, path: str | Path, dry_run: bool = False) -> ImportResult:
    res = ImportResult()
    rows = _read(path)
    if not rows:
        raise ValidationError("The CSV file has no product rows.")
    groups: dict[tuple, tuple[ProductInput, list[int]]] = {}
    existing_cats = {c["name"].lower(): c["id"] for c in catalog.list_categories(db)}
    seen_sku: dict[str, int] = {}
    seen_bc: dict[str, int] = {}
    for n, row in enumerate(rows, start=2):
        try:
            name = row.get("product_name", "")
            if not name:
                raise ValidationError("product_name is empty.")
            price = parse_rupees(row.get("selling_price"), "selling_price", allow_zero=False)
            cost = parse_rupees(row.get("purchase_cost") or "0", "purchase_cost")
            mrp = parse_rupees(row.get("mrp") or "0", "mrp")
            mode = (row.get("gst_mode") or "DEFAULT").upper()
            if mode not in catalog.GST_MODES:
                raise ValidationError("gst_mode must be DEFAULT, FIXED, SLAB or EXEMPT.")
            rate = parse_percent(row.get("gst_rate") or "0", "gst_rate")
            opening = _int(row.get("opening_stock", ""), "opening_stock") or 0
            min_stock = _int(row.get("min_stock", ""), "min_stock")
            category = row.get("category", "")
            key = (name.lower(), category.lower(), row.get("brand", "").lower())
            v = VariantInput(size=row.get("size", ""), colour=row.get("colour", ""), sku=row.get("sku", ""),
                             barcode=row.get("barcode", ""), opening_stock=opening)
            for code, seen, label in ((v.sku.lower(), seen_sku, "SKU"), (v.barcode, seen_bc, "Barcode")):
                if code:
                    if code in seen:
                        raise ValidationError(f"{label} '{code}' is also used on row {seen[code]}.")
                    seen[code] = n
            if key not in groups:
                p = ProductInput(name=name, category_id=None, price=price, brand=row.get("brand", ""),
                                 sku=row.get("product_sku", ""), hsn_code=row.get("hsn_code", ""), gst_mode=mode,
                                 gst_rate_bp=rate, cost=cost, mrp=mrp, min_stock=min_stock)
                p._category_name = category  # type: ignore[attr-defined]
                groups[key] = (p, [])
            p, row_nums = groups[key]
            if price != p.price:
                v.price = price
            if cost != p.cost:
                v.cost = cost
            if mrp != p.mrp:
                v.mrp = mrp
            p.variants.append(v)
            row_nums.append(n)
        except ValidationError as exc:
            res.errors.append((n, exc.message))

    # Check whole products (duplicates against the database, price rules, ...)
    for p, row_nums in groups.values():
        try:
            catalog._validate_product(p)
            catalog._check_unique(db, p, None)
        except ValidationError as exc:
            res.errors.append((row_nums[0], f"{p.name}: {exc.message}"))
    res.errors.sort()
    if res.errors or dry_run:
        res.products = len(groups)
        res.variants = sum(len(p.variants) for p, _ in groups.values())
        return res

    with db.transaction():
        for p, _ in groups.values():
            cat_name = p._category_name  # type: ignore[attr-defined]
            if cat_name:
                cid = existing_cats.get(cat_name.lower())
                if cid is None:
                    cid = catalog.add_category(db, cat_name)
                    existing_cats[cat_name.lower()] = cid
                    res.new_categories.append(cat_name)
                p.category_id = cid
            catalog.save_product(db, p)
            res.products += 1
            res.variants += len(p.variants)
    return res
