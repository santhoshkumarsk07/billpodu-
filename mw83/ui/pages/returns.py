"""Returns and exchanges against an original bill."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QSpinBox,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...errors import ValidationError
from ...money import fmt
from ...services import returns, sales
from ...services.returns import RETURN_REASONS, ReturnLine
from ..common import (AppContext, DateRange, button, confirm, fill_table, hint_label, hrow, info, make_table,
                      show_error, title_label)


class ReturnsPage(QWidget):
    def __init__(self, ctx: AppContext, go_to=None):
        super().__init__()
        self.setObjectName("page")
        self.ctx, self.go_to = ctx, go_to
        self.sale = None
        self.items: list[dict] = []
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Returns & Exchanges"))
        self.invoice = QLineEdit()
        self.invoice.setPlaceholderText("Original bill number, e.g. 83MW-0012 (or scan it)")
        self.invoice.returnPressed.connect(self.find)
        lay.addLayout(hrow(QLabel("1. Find the bill:"), self.invoice, button("Find", self.find, primary=True),
                           stretch=False))
        self.bill_lbl = QLabel()
        lay.addWidget(self.bill_lbl)
        lay.addWidget(QLabel("2. Enter the quantity being returned. Untick 'Sellable' for damaged items "
                             "(they will not go back into stock)."))
        self.table = make_table(["Item", "Size", "Colour", "Sold", "Already returned", "Return qty", "Sellable"],
                                stretch_col=0)
        lay.addWidget(self.table, 1)
        box = QGroupBox("3. Reason and refund")
        f = QFormLayout(box)
        self.reason = QComboBox()
        self.reason.addItems(RETURN_REASONS)
        self.details = QLineEdit()
        self.details.setPlaceholderText("Details (optional)")
        self.method = QComboBox()
        for label, code in (("Cash refund", "CASH"), ("UPI refund", "UPI"), ("Card refund", "CARD"),
                            ("Exchange (credit for a new bill)", "EXCHANGE")):
            self.method.addItem(label, code)
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("UPI/card reference (optional)")
        self.refund_lbl = QLabel()
        self.refund_lbl.setObjectName("change")
        f.addRow("Reason", hrow(self.reason, self.details, stretch=False))
        f.addRow("Refund as", hrow(self.method, self.ref, stretch=False))
        f.addRow("Refund amount", self.refund_lbl)
        lay.addWidget(box)
        lay.addLayout(hrow(button("Save return", self.save, primary=True), button("Clear", self.reset)))
        lay.addWidget(hint_label("Refund amount includes the discounts and GST of the original bill. For an exchange, "
                                 "save the return, then go to Billing and choose the credit under Payment → "
                                 "Exchange credit."))
        recent = QGroupBox("Recent returns")
        rl = QVBoxLayout(recent)
        self.range = DateRange(days_back=30)
        self.range.changed.connect(self.load_recent)
        rl.addWidget(self.range)
        self.recent = make_table(["Return no", "Date/time", "Bill", "Items", "Refund", "Via", "Reason",
                                  "Exchanged on bill"])
        rl.addWidget(self.recent)
        lay.addWidget(recent, 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.load_recent()

    def load_recent(self):
        a, b = self.range.values()
        rows = returns.list_returns(self.ctx.db, a, b)
        fill_table(self.recent, [[r["return_no"], r["created_at"], r["invoice_no"], r["items"], r["refund_paise"],
                                  r["refund_method"], r["reason"], r["exchange_invoice"] or ""] for r in rows],
                   money_cols={4})

    def load_sale(self, sale_id: int):
        self.reset()
        self.sale = sales.get_sale(self.ctx.db, sale_id)
        self.invoice.setText(self.sale["invoice_no"])
        self._show()

    def find(self):
        sid = sales.sale_id_by_invoice(self.ctx.db, self.invoice.text())
        if not sid:
            show_error(self, ValidationError(f"No bill found with number '{self.invoice.text().strip()}'."))
            return
        self.load_sale(sid)

    def _show(self):
        s = self.sale
        self.items = returns.returnable_items(self.ctx.db, s["id"])
        self.bill_lbl.setText(f"Bill <b>{s['invoice_no']}</b> · {s['created_at']} · "
                              f"{s['customer_name'] or 'Walk-in'} · Rs. {fmt(s['total_paise'])} · "
                              f"<b>{s['status'].title()}</b>")
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            for c, v in enumerate([it["product_name"], it["size"], it["colour"], it["qty"], it["returned"]]):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
            spin = QSpinBox()
            spin.setRange(0, max(0, it["remaining"]))
            spin.setEnabled(it["remaining"] > 0 and s["status"] == "COMPLETED")
            spin.valueChanged.connect(lambda _: self.update_refund())
            self.table.setCellWidget(r, 5, spin)
            chk = QCheckBox()
            chk.setChecked(True)
            self.table.setCellWidget(r, 6, chk)
        if s["status"] != "COMPLETED":
            self.refund_lbl.setText("This bill is cancelled; nothing can be returned.")
        else:
            self.update_refund()

    def _lines(self) -> list[ReturnLine]:
        out = []
        for r, it in enumerate(self.items):
            qty = self.table.cellWidget(r, 5).value()
            if qty:
                out.append(ReturnLine(it["sale_item_id"], qty, self.table.cellWidget(r, 6).isChecked()))
        return out

    def update_refund(self):
        total = 0
        for r, it in enumerate(self.items):
            qty = self.table.cellWidget(r, 5).value()
            if qty:
                total += returns.refund_share(it["line_total_paise"], it["qty"], it["returned"], qty)
        self.refund_lbl.setText(f"Rs. {fmt(total)}")
        return total

    def reset(self):
        self.sale = None
        self.items = []
        self.table.setRowCount(0)
        self.bill_lbl.setText("")
        self.refund_lbl.setText("")
        self.details.clear()
        self.ref.clear()

    def save(self):
        if not self.sale:
            show_error(self, ValidationError("Find the original bill first."))
            return
        lines = self._lines()
        if not lines:
            show_error(self, ValidationError("Enter the quantity being returned."))
            return
        method = self.method.currentData()
        amount = self.update_refund()
        not_sellable = sum(ln.qty for ln in lines if not ln.restock)
        msg = (f"Save return against bill {self.sale['invoice_no']}?\n\n"
               f"Items: {sum(ln.qty for ln in lines)}   Refund: Rs. {fmt(amount)} by {self.method.currentText()}")
        if not_sellable:
            msg += f"\n{not_sellable} damaged item(s) will NOT go back into stock."
        if not confirm(self, "Save return", msg):
            return
        reason = self.reason.currentText() + (f" - {self.details.text().strip()}" if self.details.text().strip() else "")
        try:
            rid = returns.create_return(self.ctx.db, self.ctx.settings, self.sale["id"], lines, reason, method,
                                        self.ref.text())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "saving the return")
            return
        r = returns.get_return(self.ctx.db, rid)
        if method == "EXCHANGE":
            info(self, "Return saved", f"Return {r['return_no']} saved. Exchange credit Rs. {fmt(r['refund_paise'])}.\n\n"
                                       "Now go to Billing, scan the replacement items, and choose this credit under "
                                       "Payment → Exchange credit.")
            if self.go_to:
                self.go_to("Billing / POS")
        else:
            info(self, "Return saved", f"Return {r['return_no']} saved.\nGive the customer Rs. {fmt(r['refund_paise'])}"
                                       f" by {method.title()}.")
        self.reset()
        self.invoice.clear()
        self.load_recent()
