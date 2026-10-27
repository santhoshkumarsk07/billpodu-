"""Simple customers. Walk-in Customer always exists and needs no name or phone."""
from __future__ import annotations

import re
import sqlite3

from ..db import Database, now_str
from ..errors import NotFoundError, ValidationError

PHONE_RE = re.compile(r"^\+?[0-9 -]{6,16}$")


MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")


def normalize_mobile(text: str) -> str:
    """'+91 98400-12345' -> '9840012345'. Raises ValidationError if it is not a 10-digit Indian mobile."""
    digits = re.sub(r"[\s\-()]", "", text or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not MOBILE_RE.match(digits):
        raise ValidationError("Mobile number should be 10 digits, starting with 6, 7, 8 or 9.")
    return digits


def find_by_mobile(db: Database, mobile: str) -> dict | None:
    try:
        mobile = normalize_mobile(mobile)
    except ValidationError:
        return None
    row = db.one("SELECT c.*, (SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id AND s.status='COMPLETED')"
                 " AS bills FROM customers c WHERE c.phone = ?", (mobile,))
    return dict(row) if row else None


def find_or_create(db: Database, name: str, mobile: str) -> int:
    """Customer typed on the billing screen. Mobile number is the key; name alone also works.

    Must run inside the sale's transaction so a failed bill never leaves a half-made customer.
    """
    name = (name or "").strip()
    if len(name) > 80:
        raise ValidationError("Customer name is too long (80 characters max).")
    mobile = (mobile or "").strip()
    if mobile:
        mobile = normalize_mobile(mobile)
        row = db.one("SELECT id, active FROM customers WHERE phone = ?", (mobile,))
        if row:
            if not row["active"]:
                db.execute("UPDATE customers SET active = 1 WHERE id = ?", (row["id"],))
            return int(row["id"])
        return db.execute("INSERT INTO customers(name, phone, created_at) VALUES (?,?,?)",
                          (name or f"Customer {mobile[-4:]}", mobile, now_str())).lastrowid
    if not name:
        return walkin_id(db)
    row = db.one("SELECT id FROM customers WHERE name = ? COLLATE NOCASE AND phone = '' AND active = 1 "
                 "AND is_walkin = 0 ORDER BY id LIMIT 1", (name,))
    if row:
        return int(row["id"])
    return db.execute("INSERT INTO customers(name, phone, created_at) VALUES (?,?,?)",
                      (name, "", now_str())).lastrowid


def walkin_id(db: Database) -> int:
    return int(db.scalar("SELECT id FROM customers WHERE is_walkin = 1 ORDER BY id LIMIT 1"))


def _validate(name: str, phone: str) -> tuple[str, str]:
    name = (name or "").strip()
    phone = (phone or "").strip()
    if not name:
        raise ValidationError("Customer name is required.")
    if len(name) > 80:
        raise ValidationError("Customer name is too long.")
    if phone and not PHONE_RE.match(phone):
        raise ValidationError("Phone number should contain only digits (6 to 16).")
    phone = phone.replace(" ", "").replace("-", "")
    try:
        phone = normalize_mobile(phone) if phone else ""
    except ValidationError:
        pass  # landline or other number: keep as typed
    return name, phone


def add_customer(db: Database, name: str, phone: str = "", notes: str = "") -> int:
    name, phone = _validate(name, phone)
    try:
        with db.transaction():
            return db.execute(
                "INSERT INTO customers(name, phone, notes, created_at) VALUES (?,?,?,?)",
                (name, phone, (notes or "").strip()[:300], now_str())).lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError(f"Another customer already has phone number {phone}.") from None


def update_customer(db: Database, customer_id: int, name: str, phone: str = "", notes: str = "") -> None:
    if customer_id == walkin_id(db):
        raise ValidationError("The Walk-in Customer cannot be changed.")
    name, phone = _validate(name, phone)
    try:
        with db.transaction():
            db.execute("UPDATE customers SET name=?, phone=?, notes=? WHERE id=?",
                       (name, phone, (notes or "").strip()[:300], customer_id))
    except sqlite3.IntegrityError:
        raise ValidationError(f"Another customer already has phone number {phone}.") from None


def set_active(db: Database, customer_id: int, active: bool) -> None:
    if customer_id == walkin_id(db):
        raise ValidationError("The Walk-in Customer cannot be archived.")
    with db.transaction():
        db.execute("UPDATE customers SET active=? WHERE id=?", (1 if active else 0, customer_id))


def get_customer(db: Database, customer_id: int) -> dict:
    row = db.one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if row is None:
        raise NotFoundError("Customer not found.")
    return dict(row)


def search(db: Database, text: str = "", include_archived: bool = False, limit: int = 500) -> list[dict]:
    sql = ("SELECT c.*, (SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id AND s.status='COMPLETED') AS bills,"
           " (SELECT COALESCE(SUM(total_paise),0) FROM sales s WHERE s.customer_id = c.id AND s.status='COMPLETED')"
           " AS spent FROM customers c WHERE 1=1 ")
    params: list = []
    if not include_archived:
        sql += "AND c.active = 1 "
    if text.strip():
        like = f"%{text.strip()}%"
        sql += "AND (c.name LIKE ? OR c.phone LIKE ?) "
        params += [like, like]
    sql += "ORDER BY c.is_walkin DESC, c.name COLLATE NOCASE LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.all(sql, tuple(params))]


def purchase_history(db: Database, customer_id: int, limit: int = 500) -> list[dict]:
    return [dict(r) for r in db.all(
        "SELECT s.id, s.invoice_no, s.created_at, s.total_paise, s.status,"
        " (SELECT COALESCE(SUM(qty),0) FROM sale_items i WHERE i.sale_id = s.id) AS items "
        "FROM sales s WHERE s.customer_id = ? ORDER BY s.id DESC LIMIT ?", (customer_id, limit))]
