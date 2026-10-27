"""Shared UI helpers: friendly errors, confirmations, tables, money inputs, background jobs."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QAbstractItemView, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QWidget)

from ..db import Database
from ..errors import UserError
from ..logging_setup import log_path
from ..money import fmt
from ..services.settings import Settings

log = logging.getLogger("mw83.ui")


@dataclass
class AppContext:
    db: Database
    settings: Settings


def show_error(parent: QWidget | None, exc: BaseException, action: str = "") -> None:
    """Plain message for the owner; technical details only go to the log file."""
    if isinstance(exc, UserError):
        QMessageBox.warning(parent, exc.title, exc.message)
        return
    log.error("unexpected error during %s", action or "an action", exc_info=exc)
    if isinstance(exc, sqlite3.Error):
        msg = ("The database could not save or read this information. Nothing was half-saved.\n\n"
               "Try again. If it keeps happening, restart the app and make a backup.")
        title = "Database problem"
    else:
        msg = "Something went wrong" + (f" while {action}" if action else "") + ". Nothing was half-saved."
        title = "Unexpected problem"
    QMessageBox.critical(parent, title, f"{msg}\n\nTechnical details were saved to:\n{log_path()}")


def run_safely(parent: QWidget | None, fn: Callable, action: str = ""):
    """Call fn(); show a friendly error and return None if it fails."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - UI boundary
        show_error(parent, exc, action)
        return None


def confirm(parent: QWidget | None, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question, title, text,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


MONEY_RE = r"^\d{0,8}(\.\d{0,2})?$"


def money_edit(placeholder: str = "0.00", width: int = 0) -> QLineEdit:
    e = QLineEdit()
    e.setValidator(QRegularExpressionValidator(MONEY_RE))
    e.setPlaceholderText(placeholder)
    e.setAlignment(Qt.AlignmentFlag.AlignRight)
    if width:
        e.setFixedWidth(width)
    return e


def percent_edit() -> QLineEdit:
    e = QLineEdit()
    e.setValidator(QRegularExpressionValidator(r"^(100(\.0{0,2})?|\d{0,2}(\.\d{0,2})?)$"))
    e.setPlaceholderText("0")
    e.setAlignment(Qt.AlignmentFlag.AlignRight)
    return e


def int_edit(placeholder: str = "0", allow_negative: bool = False) -> QLineEdit:
    e = QLineEdit()
    e.setValidator(QRegularExpressionValidator(r"^-?\d{0,6}$" if allow_negative else r"^\d{0,6}$"))
    e.setPlaceholderText(placeholder)
    return e


def make_table(headers: list[str], stretch_col: int = 0) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(26)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if 0 <= stretch_col < len(headers):
        h.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    return t


def fill_table(table: QTableWidget, rows: list[list], money_cols: set[int] = frozenset(),
               ids: list | None = None, right_cols: set[int] = frozenset()) -> None:
    """Fill a table. Row ids are stored in column 0's UserRole."""
    table.setUpdatesEnabled(False)
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if c in money_cols and isinstance(value, int):
                item = QTableWidgetItem(fmt(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            else:
                item = QTableWidgetItem("" if value is None else str(value))
                if c in right_cols or isinstance(value, int):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if c == 0 and ids is not None:
                item.setData(Qt.ItemDataRole.UserRole, ids[r])
            table.setItem(r, c, item)
    table.setUpdatesEnabled(True)


def selected_id(table: QTableWidget):
    row = table.currentRow()
    if row < 0 or table.item(row, 0) is None:
        return None
    return table.item(row, 0).data(Qt.ItemDataRole.UserRole)


def title_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("title")
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("hint")
    return lbl


def button(text: str, slot: Callable | None = None, primary: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def hrow(*widgets, stretch: bool = True) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    if stretch:
        lay.addStretch(1)
    return lay


class DateRange(QWidget):
    changed = Signal()

    def __init__(self, days_back: int = 0, parent=None):
        super().__init__(parent)
        today = QDate.currentDate()
        self.start = QDateEdit(today.addDays(-days_back))
        self.end = QDateEdit(today)
        for d in (self.start, self.end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd-MM-yyyy")
            d.dateChanged.connect(self.changed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("From"))
        lay.addWidget(self.start)
        lay.addWidget(QLabel("To"))
        lay.addWidget(self.end)
        for label, fn in (("Today", self.today), ("This month", self.this_month), ("Last 30 days", self.last30)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            lay.addWidget(b)

    def today(self):
        self.start.setDate(QDate.currentDate())
        self.end.setDate(QDate.currentDate())

    def this_month(self):
        t = QDate.currentDate()
        self.start.setDate(QDate(t.year(), t.month(), 1))
        self.end.setDate(t)

    def last30(self):
        self.start.setDate(QDate.currentDate().addDays(-29))
        self.end.setDate(QDate.currentDate())

    def values(self) -> tuple[str, str]:
        a, b = self.start.date(), self.end.date()
        if a > b:
            a, b = b, a
        return a.toString("yyyy-MM-dd"), b.toString("yyyy-MM-dd")


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class Job(QRunnable):
    """Run a read-only query on a worker thread with its own database connection."""

    def __init__(self, db_path, fn: Callable, on_done: Callable, on_failed: Callable):
        super().__init__()
        self.db_path, self.fn = db_path, fn
        self.signals = _Signals()
        self.signals.done.connect(on_done)
        self.signals.failed.connect(on_failed)

    def run(self):
        from ..db.database import connect

        try:
            conn = connect(self.db_path, readonly=True)
            try:
                result = self.fn(conn)
            finally:
                conn.close()
            self.signals.done.emit(result)
        except Exception as exc:  # noqa: BLE001 - reported on the UI thread
            self.signals.failed.emit(exc)


def run_in_background(ctx: AppContext, fn: Callable, on_done: Callable, parent: QWidget, action: str) -> Job:
    job = Job(ctx.db.path, fn, on_done, lambda exc: show_error(parent, exc, action))
    QThreadPool.globalInstance().start(job)
    return job


def money_text(edit: QLineEdit, field: str = "Amount") -> int:
    from ..money import parse_rupees

    t = edit.text().strip()
    return 0 if t == "" else parse_rupees(t, field)
