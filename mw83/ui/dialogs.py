"""Small reusable dialogs: product search, customer picker, discount entry."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QVBoxLayout)

from ..errors import ValidationError
from ..money import fmt_percent, fmt_plain, parse_percent, parse_rupees
from ..services import catalog, customers
from .common import AppContext, button, fill_table, hint_label, hrow, make_table, run_safely, selected_id


class VariantSearchDialog(QDialog):
    """Find a product size/colour by name, brand, SKU or barcode. Enter picks the highlighted row."""

    def __init__(self, ctx: AppContext, parent=None, text: str = "", active_only: bool = True,
                 multi: bool = False, title: str = "Search product"):
        super().__init__(parent)
        self.ctx, self.active_only = ctx, active_only
        self.setWindowTitle(title)
        self.resize(900, 520)
        self.search = QLineEdit(text)
        self.search.setPlaceholderText("Type name, brand, size, colour, SKU or barcode…")
        self.table = make_table(["Product", "Size", "Colour", "SKU", "Barcode", "Price", "Stock"])
        if multi:
            self.table.setSelectionMode(self.table.SelectionMode.ExtendedSelection)
        self.timer = QTimer(self, singleShot=True, interval=150, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self.timer.start())
        self.search.returnPressed.connect(self.accept_current)
        self.table.doubleClicked.connect(lambda _: self.accept_current())
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.table)
        lay.addWidget(hint_label("↑/↓ to move, Enter to choose, Esc to close." +
                                 (" Ctrl+click to choose several." if multi else "")))
        self.selected: list[int] = []
        self.reload()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.search.hasFocus():
            row = max(0, min(self.table.rowCount() - 1, self.table.currentRow() +
                             (1 if e.key() == Qt.Key.Key_Down else -1)))
            self.table.selectRow(row)
            return
        super().keyPressEvent(e)

    def reload(self):
        rows = catalog.search_variants(self.ctx.db, self.search.text(), limit=200, active_only=self.active_only)
        fill_table(self.table, [[r["product_name"], r["size"], r["colour"], r["sku"], r["barcode"], r["price"],
                                 r["stock"]] for r in rows], money_cols={5}, ids=[r["variant_id"] for r in rows])
        if rows:
            self.table.selectRow(0)

    def accept_current(self):
        ids = {self.table.item(i.row(), 0).data(Qt.ItemDataRole.UserRole)
               for i in self.table.selectionModel().selectedRows()}
        if not ids:
            vid = selected_id(self.table)
            ids = {vid} if vid else set()
        if ids:
            self.selected = sorted(ids)
            self.accept()


class CustomerPicker(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Choose customer")
        self.resize(640, 460)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or phone…")
        self.table = make_table(["Name", "Phone", "Bills"])
        self.search.textChanged.connect(lambda _: self.reload())
        self.search.returnPressed.connect(self.pick)
        self.table.doubleClicked.connect(lambda _: self.pick())
        self.name, self.phone = QLineEdit(), QLineEdit()
        self.name.setPlaceholderText("New customer name")
        self.phone.setPlaceholderText("Phone (optional)")
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.table)
        lay.addLayout(hrow(button("Use Walk-in Customer", self.walkin), None,
                           button("Choose selected", self.pick, primary=True), stretch=False))
        lay.addWidget(QLabel("Add a new customer:"))
        lay.addLayout(hrow(self.name, self.phone, button("Add && choose", self.add), stretch=False))
        self.customer_id: int | None = None
        self.reload()

    def reload(self):
        rows = customers.search(self.ctx.db, self.search.text(), limit=300)
        fill_table(self.table, [[r["name"], r["phone"], r["bills"]] for r in rows], ids=[r["id"] for r in rows])
        if rows:
            self.table.selectRow(0)

    def pick(self):
        cid = selected_id(self.table)
        if cid:
            self.customer_id = cid
            self.accept()

    def walkin(self):
        self.customer_id = customers.walkin_id(self.ctx.db)
        self.accept()

    def add(self):
        cid = run_safely(self, lambda: customers.add_customer(self.ctx.db, self.name.text(), self.phone.text()),
                         "adding the customer")
        if cid:
            self.customer_id = cid
            self.accept()


class DiscountDialog(QDialog):
    """Enter a percentage or a fixed amount. Result in .type / .value (bp or paise)."""

    def __init__(self, title: str, base_paise: int, current_type: str = "NONE", current_value: int = 0,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.base = base_paise
        self.kind = QComboBox()
        self.kind.addItems(["Percentage (%)", "Amount (Rs.)", "No discount"])
        self.value = QLineEdit()
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight)
        if current_type == "PERCENT":
            self.kind.setCurrentIndex(0)
            self.value.setText(fmt_percent(current_value))
        elif current_type == "AMOUNT":
            self.kind.setCurrentIndex(1)
            self.value.setText(fmt_plain(current_value))
        form = QFormLayout(self)
        form.addRow(QLabel(f"Amount before discount: Rs. {fmt_plain(base_paise)}"))
        form.addRow("Type", self.kind)
        form.addRow("Discount", self.value)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        form.addRow(box)
        self.value.setFocus()
        self.value.selectAll()
        self.type, self.result_value = "NONE", 0

    def _ok(self):
        try:
            idx = self.kind.currentIndex()
            text = self.value.text().strip()
            if idx == 2 or text in ("", "0"):
                self.type, self.result_value = "NONE", 0
            elif idx == 0:
                self.type, self.result_value = "PERCENT", parse_percent(text, "Discount %")
            else:
                amount = parse_rupees(text, "Discount amount")
                if amount > self.base:
                    raise ValidationError("Discount cannot be more than the amount.")
                self.type, self.result_value = "AMOUNT", amount
            self.accept()
        except ValidationError as exc:
            from .common import show_error

            show_error(self, exc)


class ReasonDialog(QDialog):
    def __init__(self, title: str, prompt: str, parent=None, choices: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(prompt))
        self.combo = None
        if choices:
            self.combo = QComboBox()
            self.combo.addItems(choices)
            lay.addWidget(self.combo)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Reason / details")
        self.text.setFixedHeight(70)
        lay.addWidget(self.text)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def reason(self) -> str:
        parts = [self.combo.currentText()] if self.combo else []
        if self.text.toPlainText().strip():
            parts.append(self.text.toPlainText().strip())
        return " - ".join(parts)
