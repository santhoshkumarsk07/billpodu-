from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSplitter,
                               QVBoxLayout, QWidget)

from ...services import customers
from ..common import (AppContext, button, confirm, fill_table, hrow, make_table, run_safely, selected_id, show_error,
                      title_label)


class CustomerDialog(QDialog):
    def __init__(self, ctx: AppContext, customer_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.customer_id = ctx, customer_id
        self.setWindowTitle("Edit customer" if customer_id else "Add customer")
        form = QFormLayout(self)
        self.name, self.phone, self.notes = QLineEdit(), QLineEdit(), QLineEdit()
        self.name.setMaxLength(80)
        self.phone.setMaxLength(16)
        self.notes.setMaxLength(300)
        form.addRow("Name *", self.name)
        form.addRow("Phone", self.phone)
        form.addRow("Notes", self.notes)
        if customer_id:
            c = customers.get_customer(ctx.db, customer_id)
            self.name.setText(c["name"])
            self.phone.setText(c["phone"])
            self.notes.setText(c["notes"])
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def save(self):
        try:
            if self.customer_id:
                customers.update_customer(self.ctx.db, self.customer_id, self.name.text(), self.phone.text(),
                                          self.notes.text())
            else:
                self.customer_id = customers.add_customer(self.ctx.db, self.name.text(), self.phone.text(),
                                                          self.notes.text())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "saving the customer")
            return
        self.accept()


class CustomersPage(QWidget):
    def __init__(self, ctx: AppContext, open_sale=None):
        super().__init__()
        self.setObjectName("page")
        self.ctx, self.open_sale = ctx, open_sale
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Customers"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or phone…")
        self.archived = QCheckBox("Show archived")
        self.timer = QTimer(self, singleShot=True, interval=200, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self.timer.start())
        self.archived.toggled.connect(lambda _: self.reload())
        lay.addLayout(hrow(self.search, self.archived, stretch=False))
        split = QSplitter()
        self.table = make_table(["Name", "Phone", "Bills", "Total spent", "Status"])
        self.table.itemSelectionChanged.connect(self.load_history)
        self.table.doubleClicked.connect(lambda _: self.edit())
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.hist_label = QLabel("Purchase history")
        rl.addWidget(self.hist_label)
        self.hist = make_table(["Bill", "Date", "Items", "Total", "Status"])
        self.hist.doubleClicked.connect(self.open_bill)
        rl.addWidget(self.hist)
        split.addWidget(right)
        lay.addWidget(split, 1)
        lay.addLayout(hrow(button("Add customer", self.add, primary=True), button("Edit", self.edit),
                           button("Archive / restore", self.toggle)))

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        rows = customers.search(self.ctx.db, self.search.text(), self.archived.isChecked())
        fill_table(self.table, [[r["name"], r["phone"], r["bills"], r["spent"],
                                 "Active" if r["active"] else "Archived"] for r in rows],
                   money_cols={3}, ids=[r["id"] for r in rows])

    def load_history(self):
        cid = selected_id(self.table)
        if not cid:
            return
        rows = customers.purchase_history(self.ctx.db, cid)
        self.hist_label.setText(f"Purchase history ({len(rows)} bills) — double-click a bill to open it")
        fill_table(self.hist, [[r["invoice_no"], r["created_at"], r["items"], r["total_paise"], r["status"].title()]
                               for r in rows], money_cols={3}, ids=[r["id"] for r in rows])

    def open_bill(self, _):
        sid = selected_id(self.hist)
        if sid and self.open_sale:
            self.open_sale(sid)

    def add(self):
        if CustomerDialog(self.ctx, None, self).exec():
            self.reload()

    def edit(self):
        cid = selected_id(self.table)
        if cid and cid == customers.walkin_id(self.ctx.db):
            return
        if cid and CustomerDialog(self.ctx, cid, self).exec():
            self.reload()

    def toggle(self):
        cid = selected_id(self.table)
        if not cid:
            return
        c = customers.get_customer(self.ctx.db, cid)
        if c["active"] and not confirm(self, "Archive customer", f"Archive {c['name']}? Their old bills are kept."):
            return
        run_safely(self, lambda: customers.set_active(self.ctx.db, cid, not c["active"]))
        self.reload()
