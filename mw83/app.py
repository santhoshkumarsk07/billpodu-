"""Application start-up."""
from __future__ import annotations

import logging
import sys
import traceback

from . import APP_NAME, paths
from .logging_setup import log_path, setup_logging


def main(argv: list[str] | None = None) -> int:
    log = setup_logging()
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(argv if argv is not None else sys.argv)
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
