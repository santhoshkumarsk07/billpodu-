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
    assert "Unknown barcode" in pos.banner.text()
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
    QTest.keyClicks(pos.upi, "500")
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
