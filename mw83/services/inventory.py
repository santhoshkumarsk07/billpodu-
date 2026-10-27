"""Stock is only ever changed through record_movement, so the history always matches the stock."""
from __future__ import annotations

from ..db import Database, now_str
from ..errors import StockError, ValidationError

MOVEMENT_LABELS = {
    "OPENING": "Opening stock",
    "RECEIVED": "Stock received",
    "SALE": "Sold",
    "SALE_CANCEL": "Bill cancelled",
    "RETURN": "Customer return",
    "DAMAGED": "Damaged",
    "LOST": "Lost",
    "ADJUSTMENT": "Manual adjustment",
}
MANUAL_TYPES = ("DAMAGED", "LOST", "ADJUSTMENT")


def record_movement(db: Database, variant_id: int, movement_type: str, qty_change: int, *,
                    ref_type: str = "", ref_id: int | None = None, ref_text: str = "",
                    reason: str = "", description: str = "") -> int:
    """Change stock and log it. Must run inside a transaction. Returns the new balance."""
    if not db.in_transaction:
        raise RuntimeError("stock changes must run inside a transaction")
    if movement_type not in MOVEMENT_LABELS:
        raise ValueError(f"bad movement type {movement_type}")
    if qty_change == 0:
        raise ValidationError("Quantity change cannot be zero.")
    cur = db.execute(
        "UPDATE variants SET stock = stock + ? WHERE id = ? AND stock + ? >= 0",
        (qty_change, variant_id, qty_change),
    )
    if cur.rowcount != 1:
        row = db.one("SELECT stock FROM variants WHERE id = ?", (variant_id,))
        if row is None:
            raise ValidationError("That product variant no longer exists.")
        name = description or "this item"
        raise StockError(f"Only {row['stock']} in stock for {name}; cannot take out {-qty_change}.")
    balance = int(db.scalar("SELECT stock FROM variants WHERE id = ?", (variant_id,)))
    db.execute(
        "INSERT INTO stock_movements(variant_id, movement_type, qty_change, balance_after, "
        "ref_type, ref_id, ref_text, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (variant_id, movement_type, qty_change, balance, ref_type, ref_id, ref_text, reason.strip(), now_str()),
    )
    return balance


def _check_qty(qty: int) -> None:
    if not isinstance(qty, int) or qty <= 0:
        raise ValidationError("Quantity must be a whole number of 1 or more.")
    if qty > 100000:
        raise ValidationError("Quantity is too large.")


def receive_stock(db: Database, variant_id: int, qty: int, note: str = "") -> int:
    _check_qty(qty)
    with db.transaction():
        return record_movement(db, variant_id, "RECEIVED", qty, ref_text=note.strip()[:100],
                               reason=note.strip()[:200])


def adjust_stock(db: Database, variant_id: int, movement_type: str, qty_change: int, reason: str) -> int:
    """DAMAGED / LOST take stock out; ADJUSTMENT may go up or down. A reason is required."""
    if movement_type not in MANUAL_TYPES:
        raise ValidationError("Choose Damaged, Lost or Adjustment.")
    if not reason or not reason.strip():
        raise ValidationError("Please enter a reason for this stock change.")
    if not isinstance(qty_change, int) or qty_change == 0:
        raise ValidationError("Quantity change cannot be zero.")
    if movement_type in ("DAMAGED", "LOST") and qty_change > 0:
        qty_change = -qty_change
    if abs(qty_change) > 100000:
        raise ValidationError("Quantity is too large.")
    with db.transaction():
        return record_movement(db, variant_id, movement_type, qty_change, reason=reason.strip()[:200])


def stock_list(db: Database, text: str = "", category_id: int | None = None, status: str = "ALL",
               default_min: int = 2, include_archived: bool = False, limit: int = 2000) -> list[dict]:
    """status: ALL / LOW / OUT."""
    sql = [
        "SELECT v.id AS variant_id, p.id AS product_id, p.name, p.brand, c.name AS category, v.size, v.colour,",
        " v.sku, v.barcode, v.stock, COALESCE(p.min_stock, ?) AS min_stock,",
        " COALESCE(v.cost_paise, p.cost_paise) AS cost, COALESCE(v.price_paise, p.price_paise) AS price,",
        " COALESCE(v.mrp_paise, p.mrp_paise) AS mrp, v.active AND p.active AS active",
        "FROM variants v JOIN products p ON p.id = v.product_id LEFT JOIN categories c ON c.id = p.category_id",
        "WHERE 1=1",
    ]
    params: list = [default_min]
    if not include_archived:
        sql.append("AND v.active = 1 AND p.active = 1")
    if text.strip():
        like = f"%{text.strip()}%"
        sql.append("AND (p.name LIKE ? OR v.sku LIKE ? OR v.barcode LIKE ? OR p.brand LIKE ?)")
        params += [like, like, like, like]
    if category_id:
        sql.append("AND p.category_id = ?")
        params.append(category_id)
    if status == "LOW":
        sql.append("AND v.stock > 0 AND v.stock <= COALESCE(p.min_stock, ?)")
        params.append(default_min)
    elif status == "OUT":
        sql.append("AND v.stock = 0")
    sql.append("ORDER BY p.name COLLATE NOCASE, v.size, v.colour LIMIT ?")
    params.append(limit)
    return [dict(r) for r in db.all(" ".join(sql), tuple(params))]


def low_stock_count(db: Database, default_min: int) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM variants v JOIN products p ON p.id = v.product_id "
        "WHERE v.active = 1 AND p.active = 1 AND v.stock <= COALESCE(p.min_stock, ?)",
        (default_min,), 0))


def stock_value(db: Database) -> dict:
    row = db.one(
        "SELECT COALESCE(SUM(v.stock),0) AS units,"
        " COALESCE(SUM(v.stock * COALESCE(v.cost_paise, p.cost_paise)),0) AS cost_value,"
        " COALESCE(SUM(v.stock * COALESCE(v.price_paise, p.price_paise)),0) AS sale_value "
        "FROM variants v JOIN products p ON p.id = v.product_id WHERE v.active = 1 AND p.active = 1")
    return dict(row)


def movements(db: Database, variant_id: int | None = None, date_from: str = "", date_to: str = "",
              movement_type: str = "", text: str = "", limit: int = 2000) -> list[dict]:
    sql = [
        "SELECT m.id, m.created_at, m.movement_type, m.qty_change, m.balance_after, m.ref_text, m.reason,",
        " p.name, v.size, v.colour, v.sku, v.id AS variant_id",
        "FROM stock_movements m JOIN variants v ON v.id = m.variant_id JOIN products p ON p.id = v.product_id",
        "WHERE 1=1",
    ]
    params: list = []
    if variant_id:
        sql.append("AND m.variant_id = ?")
        params.append(variant_id)
    if date_from:
        sql.append("AND m.created_at >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        sql.append("AND m.created_at <= ?")
        params.append(date_to + " 23:59:59")
    if movement_type:
        sql.append("AND m.movement_type = ?")
        params.append(movement_type)
    if text.strip():
        like = f"%{text.strip()}%"
        sql.append("AND (p.name LIKE ? OR v.sku LIKE ? OR v.barcode LIKE ? OR m.ref_text LIKE ?)")
        params += [like, like, like, like]
    sql.append("ORDER BY m.id DESC LIMIT ?")
    params.append(limit)
    return [dict(r) for r in db.all(" ".join(sql), tuple(params))]
