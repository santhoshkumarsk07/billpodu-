"""Main window: left sidebar with the 12 sections. Opens on Billing / POS."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, \
    QWidget

from .. import APP_VERSION, paths
from ..services import backup
from .common import AppContext

log = logging.getLogger("mw83.ui")

SECTIONS = ["Dashboard", "Billing / POS", "Products", "Categories", "Barcode & Tags", "Inventory", "Customers",
            "Sales History", "Returns", "Reports", "Settings", "Backup & Restore"]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{ctx.settings.get('shop_name')} — Billing & Inventory")
        icon = paths.resource_path("assets/app.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QVBoxLayout()
        side.setSpacing(0)
        brand = QLabel(ctx.settings.get("shop_name"))
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("sidebar")
        self.nav.addItems(SECTIONS)
        self.nav.setFixedWidth(190)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        side.addWidget(self.nav, 1)
        ver = QLabel(f"  v{APP_VERSION}")
        ver.setStyleSheet("background:#1f2a37;color:#6b7280;padding:4px;")
        side.addWidget(ver)
        root.addLayout(side)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.pages: dict[str, QWidget] = {}
        self.nav.currentRowChanged.connect(self._show_section)
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.go_to("Billing / POS"))
        self.go_to("Billing / POS")
        self.statusBar().showMessage("Ready. Data folder: " + str(paths.data_dir()))
        self.backup_timer = QTimer(self, interval=60 * 60 * 1000, timeout=self.auto_backup)
        self.backup_timer.start()
        QTimer.singleShot(5000, self.auto_backup)

    # Pages are created on first use so the app opens fast.
    def _make(self, name: str) -> QWidget:
        from .pages import (backup as backup_page, categories, customers, dashboard, inventory, pos, products,
                            reports, returns, sales_history, settings, tags)

        ctx = self.ctx
        factory = {
            "Dashboard": lambda: dashboard.DashboardPage(ctx, self.go_to),
            "Billing / POS": lambda: pos.PosPage(ctx),
            "Products": lambda: products.ProductsPage(ctx),
            "Categories": lambda: categories.CategoriesPage(ctx),
            "Barcode & Tags": lambda: tags.TagsPage(ctx),
            "Inventory": lambda: inventory.InventoryPage(ctx),
            "Customers": lambda: customers.CustomersPage(ctx, self.open_sale),
            "Sales History": lambda: sales_history.SalesHistoryPage(ctx, self.start_return),
            "Returns": lambda: returns.ReturnsPage(ctx, self.go_to),
            "Reports": lambda: reports.ReportsPage(ctx),
            "Settings": lambda: settings.SettingsPage(ctx),
            "Backup & Restore": lambda: backup_page.BackupPage(ctx, self.after_restore),
        }
        page = factory[name]()
        self.pages[name] = page
        self.stack.addWidget(page)
        return page

    def page(self, name: str) -> QWidget:
        return self.pages.get(name) or self._make(name)

    def _show_section(self, row: int):
        if 0 <= row < len(SECTIONS):
            self.stack.setCurrentWidget(self.page(SECTIONS[row]))

    def go_to(self, name: str):
        row = SECTIONS.index(name)
        if self.nav.currentRow() == row:
            self._show_section(row)
        else:
            self.nav.setCurrentRow(row)

    def open_sale(self, sale_id: int):
        self.go_to("Sales History")
        self.page("Sales History").open_sale(sale_id)

    def start_return(self, sale_id: int):
        self.go_to("Returns")
        self.page("Returns").load_sale(sale_id)

    def after_restore(self):
        """Data was replaced: throw away pages that may hold old data (except the backup page)."""
        for name in list(self.pages):
            if name == "Backup & Restore":
                continue
            w = self.pages.pop(name)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.setWindowTitle(f"{self.ctx.settings.get('shop_name')} — Billing & Inventory")

    def auto_backup(self, quiet: bool = False):
        try:
            path = backup.auto_backup_if_due(self.ctx.db, self.ctx.settings)
            if path:
                self.statusBar().showMessage(f"Automatic backup saved: {path}", 15000)
        except Exception as exc:  # noqa: BLE001
            log.exception("automatic backup failed")
            self.statusBar().showMessage("⚠ Automatic backup FAILED — open Backup & Restore", 0)
            if not quiet:
                msg = exc.message if hasattr(exc, "message") else "See the log file for details."
                QMessageBox.warning(self, "Automatic backup failed",
                                    f"Today's automatic backup could not be made.\n\n{msg}\n\n"
                                    "Billing still works. Check the backup folder in Settings → Backup.")

    def closeEvent(self, e):
        pos = self.pages.get("Billing / POS")
        if pos is not None and pos.lines:
            box = QMessageBox.question(self, "Unsaved bill", "The current bill is not saved. Hold it before closing?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                       QMessageBox.StandardButton.Cancel)
            if box == QMessageBox.StandardButton.Cancel:
                e.ignore()
                return
            if box == QMessageBox.StandardButton.Yes:
                from ..services import sales

                try:
                    sales.hold_bill(self.ctx.db, "Held when closing", pos._state())
                except Exception:  # noqa: BLE001
                    log.exception("could not hold bill on close")
        self.auto_backup(quiet=True)
        e.accept()
