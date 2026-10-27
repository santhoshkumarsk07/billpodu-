"""Categories, products and variants. Products are archived, never deleted."""
from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths
from ..db import Database, now_str
from ..errors import NotFoundError, ValidationError
from .inventory import record_movement

CODE_RE = re.compile(r"^[A-Za-z0-9._/+-]{1,32}$")
GST_MODES = ("DEFAULT", "FIXED", "SLAB", "EXEMPT")
MAX_IMAGE_BYTES = 15 * 1024 * 1024
ITEM_NO_MAX_DIGITS = 6  # short numbers typed at the till are item numbers; real barcodes are longer


# ----------------------------------------------------------------- categories
def list_categories(db: Database) -> list[dict]:
    return [dict(r) for r in db.all(
        "SELECT c.id, c.name, (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id) AS products "
        "FROM categories c ORDER BY c.name COLLATE NOCASE")]


def _category_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Category name cannot be empty.")
    if len(name) > 60:
        raise ValidationError("Category name is too long (60 characters max).")
    return name


def add_category(db: Database, name: str) -> int:
    name = _category_name(name)
    try:
        with db.transaction():
            return db.execute("INSERT INTO categories(name, created_at) VALUES (?, ?)",
                              (name, now_str())).lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError(f"A category called '{name}' already exists.") from None


def rename_category(db: Database, category_id: int, name: str) -> None:
    name = _category_name(name)
    try:
        with db.transaction():
            db.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
    except sqlite3.IntegrityError:
        raise ValidationError(f"A category called '{name}' already exists.") from None


def delete_category(db: Database, category_id: int) -> None:
    count = db.scalar("SELECT COUNT(*) FROM products WHERE category_id = ?", (category_id,), 0)
    if count:
        raise ValidationError(
            f"This category has {count} product(s). Move them to another category first "
            "(archived products count too).")
    with db.transaction():
        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def category_id_by_name(db: Database, name: str) -> int | None:
    return db.scalar("SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (name.strip(),))


# ------------------------------------------------------------------ products
@dataclass
class VariantInput:
    id: int | None = None
    size: str = ""
    colour: str = ""
    sku: str = ""
    barcode: str = ""
    price: int | None = None    # None = use product price
    mrp: int | None = None
    cost: int | None = None
    opening_stock: int = 0      # only used for new variants
    active: bool = True


@dataclass
class ProductInput:
    name: str
    category_id: int | None
    price: int
    brand: str = ""
    sku: str = ""
    hsn_code: str = ""
    gst_mode: str = "DEFAULT"
    gst_rate_bp: int = 0
    cost: int = 0
    mrp: int = 0
    min_stock: int | None = None
    variants: list[VariantInput] = field(default_factory=list)


def _clean_code(value: str, what: str, required: bool) -> str:
    value = (value or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{what} is required.")
        return ""
    if not CODE_RE.match(value):
        raise ValidationError(
            f"{what} '{value}' may only use letters, digits and . _ / + - (no spaces, 32 characters max).")
    return value


def _new_barcode(db: Database) -> str:
    """Internal EAN-13 in the 2xxxxxxxxxxxx 'in-store' range, unique in the database."""
    from ..printing.barcodes import ean13_check_digit

    while True:
        n = db.next_sequence("auto_barcode")
        body = f"2{n:011d}"
        code = body + str(ean13_check_digit(body))
        if not db.scalar("SELECT 1 FROM variants WHERE barcode = ?", (code,)):
            return code


def _new_sku(db: Database) -> str:
    while True:
        code = f"MW{db.next_sequence('auto_sku'):06d}"
        if not db.scalar("SELECT 1 FROM variants WHERE sku = ? COLLATE NOCASE", (code,)):
            return code


def _validate_product(p: ProductInput) -> None:
    p.name = (p.name or "").strip()
    if not p.name:
        raise ValidationError("Product name is required.")
    if len(p.name) > 120:
        raise ValidationError("Product name is too long (120 characters max).")
    p.brand = (p.brand or "").strip()[:60]
    p.hsn_code = (p.hsn_code or "").strip()
    if p.hsn_code and not re.fullmatch(r"[0-9]{4,8}", p.hsn_code):
        raise ValidationError("HSN code should be 4 to 8 digits.")
    if p.gst_mode not in GST_MODES:
        raise ValidationError("Unknown GST option.")
    if not 0 <= p.gst_rate_bp <= 10000:
        raise ValidationError("GST rate must be between 0 and 100%.")
    p.sku = _clean_code(p.sku, "Product SKU", False)
    for v in (p.price, p.cost, p.mrp):
        if v < 0:
            raise ValidationError("Prices cannot be negative.")
    if p.price <= 0:
        raise ValidationError("Selling price must be more than zero.")
    if p.mrp and p.price > p.mrp:
        raise ValidationError("Selling price cannot be more than MRP.")
    if p.min_stock is not None and p.min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative.")
    active = [v for v in p.variants if v.active]
    if not active:
        raise ValidationError("A product needs at least one size/colour row (it can be left blank).")
    seen_sku, seen_bc, seen_combo = set(), set(), set()
    for v in p.variants:
        v.size = (v.size or "").strip()[:20]
        v.colour = (v.colour or "").strip()[:30]
        v.sku = _clean_code(v.sku, "SKU", False)
        v.barcode = _clean_code(v.barcode, "Barcode", False)
        label = " / ".join(x for x in (v.size, v.colour) if x) or "the item"
        for amount in (v.price, v.mrp, v.cost):
            if amount is not None and amount < 0:
                raise ValidationError(f"Prices for {label} cannot be negative.")
        price = v.price if v.price is not None else p.price
        mrp = v.mrp if v.mrp is not None else p.mrp
        if price <= 0:
            raise ValidationError(f"Selling price for {label} must be more than zero.")
        if mrp and price > mrp:
            raise ValidationError(f"Selling price for {label} cannot be more than its MRP.")
        if v.opening_stock < 0 or v.opening_stock > 100000:
            raise ValidationError(f"Opening stock for {label} must be between 0 and 100000.")
        combo = (v.size.lower(), v.colour.lower())
        if combo in seen_combo:
            raise ValidationError(f"Size/colour '{label}' is listed twice.")
        seen_combo.add(combo)
        if v.sku:
            if v.sku.lower() in seen_sku:
                raise ValidationError(f"SKU '{v.sku}' is used twice in this product.")
            seen_sku.add(v.sku.lower())
        if v.barcode:
            if v.barcode in seen_bc:
                raise ValidationError(f"Barcode '{v.barcode}' is used twice in this product.")
            seen_bc.add(v.barcode)


def _check_unique(db: Database, p: ProductInput, product_id: int | None) -> None:
    if p.sku:
        other = db.one("SELECT name FROM products WHERE sku = ? AND id IS NOT ?", (p.sku, product_id))
        if other:
            raise ValidationError(f"Product SKU '{p.sku}' is already used by '{other['name']}'.")
    for v in p.variants:
        if v.sku:
            other = db.one(
                "SELECT p.name, v.size, v.colour FROM variants v JOIN products p ON p.id = v.product_id "
                "WHERE v.sku = ? COLLATE NOCASE AND v.id IS NOT ?", (v.sku, v.id))
            if other:
                raise ValidationError(f"Duplicate SKU: '{v.sku}' is already used by {_describe(other)}.")
        if v.barcode:
            other = db.one(
                "SELECT p.name, v.size, v.colour FROM variants v JOIN products p ON p.id = v.product_id "
                "WHERE v.barcode = ? AND v.id IS NOT ?", (v.barcode, v.id))
            if other:
                raise ValidationError(
                    f"Duplicate barcode: '{v.barcode}' is already used by {_describe(other)}.")


def _describe(row) -> str:
    extra = " / ".join(x for x in (row["size"], row["colour"]) if x)
    return f"'{row['name']}" + (f" ({extra})'" if extra else "'")


def save_product(db: Database, p: ProductInput, product_id: int | None = None) -> int:
    """Create or update a product and its variants in one transaction."""
    _validate_product(p)
    try:
        with db.transaction():
            _check_unique(db, p, product_id)
            ts = now_str()
            values = (p.name, p.category_id, p.brand, p.sku or None, p.hsn_code, p.gst_mode, p.gst_rate_bp,
                      p.cost, p.price, p.mrp, p.min_stock)
            if product_id is None:
                product_id = db.execute(
                    "INSERT INTO products(name, category_id, brand, sku, hsn_code, gst_mode, gst_rate_bp, "
                    "cost_paise, price_paise, mrp_paise, min_stock, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values + (ts, ts)).lastrowid
            else:
                if not db.scalar("SELECT 1 FROM products WHERE id = ?", (product_id,)):
                    raise NotFoundError("This product no longer exists.")
                db.execute(
                    "UPDATE products SET name=?, category_id=?, brand=?, sku=?, hsn_code=?, gst_mode=?, "
                    "gst_rate_bp=?, cost_paise=?, price_paise=?, mrp_paise=?, min_stock=?, updated_at=? "
                    "WHERE id=?", values + (ts, product_id))
            for v in p.variants:
                _save_variant(db, product_id, v, p.name)
        return product_id
    except sqlite3.IntegrityError as exc:
        msg = str(exc)
        if "barcode" in msg:
            raise ValidationError("Duplicate barcode: that barcode is already used by another item.") from None
        if "sku" in msg:
            raise ValidationError("Duplicate SKU: that SKU is already used by another item.") from None
        if "size" in msg or "colour" in msg:
            raise ValidationError(
                "This product already has that size/colour (maybe archived). Re-activate it instead.") from None
        raise


def _save_variant(db: Database, product_id: int, v: VariantInput, product_name: str) -> None:
    if v.id is None:
        if not v.active:
            return
        sku = v.sku or _new_sku(db)
        barcode = v.barcode or _new_barcode(db)
        v.id = db.execute(
            "INSERT INTO variants(product_id, size, colour, sku, barcode, price_paise, mrp_paise, cost_paise, "
            "stock, active, created_at) VALUES (?,?,?,?,?,?,?,?,0,1,?)",
            (product_id, v.size, v.colour, sku, barcode, v.price, v.mrp, v.cost, now_str())).lastrowid
        v.sku, v.barcode = sku, barcode
        if v.opening_stock:
            record_movement(db, v.id, "OPENING", v.opening_stock, reason="Opening stock",
                            description=product_name)
        return
    row = db.one("SELECT product_id FROM variants WHERE id = ?", (v.id,))
    if row is None or row["product_id"] != product_id:
        raise NotFoundError("A size/colour row no longer exists. Please reopen the product.")
    sku = v.sku or _new_sku(db)
    barcode = v.barcode or _new_barcode(db)
    db.execute(
        "UPDATE variants SET size=?, colour=?, sku=?, barcode=?, price_paise=?, mrp_paise=?, cost_paise=?, "
        "active=? WHERE id=?",
        (v.size, v.colour, sku, barcode, v.price, v.mrp, v.cost, 1 if v.active else 0, v.id))


def set_product_active(db: Database, product_id: int, active: bool) -> None:
    with db.transaction():
        db.execute("UPDATE products SET active = ?, updated_at = ? WHERE id = ?",
                   (1 if active else 0, now_str(), product_id))


def get_product(db: Database, product_id: int) -> dict:
    row = db.one("SELECT p.*, c.name AS category FROM products p LEFT JOIN categories c ON c.id = p.category_id "
                 "WHERE p.id = ?", (product_id,))
    if row is None:
        raise NotFoundError("Product not found.")
    d = dict(row)
    d["variants"] = [dict(r) for r in db.all(
        "SELECT * FROM variants WHERE product_id = ? ORDER BY active DESC, id", (product_id,))]
    return d


def list_products(db: Database, text: str = "", category_id: int | None = None, status: str = "ACTIVE",
                  brand: str = "", limit: int = 3000) -> list[dict]:
    sql = [
        "SELECT p.id, p.name, p.brand, p.sku, c.name AS category, p.price_paise, p.mrp_paise, p.cost_paise,",
        " p.gst_mode, p.gst_rate_bp, p.active, p.min_stock,",
        " (SELECT COUNT(*) FROM variants v WHERE v.product_id = p.id AND v.active = 1) AS variant_count,",
        " (SELECT COALESCE(SUM(v.stock),0) FROM variants v WHERE v.product_id = p.id AND v.active = 1) AS stock",
        "FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE 1=1",
    ]
    params: list = []
    if status == "ACTIVE":
        sql.append("AND p.active = 1")
    elif status == "ARCHIVED":
        sql.append("AND p.active = 0")
    if category_id:
        sql.append("AND p.category_id = ?")
        params.append(category_id)
    if brand.strip():
        sql.append("AND p.brand = ? COLLATE NOCASE")
        params.append(brand.strip())
    if text.strip():
        like = f"%{text.strip()}%"
        sql.append("AND (p.name LIKE ? OR p.brand LIKE ? OR p.sku LIKE ? OR EXISTS (SELECT 1 FROM variants v "
                   "WHERE v.product_id = p.id AND (v.sku LIKE ? OR v.barcode LIKE ?)))")
        params += [like, like, like, like, like]
    sql.append("ORDER BY p.name COLLATE NOCASE LIMIT ?")
    params.append(limit)
    return [dict(r) for r in db.all(" ".join(sql), tuple(params))]


def list_brands(db: Database) -> list[str]:
    return [r[0] for r in db.all("SELECT DISTINCT brand FROM products WHERE brand <> '' ORDER BY brand COLLATE NOCASE")]


VARIANT_SELECT = (
    "SELECT v.id AS variant_id, v.product_id, p.name AS product_name, v.size, v.colour, v.sku, v.barcode,"
    " COALESCE(v.price_paise, p.price_paise) AS price, COALESCE(v.mrp_paise, p.mrp_paise) AS mrp,"
    " COALESCE(v.cost_paise, p.cost_paise) AS cost, v.stock, v.active AS variant_active,"
    " p.active AS product_active, p.hsn_code, p.gst_mode, p.gst_rate_bp, p.brand, p.image_file,"
    " c.name AS category_name "
    "FROM variants v JOIN products p ON p.id = v.product_id LEFT JOIN categories c ON c.id = p.category_id ")


def variant_by_code(db: Database, code: str) -> dict | None:
    """Look up by exact barcode, then by SKU. Includes archived items so the caller can explain."""
    code = (code or "").strip()
    if not code:
        return None
    row = db.one(VARIANT_SELECT + "WHERE v.barcode = ?", (code,))
    if row is None:
        row = db.one(VARIANT_SELECT + "WHERE v.sku = ? COLLATE NOCASE", (code,))
    return dict(row) if row else None


def narrow_by_words(matches: list[dict], text: str) -> list[dict]:
    """From several search hits keep those where every typed word is a whole word of the item,
    e.g. 'cotton shirt l black' -> only size L in Black. Falls back to all hits if none fit."""
    words = [w.lower() for w in text.split() if w]

    def tokens(m: dict) -> set[str]:
        parts = " ".join(str(m.get(k) or "") for k in ("product_name", "brand", "size", "colour", "category_name",
                                                         "sku"))
        return {t for t in re.split(r"[^0-9a-z]+", parts.lower()) if t}

    exact = [m for m in matches if all(w in tokens(m) for w in words)]
    return exact or matches


def variant_by_item_no(db: Database, item_no: int) -> dict | None:
    """The item number is the size/colour row's permanent id, shown as 'Item no.' on screens."""
    row = db.one(VARIANT_SELECT + "WHERE v.id = ?", (int(item_no),))
    return dict(row) if row else None


def get_variant(db: Database, variant_id: int) -> dict:
    row = db.one(VARIANT_SELECT + "WHERE v.id = ?", (variant_id,))
    if row is None:
        raise NotFoundError("Item not found.")
    return dict(row)


def search_variants(db: Database, text: str, limit: int = 100, active_only: bool = True) -> list[dict]:
    words = [w for w in (text or "").split() if w]
    sql = VARIANT_SELECT + "WHERE 1=1 "
    params: list = []
    if active_only:
        sql += "AND v.active = 1 AND p.active = 1 "
    for w in words[:5]:
        like = f"%{w}%"
        sql += ("AND (p.name LIKE ? OR p.brand LIKE ? OR v.size LIKE ? OR v.colour LIKE ? OR v.sku LIKE ? "
                "OR v.barcode LIKE ? OR c.name LIKE ? OR p.sku LIKE ? OR CAST(v.id AS TEXT) = ?) ")
        params += [like] * 8 + [w]
    sql += "ORDER BY p.name COLLATE NOCASE, v.size, v.colour LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.all(sql, tuple(params))]


# -------------------------------------------------------------------- images
def set_product_image(db: Database, product_id: int, source: str | Path | None) -> str:
    """Copy an image into the app's images folder after checking it really is an image.

    The picture is re-encoded, so only clean pixel data is stored. Pass None to remove.
    """
    old = db.scalar("SELECT image_file FROM products WHERE id = ?", (product_id,), "")
    if source is None:
        with db.transaction():
            db.execute("UPDATE products SET image_file = '' WHERE id = ?", (product_id,))
        _remove_image(old)
        return ""
    src = Path(source)
    if not src.is_file():
        raise ValidationError("Image file not found.")
    if src.stat().st_size > MAX_IMAGE_BYTES:
        raise ValidationError("Image is too large (15 MB max).")
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(src) as im:
            im.load()
            im = im.convert("RGB")
            im.thumbnail((800, 800))
            name = f"p{product_id}_{uuid.uuid4().hex[:10]}.jpg"
            im.save(paths.images_dir() / name, "JPEG", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("That file is not a picture the app can read (use JPG or PNG).") from None
    with db.transaction():
        db.execute("UPDATE products SET image_file = ? WHERE id = ?", (name, product_id))
    _remove_image(old)
    return name


def image_path(image_file: str) -> Path | None:
    if not image_file or "/" in image_file or "\\" in image_file or image_file.startswith("."):
        return None
    p = paths.images_dir() / image_file
    return p if p.is_file() else None


def _remove_image(name: str) -> None:
    p = image_path(name)
    if p:
        try:
            p.unlink()
        except OSError:
            pass
