"""Stock per size/colour, receiving stock, adjustments and the full movement history."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QRadioButton,
                               QTabWidget, QVBoxLayout, QWidget)

from ...errors import ValidationError
from ...money import fmt
from ...services import catalog, inventory
from ...services.inventory import MOVEMENT_LABELS
from ..common import (AppContext, DateRange, button, confirm, fill_table, hint_label, hrow, int_edit, make_table,
                      run_safely, selected_id, show_error, title_label)


class StockChangeDialog(QDialog):
    def __init__(self, ctx: AppContext, variant: dict, receive: bool, parent=None):
        super().__init__(parent)
        self.ctx, self.v, self.receive = ctx, variant, receive
        name = variant["product_name"] + (f" ({' / '.join(x for x in (variant['size'], variant['colour']) if x)})"
                                          if variant["size"] or variant["colour"] else "")
        self.setWindowTitle("Receive stock" if receive else "Adjust stock")
        form = QFormLayout(self)
        form.addRow(QLabel(f"<b>{name}</b><br>SKU {variant['sku']} · Current stock: <b>{variant['stock']}</b>"))
        self.kind = QComboBox()
        if not receive:
            self.kind.addItem("Damaged (remove)", "DAMAGED")
            self.kind.addItem("Lost / missing (remove)", "LOST")
            self.kind.addItem("Manual adjustment / recount", "ADJUSTMENT")
            form.addRow("Type", self.kind)
            self.by_delta = QRadioButton("Change by quantity")
            self.by_count = QRadioButton("Set to counted quantity")
            self.by_delta.setChecked(True)
            form.addRow(hrow(self.by_delta, self.by_count))
            self.kind.currentIndexChanged.connect(self._mode)
        self.qty = int_edit("e.g. 5", allow_negative=not receive)
        form.addRow("Quantity", self.qty)
        self.reason = QLineEdit()
        self.reason.setMaxLength(200)
        self.reason.setPlaceholderText("Supplier / bill no. (optional)" if receive else "Reason (required)")
        form.addRow("Supplier / note" if receive else "Reason", self.reason)
        if not receive:
            form.addRow(hint_label("Damaged and Lost always reduce stock. For Adjustment, use a negative number "
                                   "to reduce (e.g. -2) or set the counted quantity."))
            self._mode()
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _mode(self):
        adj = self.kind.currentData() == "ADJUSTMENT"
        self.by_count.setEnabled(adj)
        if not adj:
            self.by_delta.setChecked(True)

    def save(self):
        try:
            text = self.qty.text().strip()
            if not text or text == "-":
                raise ValidationError("Enter a quantity.")
            n = int(text)
            if self.receive:
                if n <= 0:
                    raise ValidationError("Quantity received must be 1 or more.")
                if not confirm(self, "Receive stock", f"Add {n} to stock?"):
                    return
                inventory.receive_stock(self.ctx.db, self.v["variant_id"], n, self.reason.text())
            else:
                kind = self.kind.currentData()
                if self.by_count.isChecked():
                    if n < 0:
                        raise ValidationError("Counted quantity cannot be negative.")
                    delta = n - self.v["stock"]
                    if delta == 0:
                        raise ValidationError("The counted quantity is the same as the current stock.")
                else:
                    delta = -abs(n) if kind in ("DAMAGED", "LOST") else n
                if not self.reason.text().strip():
                    raise ValidationError("Please enter a reason for this stock change.")
                new = self.v["stock"] + delta
                large = abs(delta) >= self.ctx.settings.get_int("large_adjustment_qty")
                msg = (f"{MOVEMENT_LABELS[kind]}: change stock by {delta:+d}\n"
                       f"from {self.v['stock']} to {new}.\n\nReason: {self.reason.text().strip()}")
                if large:
                    msg = "⚠ This is a LARGE stock change.\n\n" + msg
                if (self.ctx.settings.get_bool("confirm_adjustments") or large) and not confirm(
                        self, "Confirm stock change", msg, danger=large):
                    return
                inventory.adjust_stock(self.ctx.db, self.v["variant_id"], kind, delta, self.reason.text())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "changing stock")
            return
        self.accept()


class InventoryPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Inventory"))
        self.value_lbl = QLabel()
        lay.addWidget(self.value_lbl)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        stock = QWidget()
        sl = QVBoxLayout(stock)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, SKU, barcode…")
        self.status = QComboBox()
        self.status.addItem("All stock", "ALL")
        self.status.addItem("Low stock", "LOW")
        self.status.addItem("Out of stock", "OUT")
        self.category = QComboBox()
        self.timer = QTimer(self, singleShot=True, interval=200, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self.timer.start())
        self.status.currentIndexChanged.connect(lambda _: self.reload())
        self.category.currentIndexChanged.connect(lambda _: self.reload())
        sl.addLayout(hrow(self.search, self.status, QLabel("Category"), self.category, stretch=False))
        self.table = make_table(["Product", "Size", "Colour", "SKU", "Barcode", "Stock", "Low at", "Cost", "Price",
                                 "Stock value (cost)"])
        sl.addWidget(self.table, 1)
        sl.addLayout(hrow(button("Receive stock…", self.receive, primary=True),
                          button("Damaged / lost / adjust…", self.adjust),
                          button("History of selected", self.history_of_selected)))
        tabs.addTab(stock, "Current stock")

        hist = QWidget()
        hl = QVBoxLayout(hist)
        self.range = DateRange(days_back=30)
        self.mtype = QComboBox()
        self.mtype.addItem("All types", "")
        for k, label in MOVEMENT_LABELS.items():
            self.mtype.addItem(label, k)
        self.hsearch = QLineEdit()
        self.hsearch.setPlaceholderText("Product, SKU, barcode or bill no.")
        self.variant_filter: int | None = None
        self.vf_label = QLabel()
        hl.addLayout(hrow(self.range, self.mtype, self.hsearch, button("Show", self.reload_history), stretch=False))
        hl.addLayout(hrow(self.vf_label, button("Clear item filter", self.clear_variant_filter)))
        self.htable = make_table(["Date/time", "Product", "Size", "Colour", "SKU", "Type", "Change", "New stock",
                                  "Reference", "Reason"])
        hl.addWidget(self.htable, 1)
        tabs.addTab(hist, "Stock movement history")
        self.tabs = tabs
        tabs.currentChanged.connect(lambda i: self.reload_history() if i == 1 else None)

    def showEvent(self, e):
        super().showEvent(e)
        cur = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All", None)
        for c in catalog.list_categories(self.ctx.db):
            self.category.addItem(c["name"], c["id"])
        self.category.setCurrentIndex(max(0, self.category.findData(cur)))
        self.category.blockSignals(False)
        self.reload()

    def reload(self):
        dm = self.ctx.settings.get_int("default_min_stock")
        rows = inventory.stock_list(self.ctx.db, self.search.text(), self.category.currentData(),
                                    self.status.currentData(), dm)
        fill_table(self.table, [[r["name"], r["size"], r["colour"], r["sku"], r["barcode"], r["stock"],
                                 r["min_stock"], r["cost"], r["price"], r["stock"] * r["cost"]] for r in rows],
                   money_cols={7, 8, 9}, ids=[r["variant_id"] for r in rows])
        val = inventory.stock_value(self.ctx.db)
        low = inventory.low_stock_count(self.ctx.db, dm)
        self.value_lbl.setText(f"<b>{val['units']}</b> pieces in stock · value at cost <b>Rs. {fmt(val['cost_value'])}"
                               f"</b> · at selling price <b>Rs. {fmt(val['sale_value'])}</b> · "
                               f"<b>{low}</b> item(s) low or out of stock")

    def _selected_variant(self):
        vid = selected_id(self.table)
        if not vid:
            return None
        return catalog.get_variant(self.ctx.db, vid)

    def receive(self):
        v = self._selected_variant()
        if v and StockChangeDialog(self.ctx, v, True, self).exec():
            self.reload()

    def adjust(self):
        v = self._selected_variant()
        if v and StockChangeDialog(self.ctx, v, False, self).exec():
            self.reload()

    def history_of_selected(self):
        v = self._selected_variant()
        if not v:
            return
        self.variant_filter = v["variant_id"]
        self.vf_label.setText(f"Showing only: {v['product_name']} {v['size']} {v['colour']} ({v['sku']})")
        self.range.start.setDate(self.range.start.date().addYears(-20))
        self.tabs.setCurrentIndex(1)
        self.reload_history()

    def clear_variant_filter(self):
        self.variant_filter = None
        self.vf_label.setText("")
        self.reload_history()

    def reload_history(self):
        a, b = self.range.values()
        rows = run_safely(self, lambda: inventory.movements(self.ctx.db, self.variant_filter, a, b,
                                                            self.mtype.currentData(), self.hsearch.text()))
        if rows is None:
            return
        fill_table(self.htable, [[r["created_at"], r["name"], r["size"], r["colour"], r["sku"],
                                  MOVEMENT_LABELS.get(r["movement_type"], r["movement_type"]),
                                  f"{r['qty_change']:+d}", r["balance_after"], r["ref_text"], r["reason"]]
                                 for r in rows], right_cols={6})
