"""Application start-up."""
from __future__ import annotations

import logging
import sys
import traceback

from . import APP_NAME, paths
from .logging_setup import log_path, setup_logging


def self_test(out_file: str) -> int:
    """Used by the build pipeline to prove a packaged exe works: temporary data only."""
    import os
    import tempfile

    tmp = tempfile.mkdtemp(prefix="mw83-selftest-")
    os.environ["MW83_DATA_DIR"] = os.path.join(tmp, "data")
    os.environ["MW83_BACKUP_DIR"] = os.path.join(tmp, "backups")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines = []
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])  # noqa: F841
        from .db import Database
        from .printing.pdf import receipt_pdf
        from .printing.receipt import build_receipt
        from .printing.tags import TagTemplate, render_preview
        from .services import backup, catalog, sales
        from .services.catalog import ProductInput, VariantInput
        from .services.settings import Settings

        db = Database(paths.db_path())
        st = Settings(db)
        pid = catalog.save_product(db, ProductInput("Self-test shirt", None, 50000,
                                                    variants=[VariantInput(size="M", opening_stock=2)]))
        v = catalog.get_product(db, pid)["variants"][0]
        ln = sales.line_from_variant(catalog.variant_by_code(db, v["barcode"]))
        sid = sales.complete_sale(db, st, sales.SaleRequest(lines=[ln], payment=sales.PaymentInput(cash_received=50000)))
        sale = sales.get_sale(db, sid)
        receipt_pdf(build_receipt(sale, {"shop_name": "TEST"}, 48), os.path.join(tmp, "r.pdf"))
        render_preview({"product_name": "x", "size": "M", "colour": "", "barcode": v["barcode"], "mrp": 0,
                        "price": 50000}, TagTemplate())
        backup.validate_backup(backup.manual_backup(db, st))
        db.close()
        lines.append(f"OK {sale['invoice_no']}")
        code = 0
    except Exception:  # noqa: BLE001
        lines.append("FAIL\n" + traceback.format_exc())
        code = 1
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return code


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) >= 3 and argv[1] == "--self-test":
        return self_test(argv[2])
    log = setup_logging()
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    from .ui.style import STYLE

    app.setStyleSheet(STYLE)

    def excepthook(exc_type, exc, tb):
        log.error("unhandled error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        from .errors import UserError

        if isinstance(exc, UserError):
            QMessageBox.warning(None, exc.title, exc.message)
        else:
            QMessageBox.critical(None, "Unexpected problem",
                                 "Something went wrong. Your saved bills are safe.\n\n"
                                 f"Technical details were saved to:\n{log_path()}")

    sys.excepthook = excepthook

    lock = QLockFile(str(paths.data_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "The billing app is already open. Look for it on the taskbar.")
        return 0

    from .db import Database
    from .errors import UserError
    from .services.settings import Settings
    from .ui.common import AppContext
    from .ui.main_window import MainWindow

    try:
        db = Database(paths.db_path())
    except UserError as exc:
        QMessageBox.critical(None, exc.title, exc.message)
        return 1
    except Exception:  # noqa: BLE001
        logging.getLogger("mw83").exception("could not open database")
        QMessageBox.critical(None, "Cannot open data",
                             "The shop data could not be opened. Do not delete anything.\n"
                             "Restore the latest backup from another computer copy or contact support.\n\n"
                             f"Details: {log_path()}")
        return 1
    log.info("started; data at %s", paths.data_dir())
    win = MainWindow(AppContext(db, Settings(db)))
    win.showMaximized()
    code = app.exec()
    db.close()
    lock.unlock()
    return code
