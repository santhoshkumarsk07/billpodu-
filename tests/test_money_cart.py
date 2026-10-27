import pytest

from mw83.errors import ValidationError
from mw83.money import allocate, fmt, parse_percent, parse_rupees, round_div
from mw83.services.cart import AMOUNT, PERCENT, BillDiscount, CartLine, TaxConfig, compute, settle, split_tax


def line(price, qty=1, **kw):
    return CartLine(variant_id=1, product_name="Shirt", size="M", colour="Black", sku="S", barcode="B",
                    unit_price=price, qty=qty, **kw)


def test_parse_rupees():
    assert parse_rupees("1,299.50") == 129950
    assert parse_rupees("499") == 49900
    assert parse_rupees("0.1") == 10
    for bad in ("", "-1", "abc", "1.234", "nan", "inf"):
        with pytest.raises(ValidationError):
            parse_rupees(bad)
    with pytest.raises(ValidationError):
        parse_rupees("0", allow_zero=False)


def test_parse_percent_and_format():
    assert parse_percent("12.5") == 1250
    with pytest.raises(ValidationError):
        parse_percent("101")
    assert fmt(123456) == "1,234.56"
    assert fmt(-5) == "-0.05"


def test_round_and_allocate_exact():
    assert round_div(5, 2) == 3
    assert round_div(4, 3) == 1
    parts = allocate(1000, [333, 333, 334])
    assert sum(parts) == 1000
    assert allocate(1, [1, 1, 1]) == [1, 0, 0]


def test_cart_totals_no_gst():
    t = compute([line(99900, 2), line(49900)], BillDiscount(), TaxConfig(enabled=False))
    assert t.gross == 249700
    assert t.total == 249700
    assert t.tax == 0
    assert t.item_count == 3


def test_item_discounts_percent_and_amount():
    t = compute([line(100000, 2, disc_type=PERCENT, disc_value=1000),  # 10 % of 2000.00
                 line(50000, 1, disc_type=AMOUNT, disc_value=5000)], BillDiscount(), TaxConfig())
    assert t.item_discount == 20000 + 5000
    assert t.total == 200000 - 20000 + 50000 - 5000


def test_bill_discount_split_exactly_across_lines():
    lines = [line(33333), line(33333), line(33334)]
    t = compute(lines, BillDiscount(PERCENT, 1000), TaxConfig())
    assert t.bill_discount == 10000
    assert sum(r.bill_discount for r in t.lines) == 10000
    assert t.total == 90000
    t2 = compute(lines, BillDiscount(AMOUNT, 101), TaxConfig())
    assert sum(r.bill_discount for r in t2.lines) == 101


def test_discount_cannot_exceed_amount():
    with pytest.raises(ValidationError):
        compute([line(10000, disc_type=AMOUNT, disc_value=10001)], BillDiscount(), TaxConfig())
    with pytest.raises(ValidationError):
        compute([line(10000)], BillDiscount(AMOUNT, 10001), TaxConfig())
    with pytest.raises(ValidationError):
        compute([line(10000, disc_type=PERCENT, disc_value=10001)], BillDiscount(), TaxConfig())


def test_discount_limit_setting():
    with pytest.raises(ValidationError):
        compute([line(10000)], BillDiscount(PERCENT, 2000), TaxConfig(), max_discount_bp=1500)
    t = compute([line(10000)], BillDiscount(PERCENT, 1500), TaxConfig(), max_discount_bp=1500)
    assert t.total == 8500


def test_invalid_quantity():
    for q in (0, -1):
        with pytest.raises(ValidationError):
            compute([line(10000, q)], BillDiscount(), TaxConfig())


def test_gst_inclusive_cgst_sgst():
    cfg = TaxConfig(enabled=True, inclusive=True, default_rate_bp=500)
    t = compute([line(105000)], BillDiscount(), cfg)
    assert t.taxable == 100000
    assert t.cgst == 2500 and t.sgst == 2500 and t.igst == 0
    assert t.total == 105000


def test_gst_exclusive_and_igst():
    cfg = TaxConfig(enabled=True, inclusive=False, inter_state=True, default_rate_bp=1200)
    t = compute([line(100000)], BillDiscount(), cfg)
    assert t.taxable == 100000 and t.igst == 12000 and t.cgst == 0
    assert t.total == 112000


def test_gst_after_discount_and_odd_paise():
    cfg = TaxConfig(enabled=True, inclusive=False, default_rate_bp=500)
    t = compute([line(99999, disc_type=PERCENT, disc_value=1000)], BillDiscount(), cfg)
    r = t.lines[0]
    assert r.net == 99999 - 10000
    assert r.cgst + r.sgst == round_div(r.net * 500, 10000)
    assert t.total == r.net + r.cgst + r.sgst


def test_gst_slab_by_unit_value():
    cfg = TaxConfig(enabled=True, inclusive=False, slab_threshold=250000, slab_low_bp=500, slab_high_bp=1800)
    low = compute([line(249900, 3, gst_mode="SLAB")], BillDiscount(), cfg)
    high = compute([line(300000, 1, gst_mode="SLAB")], BillDiscount(), cfg)
    assert low.lines[0].gst_rate_bp == 500
    assert high.lines[0].gst_rate_bp == 1800


def test_gst_fixed_and_exempt_and_disabled():
    cfg = TaxConfig(enabled=True, inclusive=True, default_rate_bp=500)
    t = compute([line(10000, gst_mode="FIXED", gst_rate_bp=1800), line(10000, gst_mode="EXEMPT")],
                BillDiscount(), cfg)
    assert t.lines[0].gst_rate_bp == 1800 and t.lines[1].gst_rate_bp == 0
    off = compute([line(10000, gst_mode="FIXED", gst_rate_bp=1800)], BillDiscount(), TaxConfig(enabled=False))
    assert off.tax == 0


def test_split_tax_sums():
    for net in range(0, 5000, 7):
        taxable, c, s, i, total = split_tax(net, 500, True, False)
        assert taxable + c + s == total == net


def test_round_off():
    t = compute([line(10049)], BillDiscount(), TaxConfig(), round_off=True)
    assert t.total == 10000 and t.round_off == -49
    t = compute([line(10050)], BillDiscount(), TaxConfig(), round_off=True)
    assert t.total == 10100


def test_settle_cash_change():
    s = settle(84900, cash_received=100000)
    assert s.payments == [("CASH", 84900, "")]
    assert s.change == 15100


def test_settle_split_cash_upi():
    s = settle(100000, upi=60000, cash_received=50000, upi_ref="TXN1")
    assert ("UPI", 60000, "TXN1") in s.payments and ("CASH", 40000, "") in s.payments
    assert s.change == 10000
    assert sum(a for _, a, _ in s.payments) == 100000


def test_settle_errors():
    with pytest.raises(ValidationError):
        settle(10000, cash_received=9999)
    with pytest.raises(ValidationError):
        settle(10000, upi=8000, card=3000)
    with pytest.raises(ValidationError):
        settle(10000, exchange=10001)
    s = settle(10000, card=10000)
    assert s.payments == [("CARD", 10000, "")] and s.change == 0
