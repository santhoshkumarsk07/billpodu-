"""Backup now, list backups, restore with validation, confirmation and a safety backup."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLabel, QVBoxLayout, QWidget

from ...services import backup
from ..common import (AppContext, button, confirm, fill_table, hint_label, hrow, info, make_table, run_safely,
                      selected_id, show_error, title_label)


class BackupPage(QWidget):
    def __init__(self, ctx: AppContext, on_restored=None):
        super().__init__()
        self.setObjectName("page")
        self.ctx, self.on_restored = ctx, on_restored
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Backup & Restore"))
        self.where = QLabel()
        self.where.setWordWrap(True)
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.where)
        lay.addLayout(hrow(button("Backup now", self.backup_now, primary=True),
                           button("Open backup folder", self.open_folder)))
        lay.addWidget(QLabel("<b>Backups in this folder</b> (newest first)"))
        self.table = make_table(["File", "Size", "Type"], stretch_col=0)
        lay.addWidget(self.table, 1)
        restore_sel = button("Restore selected backup…", self.restore_selected)
        restore_sel.setObjectName("danger")
        restore_file = button("Restore from another file…", self.restore_file)
        restore_file.setObjectName("danger")
        lay.addLayout(hrow(restore_sel, restore_file))
        lay.addWidget(hint_label(
            "A backup contains all products, stock, bills, customers, settings and product pictures. Restoring "
            "REPLACES all current data with the backup. Before restoring, the app always saves a safety backup of "
            "the current data (file name ends with 'before-restore'). Backups are never deleted when the app is "
            "uninstalled. Change the folder, how often and how many to keep in Settings → Backup."))

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        d = backup.backup_dir(self.ctx.settings)
        auto = {"DAILY": "every day", "WEEKLY": "every week", "OFF": "OFF"}.get(
            self.ctx.settings.get("backup_frequency"), "every day")
        last = self.ctx.settings.get("last_auto_backup") or "never"
        self.where.setText(f"Backup folder: <b>{d}</b><br>Automatic backup: <b>{auto}</b> · last automatic "
                           f"backup: {last} · keeping the newest {self.ctx.settings.get_int('backups_to_keep')}")
        files = backup.list_backups(d)
        fill_table(self.table, [[p.name, f"{p.stat().st_size / 1024 / 1024:.1f} MB",
                                 "Safety copy before restore" if "before-restore" in p.name else
                                 ("Automatic" if "-auto" in p.name else "Manual")] for p in files],
                   ids=[str(p) for p in files])

    def backup_now(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            path = backup.manual_backup(self.ctx.db, self.ctx.settings)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            show_error(self, exc, "making the backup")
            return
        QApplication.restoreOverrideCursor()
        self.reload()
        info(self, "Backup done", f"Backup saved:\n{path}")

    def open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        d = backup.backup_dir(self.ctx.settings)
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def restore_selected(self):
        path = selected_id(self.table)
        if path:
            self.restore(Path(path))

    def restore_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose backup file", str(backup.backup_dir(self.ctx.settings)),
                                              "Backup files (*.zip)")
        if path:
            self.restore(Path(path))

    def restore(self, path: Path):
        manifest = run_safely(self, lambda: backup.validate_backup(path), "checking the backup")
        if manifest is None:
            return
        c = manifest.get("counts", {})
        details = (f"Backup made: {manifest.get('created_at', 'unknown')}\n"
                   f"Products: {c.get('products', '?')}   Bills: {c.get('sales', '?')}   "
                   f"Customers: {c.get('customers', '?')}")
        if not confirm(self, "Restore backup", "The backup file is valid.\n\n" + details +
                       "\n\n⚠ ALL CURRENT DATA WILL BE REPLACED by this backup.\nA safety backup of the current data "
                       "will be made first.\n\nContinue?", danger=True):
            return
        word, ok = QInputDialog.getText(self, "Confirm restore", "Type RESTORE to confirm:")
        if not ok or word.strip().upper() != "RESTORE":
            info(self, "Not restored", "Restore cancelled. Nothing was changed.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            safety = backup.restore_backup(self.ctx.db, self.ctx.settings, path)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            show_error(self, exc, "restoring the backup")
            return
        QApplication.restoreOverrideCursor()
        if self.on_restored:
            self.on_restored()
        self.reload()
        info(self, "Restored", f"Backup restored.\n\nYour previous data was saved first as:\n{safety}")
