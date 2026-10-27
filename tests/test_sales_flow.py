import pytest

from mw83.errors import NotFoundError, StockError, ValidationError
from mw83.services import catalog, inventory, returns, sales
from mw83.services.cart import PERCENT, BillDiscount
from mw83.services.catalog import ProductInput, VariantInput
from mw83.services.returns import ReturnLine
from mw83.services.sales import PaymentInput, SaleRequest


def stock_of(db, code):
    return catalog.variant_by_code(db, code)["stock"]


def movement_sum(db, variant_id):
    return db.scalar("SELECT COALESCE(SUM(qty_change),0) FROM stock_movements WHERE variant_id = ?", (variant_id,))


def sell(db, settings, lines, **kw):
    pay = kw.pop("payment", None)
    if pay is None:
        total = sales.compute_for(settings, lines, kw.get("bill_discount", BillDiscount())).total
        pay = PaymentInput(cash_received=total)
    return sales.complete_sale(db, settings, SaleRequest(lines=lines, payment=pay, **kw))


# ---------------------------------------------------------------- catalogue
def test_product_and_variants_created_with_opening_stock(db, make_product):
    p = make_product()
    assert len(p["variants"]) == 2
    assert stock_of(db, "1000001") == 10
    v = catalog.variant_by_code(db, "CCS-L-BLK")
    assert v["size"] == "L" and v["stock"] == 5
    assert movement_sum(db, v["variant_id"]) == 5


def test_auto_sku_and_valid_ean13_barcode(db):
    from mw83.printing.barcodes import is_valid_ean13

    pid = catalog.save_product(db, ProductInput("Belt", None, 49900, variants=[VariantInput()]))
    v = catalog.get_product(db, pid)["variants"][0]
    assert v["sku"].startswith("MW") and is_valid_ean13(v["barcode"])


def test_duplicate_barcode_and_sku_rejected(db, make_product):
    make_product()
    with pytest.raises(ValidationError, match="Duplicate barcode"):
        catalog.save_product(db, ProductInput("Other", None, 1000, variants=[VariantInput(barcode="1000001")]))
    with pytest.raises(ValidationError, match="Duplicate SKU"):
        catalog.save_product(db, ProductInput("Other", None, 1000, variants=[VariantInput(sku="ccs-m-blk")]))
    with pytest.raises(ValidationError, match="twice"):
        catalog.save_product(db, ProductInput("Other", None, 1000, variants=[
            VariantInput(size="M", barcode="X1"), VariantInput(size="L", barcode="X1")]))
    # nothing partial was saved
    assert db.scalar("SELECT COUNT(*) FROM products WHERE name = 'Other'") == 0


def test_invalid_product_values(db):
    for p in (ProductInput("", None, 1000, variants=[VariantInput()]),
              ProductInput("X", None, 0, variants=[VariantInput()]),
              ProductInput("X", None, 2000, mrp=1000, variants=[VariantInput()]),
              ProductInput("X", None, 1000, variants=[VariantInput(barcode="has space")]),
              ProductInput("X", None, 1000, variants=[])):
        with pytest.raises(ValidationError):
            catalog.save_product(db, p)


def test_archive_product_blocks_sale(db, settings, make_product, cart_line):
    p = make_product()
    catalog.set_product_active(db, p["id"], False)
    v = catalog.variant_by_code(db, "1000001")
    with pytest.raises(ValidationError, match="archived"):
        sales.check_sellable(v)
    ln = sales.line_from_variant(v)
    with pytest.raises(ValidationError):
        sell(db, settings, [ln])


def test_unknown_barcode_message(db):
    with pytest.raises(NotFoundError, match="Unknown barcode"):
        sales.check_sellable(catalog.variant_by_code(db, "nope"), "nope")


def test_category_delete_blocked_when_used(db, make_product):
    make_product()
    cid = catalog.category_id_by_name(db, "Shirts")
    with pytest.raises(ValidationError):
        catalog.delete_category(db, cid)
    new = catalog.add_category(db, "Caps")
    with pytest.raises(ValidationError):
        catalog.add_category(db, "caps")
    catalog.delete_category(db, new)


# -------------------------------------------------------------------- sales
def test_sale_reduces_variant_stock_and_logs_movement(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001", 3)])
    assert stock_of(db, "1000001") == 7
    assert stock_of(db, "1000002") == 5  # other size untouched
    sale = sales.get_sale(db, sid)
    assert sale["items"][0]["size"] == "M" and sale["items"][0]["qty"] == 3
    vid = sale["items"][0]["variant_id"]
    assert movement_sum(db, vid) == 7
    last = db.one("SELECT * FROM stock_movements WHERE variant_id = ? ORDER BY id DESC", (vid,))
    assert last["movement_type"] == "SALE" and last["balance_after"] == 7 and last["ref_text"] == sale["invoice_no"]


def test_insufficient_stock_blocks_sale_and_saves_nothing(db, settings, make_product, cart_line):
    make_product()
    with pytest.raises(StockError):
        sell(db, settings, [cart_line("1000001", 2), cart_line("1000002", 6)])
    assert db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert stock_of(db, "1000001") == 10


def test_invoice_numbers_sequential_and_never_reused(db, settings, make_product, cart_line):
    make_product()
    a = sales.get_sale(db, sell(db, settings, [cart_line("1000001")]))["invoice_no"]
    b_id = sell(db, settings, [cart_line("1000001")])
    b = sales.get_sale(db, b_id)["invoice_no"]
    assert (a, b) == ("83MW-0001", "83MW-0002")
    sales.cancel_sale(db, b_id, "Customer left")
    c = sales.get_sale(db, sell(db, settings, [cart_line("1000001")]))["invoice_no"]
    assert c == "83MW-0003"
    settings.set("invoice_prefix", "MW")
    assert sales.get_sale(db, sell(db, settings, [cart_line("1000001")]))["invoice_no"] == "MW-0001"


def test_failed_sale_rolls_back_everything(db, settings, make_product, cart_line, monkeypatch):
    make_product()
    lines = [cart_line("1000001"), cart_line("1000002")]
    real = inventory.record_movement
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk error")
        return real(*a, **k)

    monkeypatch.setattr(sales, "record_movement", flaky)
    with pytest.raises(RuntimeError):
        sell(db, settings, lines)
    assert db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert db.scalar("SELECT COUNT(*) FROM sale_items") == 0
    assert stock_of(db, "1000001") == 10
    monkeypatch.setattr(sales, "record_movement", real)
    sid = sell(db, settings, lines)
    assert sales.get_sale(db, sid)["invoice_no"] == "83MW-0001"  # rolled-back number was not burned


def test_same_bill_saved_twice_is_not_duplicated(db, settings, make_product, cart_line):
    make_product()
    lines = [cart_line("1000001")]
    req = SaleRequest(lines=lines, payment=PaymentInput(cash_received=99900))
    first = sales.complete_sale(db, settings, req)
    second = sales.complete_sale(db, settings, req)
    assert first == second
    assert db.scalar("SELECT COUNT(*) FROM sales") == 1
    assert stock_of(db, "1000001") == 9


def test_split_payment_recorded(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001")],
               payment=PaymentInput(upi=50000, upi_ref="UPI123", cash_received=50000))
    s = sales.get_sale(db, sid)
    pays = {p["method"]: p["amount_paise"] for p in s["payments"]}
    assert pays == {"UPI": 50000, "CASH": 49900}
    assert s["change_paise"] == 100
    assert sum(pays.values()) == s["total_paise"]


def test_underpayment_rejected(db, settings, make_product, cart_line):
    make_product()
    with pytest.raises(ValidationError):
        sell(db, settings, [cart_line("1000001")], payment=PaymentInput(cash_received=100))
    assert db.scalar("SELECT COUNT(*) FROM sales") == 0


def test_gst_stored_with_bill(db, settings, make_product, cart_line):
    settings.set_many({"gst_enabled": "1", "shop_state": "Tamil Nadu", "prices_include_tax": "1",
                       "default_gst_rate_bp": "500"})
    make_product(price=105000, mrp=105000)
    sid = sell(db, settings, [cart_line("1000001")])
    s = sales.get_sale(db, sid)
    assert s["gst_enabled"] == 1 and s["cgst_paise"] == 2500 and s["sgst_paise"] == 2500
    assert s["items"][0]["gst_rate_bp"] == 500 and s["items"][0]["taxable_paise"] == 100000
    settings.set("default_gst_rate_bp", "1800")
    assert sales.get_sale(db, sid)["cgst_paise"] == 2500  # old bill unchanged


def test_discounts_saved(db, settings, make_product, cart_line):
    make_product()
    ln = cart_line("1000001", 2, disc_type=PERCENT, disc_value=1000)
    sid = sell(db, settings, [ln], bill_discount=BillDiscount("AMOUNT", 1000, "Regular"))
    s = sales.get_sale(db, sid)
    assert s["item_discount_paise"] == 19980 and s["bill_discount_paise"] == 1000
    assert s["total_paise"] == 199800 - 19980 - 1000 and s["discount_reason"] == "Regular"


def test_cancel_restores_stock_once(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001", 4)])
    sales.cancel_sale(db, sid, "Wrong bill")
    assert stock_of(db, "1000001") == 10
    with pytest.raises(ValidationError):
        sales.cancel_sale(db, sid, "again")
    assert stock_of(db, "1000001") == 10
    assert sales.get_sale(db, sid)["status"] == "CANCELLED"
    assert db.scalar("SELECT COUNT(*) FROM sales") == 1  # never deleted


def test_hold_and_resume(db, make_product, cart_line):
    make_product()
    state = {"lines": [cart_line("1000001", 2).to_dict()], "note": "x"}
    hid = sales.hold_bill(db, "Ravi", state)
    assert sales.list_held(db)[0]["items"] == 2
    data = sales.resume_held(db, hid)
    assert data["lines"][0]["qty"] == 2
    assert sales.list_held(db) == []
    with pytest.raises(NotFoundError):
        sales.resume_held(db, hid)


# ------------------------------------------------------------------ returns
def test_return_restores_stock_and_limits_quantity(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001", 3)])
    item = sales.get_sale(db, sid)["items"][0]
    rid = returns.create_return(db, settings, sid, [ReturnLine(item["id"], 2)], "Size issue", "CASH")
    assert stock_of(db, "1000001") == 9
    assert returns.get_return(db, rid)["refund_paise"] == 2 * 99900
    with pytest.raises(ValidationError, match="only 1 left"):
        returns.create_return(db, settings, sid, [ReturnLine(item["id"], 2)], "Size issue", "CASH")
    returns.create_return(db, settings, sid, [ReturnLine(item["id"], 1, restock=False)], "Defective", "UPI")
    assert stock_of(db, "1000001") == 9  # damaged item not put back
    total_refund = db.scalar("SELECT SUM(refund_paise) FROM returns WHERE sale_id = ?", (sid,))
    assert total_refund == sales.get_sale(db, sid)["total_paise"]
    assert sales.get_sale(db, sid)["total_paise"] == 3 * 99900  # original bill unchanged
    with pytest.raises(ValidationError):
        sales.cancel_sale(db, sid, "late")


def test_return_refunds_add_up_with_odd_discount(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001", 3, disc_type="AMOUNT", disc_value=100)])
    item = sales.get_sale(db, sid)["items"][0]
    for _ in range(3):
        returns.create_return(db, settings, sid, [ReturnLine(item["id"], 1)], "Size issue", "CASH")
    assert db.scalar("SELECT SUM(refund_paise) FROM returns") == item["line_total_paise"]


def test_exchange_credit_used_once(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001")])
    item = sales.get_sale(db, sid)["items"][0]
    rid = returns.create_return(db, settings, sid, [ReturnLine(item["id"], 1)], "Size issue", "EXCHANGE")
    assert returns.open_exchange_credits(db)[0]["id"] == rid
    new_lines = [cart_line("1000002", 2)]
    new_id = sell(db, settings, new_lines, payment=PaymentInput(exchange_return_id=rid, cash_received=99900))
    s = sales.get_sale(db, new_id)
    assert {p["method"] for p in s["payments"]} == {"EXCHANGE", "CASH"}
    assert returns.get_return(db, rid)["exchange_invoice"] == s["invoice_no"]
    assert returns.open_exchange_credits(db) == []
    with pytest.raises(ValidationError, match="already been used"):
        sell(db, settings, [cart_line("1000002")], payment=PaymentInput(exchange_return_id=rid, cash_received=0))


def test_return_against_cancelled_bill_blocked(db, settings, make_product, cart_line):
    make_product()
    sid = sell(db, settings, [cart_line("1000001")])
    item = sales.get_sale(db, sid)["items"][0]
    sales.cancel_sale(db, sid, "oops")
    with pytest.raises(ValidationError):
        returns.create_return(db, settings, sid, [ReturnLine(item["id"], 1)], "Size issue", "CASH")


# ---------------------------------------------------------------- inventory
def test_manual_adjustments_need_reason_and_cannot_go_negative(db, make_product):
    make_product()
    vid = catalog.variant_by_code(db, "1000001")["variant_id"]
    with pytest.raises(ValidationError):
        inventory.adjust_stock(db, vid, "DAMAGED", 1, "")
    assert inventory.adjust_stock(db, vid, "DAMAGED", 2, "Torn") == 8
    assert inventory.adjust_stock(db, vid, "ADJUSTMENT", 3, "Recount") == 11
    with pytest.raises(StockError):
        inventory.adjust_stock(db, vid, "LOST", 50, "Theft")
    assert inventory.receive_stock(db, vid, 4, "Supplier bill 12") == 15
    assert movement_sum(db, vid) == 15 == stock_of(db, "1000001")


def test_stock_lists_and_value(db, make_product):
    make_product()
    vid = catalog.variant_by_code(db, "1000002")["variant_id"]
    inventory.adjust_stock(db, vid, "ADJUSTMENT", -4, "Recount")
    low = inventory.stock_list(db, status="LOW", default_min=2)
    assert [r["variant_id"] for r in low] == [vid]
    inventory.adjust_stock(db, vid, "ADJUSTMENT", -1, "Recount")
    assert [r["variant_id"] for r in inventory.stock_list(db, status="OUT")] == [vid]
    val = inventory.stock_value(db)
    assert val["units"] == 10 and val["cost_value"] == 10 * 50000
