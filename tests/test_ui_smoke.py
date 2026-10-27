"""Drive the real widgets offscreen: scanner input, billing, every page loads."""
import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, db, settings, make_product, monkeypatch):
    from mw83.ui import main_window
    from mw83.ui.common import AppContext
    from mw83.ui.pages import pos

    # Never block on modal dialogs during tests.
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(pos.SaleDoneDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(pos.VariantSearchDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    settings.set("auto_print_receipt", "0")
    make_product()
    w = main_window.MainWindow(AppContext(db, settings))
    w.backup_timer.stop()
    w.show()
    yield w
    w.close()


def scan(page, code):
    """Type like a keyboard-wedge scanner: characters then Enter."""
    QTest.keyClicks(page.scan, code)
    QTest.keyClick(page.scan, Qt.Key.Key_Return)


def test_opens_on_billing(window):
    assert window.stack.currentWidget() is window.page("Billing / POS")


def test_scanner_adds_and_increments_and_completes(window, db):
    from mw83.services import catalog

    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    scan(pos, "1000001")
    scan(pos, "CCS-L-BLK")
    assert [(ln.size, ln.qty) for ln in pos.lines] == [("M", 2), ("L", 1)]
    assert pos.total_lbl.text() == "2,997.00"
    assert pos.scan.text() == ""
    scan(pos, "does-not-exist")
    assert "No product found" in pos.banner.text()
    assert len(pos.lines) == 2
    QTest.keyClicks(pos.cash, "3000")
    assert "3.00" in pos.change_lbl.text()
    pos.complete()
    assert pos.lines == []
    assert db.scalar("SELECT COUNT(*) FROM sales") == 1
    assert catalog.variant_by_code(db, "1000001")["stock"] == 8
    assert db.scalar("SELECT change_paise FROM sales") == 300


def test_out_of_stock_and_quantity_keys(window, db):
    from mw83.services import inventory, catalog

    pos = window.page("Billing / POS")
    vid = catalog.variant_by_code(db, "1000002")["variant_id"]
    scan(pos, "1000002")
    QTest.keyClick(pos.scan, Qt.Key.Key_Plus)
    assert pos.lines[0].qty == 2
    QTest.keyClick(pos.scan, Qt.Key.Key_Minus)
    assert pos.lines[0].qty == 1
    QTest.keyClick(pos.scan, Qt.Key.Key_Delete)
    assert pos.lines == []
    inventory.adjust_stock(db, vid, "LOST", 5, "test")
    scan(pos, "1000002")
    assert "out of stock" in pos.banner.text().lower()
    assert pos.lines == []


def test_hold_and_resume(window, db, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from mw83.ui.pages import pos as posmod

    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Ravi", True)))
    pos.hold()
    assert pos.lines == [] and db.scalar("SELECT COUNT(*) FROM held_bills") == 1

    def fake_exec(self):
        self.held_id = db.scalar("SELECT id FROM held_bills")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(posmod.HeldBillsDialog, "exec", fake_exec)
    pos.resume()
    assert len(pos.lines) == 1 and db.scalar("SELECT COUNT(*) FROM held_bills") == 0


def test_split_payment_through_ui(window, db):
    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    pos.set_mode("SPLIT")
    QTest.keyClicks(pos.upi, "500")
    assert "Cash Rs. 499.00" in pos.change_lbl.text()
    pos.complete()
    pays = dict(db.all("SELECT method, amount_paise FROM sale_payments"))
    assert pays == {"UPI": 50000, "CASH": 49900}


def test_every_page_opens(window):
    from mw83.ui.main_window import SECTIONS

    for name in SECTIONS:
        window.go_to(name)
        QApplication.processEvents()
        assert window.stack.currentWidget() is window.page(name)


def test_product_dialog_creates_variants_with_opening_stock(window, db):
    from PySide6.QtWidgets import QTableWidgetItem

    from mw83.services import catalog
    from mw83.ui.pages.products import ProductDialog

    dlg = ProductDialog(window.ctx, None, window)
    dlg.name.setText("Polo T-Shirt")
    dlg.price.setText("599")
    dlg.mrp.setText("799")
    dlg.vt.setItem(0, 0, QTableWidgetItem("M"))
    dlg.vt.setItem(0, 7, QTableWidgetItem("3"))
    dlg.add_row({"size": "L"})
    dlg.vt.setItem(1, 3, QTableWidgetItem("POLO-L"))
    dlg.save()
    assert dlg.result() == QDialog.DialogCode.Accepted
    p = catalog.get_product(db, dlg.product_id)
    assert {v["size"]: v["stock"] for v in p["variants"]} == {"M": 3, "L": 0}
    assert catalog.variant_by_code(db, "POLO-L")["size"] == "L"
    # duplicate barcode is refused with the dialog still open
    dup = ProductDialog(window.ctx, None, window)
    dup.name.setText("Other")
    dup.price.setText("10")
    dup.vt.setItem(0, 3, QTableWidgetItem("POLO-L"))
    dup.save()
    assert dup.result() != QDialog.DialogCode.Accepted
    assert db.scalar("SELECT COUNT(*) FROM products WHERE name = 'Other'") == 0


def test_return_page_flow(window, db):
    from mw83.services import catalog

    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    scan(pos, "1000001")
    pos.complete()
    window.start_return(db.scalar("SELECT id FROM sales"))
    page = window.page("Returns")
    page.table.cellWidget(0, 5).setValue(1)
    assert page.refund_lbl.text() == "Rs. 999.00"
    page.save()
    assert db.scalar("SELECT COUNT(*) FROM returns") == 1
    assert catalog.variant_by_code(db, "1000001")["stock"] == 9


def test_settings_page_saves_and_rejects_bad_gstin(window, settings):
    window.go_to("Settings")
    page = window.page("Settings")
    page.shop_phone.setText("98400 00000")
    page.save()
    assert settings.get("shop_phone") == "98400 00000"
    page.shop_gstin.setText("BADGSTIN")
    assert page.save() is False
    assert settings.get("shop_gstin") == ""


def test_restore_while_running_refreshes_pages(window, db, settings):
    from mw83.services import backup

    pos = window.page("Billing / POS")
    bk = backup.manual_backup(db, settings)
    scan(pos, "1000001")
    pos.complete()
    backup.restore_backup(db, settings, bk)
    window.after_restore()
    assert db.scalar("SELECT COUNT(*) FROM sales") == 0
    window.go_to("Billing / POS")
    pos2 = window.page("Billing / POS")
    scan(pos2, "1000001")
    pos2.complete()
    assert db.scalar("SELECT invoice_no FROM sales") == "83MW-0001"


def test_default_customer_setting_and_search_dialog(window, db, settings):
    from mw83.services import customers
    from mw83.ui.dialogs import VariantSearchDialog

    cid = customers.add_customer(db, "Regular Ravi", "9840000001")
    settings.set("default_customer_id", str(cid))
    pos = window.page("Billing / POS")
    pos.new_bill(confirm_first=False)
    assert pos.customer_id == cid
    assert pos.cust_name.text() == "Regular Ravi" and pos.mobile.text() == "9840000001"
    customers.set_active(db, cid, False)
    pos.new_bill(confirm_first=False)
    assert pos.customer_id is None and pos.cust_name.text() == ""   # empty = walk-in
    dlg = VariantSearchDialog(window.ctx, window, "shirt", multi=True)
    assert dlg.table.rowCount() == 2
    dlg.table.selectAll()
    dlg.accept_current()
    assert len(dlg.selected) == 2


def test_add_by_item_number_style_code_and_name(window, db, monkeypatch):
    from mw83.services import catalog
    from mw83.ui.pages import pos as posmod

    pos = window.page("Billing / POS")
    item_no = catalog.variant_by_code(db, "1000002")["variant_id"]
    scan(pos, str(item_no))                       # item number
    assert [ln.size for ln in pos.lines] == ["L"]
    scan(pos, "classic cotton shirt l")           # name that matches exactly one size
    assert pos.lines[0].qty == 2
    chosen = catalog.variant_by_code(db, "1000001")["variant_id"]

    def pick_first(self):
        assert self.table.rowCount() == 2         # name matching several sizes opens the chooser
        self.selected = [chosen]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(posmod.VariantSearchDialog, "exec", pick_first)
    scan(pos, "cotton shirt")
    assert sorted(ln.size for ln in pos.lines) == ["L", "M"]
    scan(pos, "zzz no such thing")
    assert "No product found" in pos.banner.text()


def test_bill_discount_box_percent_and_limits(window, db, settings):
    pos = window.page("Billing / POS")
    scan(pos, "1000001")                          # 999.00
    QTest.keyClicks(pos.disc_value, "10")
    pos.apply_bill_discount()
    assert pos.bill.type == "PERCENT" and pos.bill.value == 1000
    assert pos.total_lbl.text() == "899.10"
    # the box cannot even accept more than 100
    pos.disc_value.clear()
    QTest.keyClicks(pos.disc_value, "150")
    assert float(pos.disc_value.text() or 0) <= 100
    pos.disc_value.setText("100")
    pos.apply_bill_discount()
    assert pos.total_lbl.text() == "0.00"
    # the owner's limit in Settings is enforced
    settings.set("max_discount_percent_bp", "1500")
    pos.disc_value.setText("20")
    pos.apply_bill_discount()
    assert pos.disc_value.property("invalid") is True
    pos.complete()
    assert db.scalar("SELECT COUNT(*) FROM sales") == 0  # not saved with an invalid discount
    pos.disc_value.setText("15")
    pos.apply_bill_discount()
    pos.complete()
    assert db.scalar("SELECT bill_discount_paise FROM sales") == 14985


def test_bill_discount_amount_mode(window, db):
    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    pos.disc_type.setCurrentIndex(1)              # Rs. off
    pos.disc_value.setText("99.90")
    pos.apply_bill_discount()
    assert pos.total_lbl.text() == "899.10"
    pos.disc_value.setText("5000")
    pos.apply_bill_discount()
    assert pos.disc_value.property("invalid") is True
    assert pos.total_lbl.text() == "899.10"       # bad value is not applied


def test_stylesheet_and_icons_load(app):
    from mw83.paths import resource_path
    from mw83.ui.style import build_style

    css = build_style()
    for name in ("arrow-down.png", "arrow-up.png", "app.ico", "app.png"):
        assert resource_path(f"assets/{name}").is_file(), name
    assert "ARROW_" not in css and css.count("{") == css.count("}")
    app.setStyleSheet(css)
    app.setStyleSheet("")


def test_customer_mobile_on_bill_new_then_found(window, db):
    from mw83.services import customers

    pos = window.page("Billing / POS")
    QTest.keyClicks(pos.mobile, "98400 12345")
    assert "New customer" in pos.cust_status.text()
    QTest.keyClicks(pos.cust_name, "Ravi Kumar")
    scan(pos, "1000001")
    pos.complete()
    c = customers.find_by_mobile(db, "9840012345")
    assert c["name"] == "Ravi Kumar" and c["bills"] == 1
    assert db.scalar("SELECT customer_name FROM sales") == "Ravi Kumar"
    # next visit: typing the mobile fills the name and locks it
    QTest.keyClicks(pos.mobile, "9840012345")
    assert pos.cust_name.text() == "Ravi Kumar" and pos.cust_name.isReadOnly()
    assert pos.customer_id == c["id"]
    scan(pos, "1000001")
    pos.complete()
    assert db.scalar("SELECT COUNT(*) FROM customers WHERE phone = '9840012345'") == 1
    # wrong mobile is refused with nothing saved
    QTest.keyClicks(pos.mobile, "12345")
    scan(pos, "1000001")
    pos.complete()
    assert db.scalar("SELECT COUNT(*) FROM sales") == 2
    pos.clear_customer()
    assert pos.mobile.text() == "" and not pos.cust_name.isReadOnly()


def test_walkin_when_customer_empty(window, db):
    from mw83.services import customers

    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    pos.complete()
    assert db.scalar("SELECT customer_id FROM sales") == customers.walkin_id(db)


def test_product_name_box_suggestions_and_enter(window, db, monkeypatch):
    from mw83.services import catalog

    pos = window.page("Billing / POS")
    pos.name_box.setText("cotton")
    pos._refresh_name_list()
    assert pos.name_model.rowCount() == 2
    label = pos.name_model.item(1).text()
    assert "Rs. 999.00" in label and "stock" in label
    pos._name_chosen(label)                       # picking from the drop-down list
    assert len(pos.lines) == 1
    pos.name_box.clear()
    QTest.keyClicks(pos.name_box, "cotton shirt m black")
    QTest.keyClick(pos.name_box, Qt.Key.Key_Return)   # typed name + Enter, exactly one match
    m = catalog.variant_by_code(db, "1000001")["variant_id"]
    assert sum(ln.qty for ln in pos.lines) == 2
    assert any(ln.variant_id == m for ln in pos.lines)
    assert pos.name_box.text() == ""


def test_upi_and_card_modes_and_quick_cash(window, db):
    pos = window.page("Billing / POS")
    scan(pos, "1000001")
    pos.set_mode("UPI")
    assert not pos.cash.isVisible() and pos.upi_ref.isVisible() and not pos.upi.isVisible()
    assert "Collect Rs. 999.00 by UPI" in pos.change_lbl.text()
    QTest.keyClicks(pos.upi_ref, "T123")
    pos.complete()
    assert db.all("SELECT method, amount_paise, reference FROM sale_payments")[0][:] == ("UPI", 99900, "T123")
    scan(pos, "1000001")
    pos.set_mode("CARD")
    pos.complete()
    assert db.scalar("SELECT method FROM sale_payments ORDER BY id DESC LIMIT 1") == "CARD"
    scan(pos, "1000001")
    pos.set_mode("CASH")
    pos.quick_cash(2000)
    assert "Return to customer: Rs. 1,001.00" in pos.change_lbl.text()
    pos.quick_cash(None)
    assert "no change" in pos.change_lbl.text()


def test_hold_keeps_customer(window, db, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from mw83.ui.pages import pos as posmod

    pos = window.page("Billing / POS")
    QTest.keyClicks(pos.mobile, "9876543210")
    QTest.keyClicks(pos.cust_name, "Arun")
    scan(pos, "1000001")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (k.get("text", ""), True)))
    pos.hold()
    assert pos.mobile.text() == ""

    def fake_exec(self):
        self.held_id = db.scalar("SELECT id FROM held_bills")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(posmod.HeldBillsDialog, "exec", fake_exec)
    pos.resume()
    assert pos.mobile.text() == "9876543210" and pos.cust_name.text() == "Arun"
