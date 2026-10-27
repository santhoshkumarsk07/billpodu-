import json
import sqlite3
import zipfile
from datetime import date

import pytest

from mw83.errors import PrinterError, ValidationError
from mw83.printing import barcodes
from mw83.printing.receipt import WIDTH_CHARS, as_text, build_receipt
from mw83.services import backup, catalog, csv_io, reports, sales
from mw83.services.returns import ReturnLine, create_return
from mw83.services.sales import PaymentInput, SaleRequest

TODAY = date.today().isoformat()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def shop(settings):
    return {k: settings.get(k) for k in ("shop_name", "shop_address", "shop_phone", "shop_gstin",
                                         "receipt_footer", "return_policy")}


def quick_sale(db, settings, cart_line, code="1000001", qty=1, **pay):
    lines = [cart_line(code, qty)]
    total = sales.compute_for(settings, lines, sales.BillDiscount()).total
    payment = PaymentInput(**pay) if pay else PaymentInput(cash_received=total)
    return sales.complete_sale(db, settings, SaleRequest(lines=lines, payment=payment))


# ----------------------------------------------------------------- barcodes
def test_ean13_validation_and_code128():
    assert barcodes.is_valid_ean13("5901234123457")
    assert not barcodes.is_valid_ean13("5901234123458")
    assert barcodes.effective_kind("5901234123458", "EAN13") == "CODE128"
    assert set(barcodes.modules("83MW-0001")) == {"0", "1"}
    assert len(barcodes.modules("5901234123457", "EAN13")) == 95
    with pytest.raises(ValidationError):
        barcodes.modules("5901234123458", "EAN13")
    with pytest.raises(ValidationError):
        barcodes.modules("")


# ------------------------------------------------------------------ receipt
@pytest.mark.parametrize("paper", ["58", "80"])
def test_receipt_fits_paper_width(db, settings, make_product, cart_line, paper):
    settings.set_many({"gst_enabled": "1", "shop_state": "Tamil Nadu", "shop_gstin": "33ABCDE1234F1Z5",
                       "shop_address": "12 Main Road, Chennai"})
    make_product(name="Very Long Premium Linen Blend Formal Shirt With Pocket")
    sid = quick_sale(db, settings, cart_line, upi=20000, upi_ref="UPI99", cash_received=100000)
    sale = sales.get_sale(db, sid)
    lines = build_receipt(sale, shop(settings), WIDTH_CHARS[paper])
    text = as_text(lines)
    assert all(len(ln.text) <= WIDTH_CHARS[paper] for ln in lines)
    for needle in ("83 MEN'S WEAR", sale["invoice_no"], "GSTIN: 33ABCDE1234F1Z5", "CGST", "SGST", "TOTAL",
                   "UPI (UPI99)", "Change", "Black"):
        assert needle in text
    dup = as_text(build_receipt(sale, shop(settings), 48, duplicate=True))
    assert "DUPLICATE" in dup


def test_receipt_pdf(db, settings, make_product, cart_line, tmp_path):
    from mw83.printing.pdf import receipt_pdf

    make_product()
    sale = sales.get_sale(db, quick_sale(db, settings, cart_line))
    out = receipt_pdf(build_receipt(sale, shop(settings), 32), tmp_path / "r.pdf", 58, 32)
    assert out.read_bytes()[:5] == b"%PDF-"


def test_printer_failure_keeps_single_sale_and_reprint_works(db, settings, make_product, cart_line, monkeypatch,
                                                             qapp):
    """Simulate the POS flow: save, print fails, reprint later. Only one sale must exist."""
    from mw83.printing import printers

    make_product()
    lines = [cart_line("1000001")]
    req = SaleRequest(lines=lines, payment=PaymentInput(cash_received=99900))
    sid = sales.complete_sale(db, settings, req)

    def broken(*a, **k):
        raise PrinterError("offline")

    monkeypatch.setattr(printers, "print_receipt_driver", broken)
    with pytest.raises(PrinterError):
        printers.print_receipt(settings, build_receipt(sales.get_sale(db, sid), shop(settings), 48))
    # Owner presses "Complete" again on the same screen: same client_ref -> same sale.
    assert sales.complete_sale(db, settings, req) == sid
    assert db.scalar("SELECT COUNT(*) FROM sales") == 1
    assert catalog.variant_by_code(db, "1000001")["stock"] == 9

    printed = []
    monkeypatch.setattr(printers, "print_receipt_driver", lambda *a, **k: printed.append(a))
    printers.print_receipt(settings, build_receipt(sales.get_sale(db, sid), shop(settings), 48, duplicate=True))
    assert printed and db.scalar("SELECT COUNT(*) FROM sales") == 1


def test_unknown_printer_gives_clear_error(qapp):
    from mw83.printing.printers import _make_printer

    with pytest.raises(PrinterError, match="not found"):
        _make_printer("No Such Printer 123", 80, 100)


def test_escpos_bytes():
    from mw83.printing.printers import escpos_bytes
    from mw83.printing.receipt import Line

    data = escpos_bytes([Line("Hello ₹", True, True)], cut=True)
    assert data.startswith(b"\x1b@") and b"Hello ?" in data and data.endswith(b"\x1dVB\x00")


def test_tag_preview_renders(qapp):
    from mw83.printing.tags import TagTemplate, render_preview

    item = {"product_name": "Classic Cotton Shirt", "size": "L", "colour": "Black", "sku": "CCS-L",
            "barcode": "200000000001", "mrp": 129900, "price": 99900}
    img = render_preview(item, TagTemplate(), dpi=203)
    assert img.width() == int(50 * 203 / 25.4)
    # some black pixels were drawn
    dark = sum(1 for x in range(0, img.width(), 3) for y in range(0, img.height(), 3)
               if img.pixelColor(x, y).lightness() < 100)
    assert dark > 50
    with pytest.raises(ValidationError):
        render_preview(item, TagTemplate(width_mm=15, height_mm=10, font_pt=9))


# ------------------------------------------------------------------- backup
def test_backup_and_restore_roundtrip(db, settings, make_product, cart_line, tmp_path):
    p = make_product()
    (tmp_path / "pic.png").write_bytes(b"")
    from PIL import Image

    Image.new("RGB", (40, 40), "red").save(tmp_path / "pic.png")
    catalog.set_product_image(db, p["id"], tmp_path / "pic.png")
    quick_sale(db, settings, cart_line)
    bk = backup.manual_backup(db, settings)
    with zipfile.ZipFile(bk) as zf:
        names = zf.namelist()
    assert "shop.db" in names and "manifest.json" in names and any(n.startswith("images/") for n in names)
    manifest = backup.validate_backup(bk)
    assert manifest["counts"]["sales"] == 1

    quick_sale(db, settings, cart_line)  # data after the backup
    assert db.scalar("SELECT COUNT(*) FROM sales") == 2
    safety = backup.restore_backup(db, settings, bk)
    assert safety.exists() and "before-restore" in safety.name
    assert db.scalar("SELECT COUNT(*) FROM sales") == 1
    assert catalog.variant_by_code(db, "1000001")["stock"] == 9
    img = catalog.get_product(db, p["id"])["image_file"]
    assert catalog.image_path(img) is not None
    # app still works after restore
    quick_sale(db, settings, cart_line)
    assert sales.get_sale(db, db.scalar("SELECT MAX(id) FROM sales"))["invoice_no"] == "83MW-0002"


def test_restore_rejects_bad_files(db, settings, tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_text("not a zip")
    with pytest.raises(backup.RestoreError):
        backup.validate_backup(bad)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("shop.db", b"x")
        zf.writestr("manifest.json", "{}")
        zf.writestr("../../escape.txt", "boom")
    with pytest.raises(backup.RestoreError, match="unexpected file"):
        backup.validate_backup(evil)
    assert not (tmp_path.parent / "escape.txt").exists()
    fake = tmp_path / "fake.zip"
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("shop.db", b"SQLite format 3\x00 garbage")
        zf.writestr("manifest.json", json.dumps({"app": "x"}))
    with pytest.raises(backup.RestoreError):
        backup.validate_backup(fake)
    other = tmp_path / "other.db"
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE t(x)")
    c.commit()
    c.close()
    wrong = tmp_path / "wrong.zip"
    with zipfile.ZipFile(wrong, "w") as zf:
        zf.write(other, "shop.db")
        zf.writestr("manifest.json", "{}")
    with pytest.raises(backup.RestoreError, match="missing required"):
        backup.validate_backup(wrong)
    # live data untouched
    assert db.scalar("SELECT COUNT(*) FROM customers") == 1


def test_backup_retention_and_auto_once_a_day(db, settings, tmp_path):
    settings.set("backups_to_keep", "3")
    for _ in range(5):
        backup.manual_backup(db, settings)
    assert len(backup.list_backups(backup.backup_dir(settings))) == 3
    assert backup.auto_backup_if_due(db, settings) is not None
    assert backup.auto_backup_if_due(db, settings) is None


def test_backup_to_unwritable_location_reports_clearly(db, settings, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(backup.BackupError):
        backup.create_backup(db, blocker / "sub")


# ---------------------------------------------------------------------- csv
def test_csv_export_import_roundtrip(db, make_product, tmp_path, data_dir):
    make_product()
    out = tmp_path / "p.csv"
    assert csv_io.export_products(db, out) == 2
    text = out.read_text(encoding="utf-8-sig")
    assert "CCS-M-BLK" in text
    # import into a fresh database
    from mw83.db import Database

    fresh = Database(tmp_path / "fresh.db")
    res = csv_io.import_products(fresh, out)
    assert res.ok and res.products == 1 and res.variants == 2
    assert catalog.variant_by_code(fresh, "1000001")["stock"] == 10
    fresh.close()


def test_csv_import_row_errors_save_nothing(db, make_product, tmp_path):
    make_product()
    f = tmp_path / "bad.csv"
    f.write_text("product_name,selling_price,barcode,size,opening_stock\n"
                 "Polo,499,NEW1,M,5\n"
                 ",499,NEW2,L,1\n"
                 "Polo,abc,NEW3,XL,1\n"
                 "Polo,499,1000001,S,1\n"
                 "Polo,499,NEW1,XXL,1\n", encoding="utf-8")
    res = csv_io.import_products(db, f)
    assert not res.ok
    rows = {r for r, _ in res.errors}
    assert {3, 4, 6} <= rows
    assert any("1000001" in m for _, m in res.errors)
    assert db.scalar("SELECT COUNT(*) FROM products WHERE name = 'Polo'") == 0


def test_csv_formula_injection_escaped(tmp_path):
    csv_io.write_csv(tmp_path / "x.csv", ["a"], [["=HYPERLINK(\"x\")"], ["-5"], ["@cmd"]])
    rows = (tmp_path / "x.csv").read_text(encoding="utf-8-sig").splitlines()
    assert rows[1].startswith("\"'=") and rows[2] == "-5" and rows[3] == "'@cmd"


# ------------------------------------------------------------------ reports
def test_reports_use_real_data(db, settings, make_product, cart_line):
    make_product()
    sid = quick_sale(db, settings, cart_line, qty=2)
    quick_sale(db, settings, cart_line, code="1000002", upi=99900)
    item = sales.get_sale(db, sid)["items"][0]
    create_return(db, settings, sid, [ReturnLine(item["id"], 1)], "Size issue", "CASH")
    conn = db.conn
    daily = reports.daily_sales(conn, TODAY, TODAY)
    assert daily.rows[0][1] == 2 and daily.rows[0][2] == 3
    assert daily.rows[0][6] == 3 * 99900 and daily.rows[0][7] == 99900
    pay = {r[0]: r for r in reports.payment_summary(conn, TODAY, TODAY).rows}
    assert pay["CASH"][2] == 2 * 99900 and pay["CASH"][3] == 99900 and pay["UPI"][2] == 99900
    cat = reports.sales_by_category(conn, TODAY, TODAY).rows
    assert cat[0][0] == "Shirts" and cat[0][1] == 3
    profit = reports.profit_estimate(conn, TODAY, TODAY).rows[0]
    assert profit[1] == 2 * 99900 and profit[2] == 2 * 50000
    dash = reports.dashboard(conn, TODAY, 2)
    assert dash["bills"] == 2 and dash["cash"] == 99900 and dash["upi"] == 99900
    assert reports.returns_report(conn, TODAY, TODAY).rows[0][6] == 1
    assert len(reports.stock_movement_report(conn, TODAY, TODAY).rows) == 2 + 2 + 1
    empty = reports.daily_sales(conn, "2000-01-01", "2000-01-02")
    assert empty.rows == [] and empty.totals is None


def test_report_pdf_and_csv(db, settings, make_product, cart_line, tmp_path):
    from mw83.printing.pdf import report_pdf

    make_product()
    quick_sale(db, settings, cart_line)
    rep = reports.stock_movement_report(db.conn, TODAY, TODAY)
    assert report_pdf(rep, tmp_path / "r.pdf", "83 MEN'S WEAR").read_bytes()[:5] == b"%PDF-"
    csv_io.write_csv(tmp_path / "r.csv", rep.headers, rep.formatted_rows())
    assert "Opening stock" in (tmp_path / "r.csv").read_text(encoding="utf-8-sig")


def test_image_validation(db, make_product, tmp_path):
    p = make_product()
    fake = tmp_path / "fake.jpg"
    fake.write_bytes(b"MZ\x90\x00 not an image")
    with pytest.raises(ValidationError):
        catalog.set_product_image(db, p["id"], fake)


def test_settings_validation(settings):
    with pytest.raises(ValidationError):
        settings.set("shop_gstin", "BAD")
    with pytest.raises(ValidationError):
        settings.set("invoice_prefix", "83 MW;DROP")
    with pytest.raises(ValidationError):
        settings.set("receipt_width_mm", "70")
    settings.set("shop_gstin", "33ABCDE1234F1Z5")
    assert settings.get("shop_gstin") == "33ABCDE1234F1Z5"


@pytest.mark.parametrize("code,kind,dpi,width", [
    ("2000000000015", "EAN13", 203, 50), ("83MW-CCS-L-BLK", "CODE128", 203, 50),
    ("CCS-M-BLK", "CODE128", 300, 38), ("MW000123", "CODE128", 203, 40)])
def test_printed_tag_barcode_scans_back(qapp, code, kind, dpi, width):
    """Decode the rendered tag with a real barcode reader to prove it is scannable."""
    zxingcpp = pytest.importorskip("zxingcpp")
    import io

    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice

    from mw83.printing.tags import TagTemplate, render_preview

    item = {"product_name": "Shirt", "size": "L", "colour": "Black", "barcode": code, "mrp": 129900, "price": 99900}
    img = render_preview(item, TagTemplate(barcode_kind=kind, width_mm=width), dpi=dpi)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    found = [r.text for r in zxingcpp.read_barcodes(Image.open(io.BytesIO(bytes(buf.data()))))]
    assert found == [code]
