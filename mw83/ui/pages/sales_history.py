"""Find old bills, view, reprint, PDF, cancel (with reversal) or start a return."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget)

from ...money import fmt, fmt_percent
from ...services import sales
from .. import receipt_actions
from ..common import (AppContext, DateRange, button, confirm, fill_table, hint_label, hrow, make_table, selected_id,
                      show_error, title_label)
from ..dialogs import ReasonDialog


class SaleViewDialog(QDialog):
    def __init__(self, ctx: AppContext, sale_id: int, parent=None, start_return=None):
        super().__init__(parent)
        self.ctx, self.sale_id, self.start_return = ctx, sale_id, start_return
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setWordWrap(True)
        lay.addWidget(self.header)
        self.items = make_table(["Item", "Size", "Colour", "SKU", "Qty", "Rate", "Discount", "GST %", "Total",
                                 "Returned"], stretch_col=0)
        lay.addWidget(self.items, 1)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(QLabel("Receipt preview:"))
        lay.addWidget(self.text, 1)
        self.cancel_btn = button("Cancel bill…", self.cancel_bill)
        self.cancel_btn.setObjectName("danger")
        self.return_btn = button("Return / exchange…", self.do_return)
        lay.addLayout(hrow(button("Reprint receipt", self.reprint, primary=True),
                           button("Save PDF", lambda: receipt_actions.save_sale_pdf(ctx, sale_id, self)),
                           self.return_btn, self.cancel_btn, None, button("Close", self.accept), stretch=False))
        lay.addWidget(hint_label("Completed bills cannot be edited. To undo a bill, cancel it (stock comes back and "
                                 "the cancellation is recorded) or make a return."))
        self.load()

    def load(self):
        s = sales.get_sale(self.ctx.db, self.sale_id)
        self.setWindowTitle(f"Bill {s['invoice_no']}")
        cust = s["customer_name"] or "Walk-in Customer"
        status = s["status"].title()
        extra = ""
        if s["cancellation"]:
            extra = f"<br><b style='color:#b91c1c'>Cancelled {s['cancellation']['created_at']}: " \
                    f"{s['cancellation']['reason']}</b>"
        if s["returns"]:
            extra += "<br>Returns: " + ", ".join(f"{r['return_no']} (Rs. {fmt(r['refund_paise'])}, "
                                                 f"{r['refund_method'].lower()})" for r in s["returns"])
        self.header.setText(f"<b>{s['invoice_no']}</b> · {s['created_at']} · {cust} · <b>Rs. {fmt(s['total_paise'])}"
                            f"</b> · {sales.describe_payments(s['payments'])} · Status: <b>{status}</b>{extra}")
        fill_table(self.items, [[i["product_name"], i["size"], i["colour"], i["sku"], i["qty"], i["unit_price_paise"],
                                 i["item_discount_paise"] + i["bill_discount_paise"],
                                 fmt_percent(i["gst_rate_bp"]) if s["gst_enabled"] else "-", i["line_total_paise"],
                                 i["returned_qty"]] for i in s["items"]], money_cols={5, 6, 8})
        _, lines = receipt_actions.receipt_lines(self.ctx, self.sale_id, duplicate=True)
        self.text.setPlainText("\n".join(ln.text for ln in lines))
        active = s["status"] == "COMPLETED"
        self.cancel_btn.setEnabled(active and not s["returns"])
        self.return_btn.setEnabled(active and any(i["returned_qty"] < i["qty"] for i in s["items"]))

    def reprint(self):
        receipt_actions.print_sale(self.ctx, self.sale_id, self, duplicate=True)

    def cancel_bill(self):
        s = sales.get_sale(self.ctx.db, self.sale_id)
        dlg = ReasonDialog("Cancel bill", f"Cancel bill {s['invoice_no']} (Rs. {fmt(s['total_paise'])})?\n"
                                          "Stock will be added back. The bill stays in history as CANCELLED.\n"
                                          "Refund the customer yourself.", self,
                           ["Billing mistake", "Customer cancelled", "Duplicate bill", "Other"])
        if not dlg.exec():
            return
        if not confirm(self, "Confirm cancellation", f"Really cancel bill {s['invoice_no']}? This cannot be undone.",
                       danger=True):
            return
        try:
            sales.cancel_sale(self.ctx.db, self.sale_id, dlg.reason())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "cancelling the bill")
            return
        self.load()

    def do_return(self):
        if self.start_return:
            self.accept()
            self.start_return(self.sale_id)


class SalesHistoryPage(QWidget):
    def __init__(self, ctx: AppContext, start_return=None):
        super().__init__()
        self.setObjectName("page")
        self.ctx, self.start_return = ctx, start_return
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Sales History"))
        self.range = DateRange(days_back=0)
        self.range.changed.connect(self.reload)
        self.invoice, self.customer, self.product, self.code = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        for w, ph in ((self.invoice, "Bill no."), (self.customer, "Customer name/phone"),
                      (self.product, "Product name"), (self.code, "Barcode / SKU")):
            w.setPlaceholderText(ph)
            w.returnPressed.connect(self.reload)
        self.method = QComboBox()
        for label, code in (("Any payment", ""), ("Cash", "CASH"), ("UPI", "UPI"), ("Card", "CARD"),
                            ("Exchange", "EXCHANGE")):
            self.method.addItem(label, code)
        self.status = QComboBox()
        for label, code in (("Any status", ""), ("Completed", "COMPLETED"), ("Cancelled", "CANCELLED")):
            self.status.addItem(label, code)
        lay.addLayout(hrow(self.range, stretch=True))
        lay.addLayout(hrow(self.invoice, self.customer, self.product, self.code, self.method, self.status,
                           button("Search", self.reload, primary=True), stretch=False))
        self.table = make_table(["Bill", "Date/time", "Customer", "Items", "Discount", "Tax", "Total", "Payment",
                                 "Status"])
        self.table.doubleClicked.connect(lambda _: self.view())
        lay.addWidget(self.table, 1)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        lay.addLayout(hrow(button("View bill", self.view), button("Reprint", self.reprint),
                           button("Save PDF", self.pdf), button("Return / exchange", self.ret)))

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        a, b = self.range.values()
        if self.invoice.text().strip():
            a, b = "", ""  # an exact bill search ignores dates
        rows = sales.search_sales(self.ctx.db, self.invoice.text(), a, b, self.customer.text(), self.product.text(),
                                  self.code.text(), self.method.currentData(), self.status.currentData())
        fill_table(self.table, [[r["invoice_no"], r["created_at"], r["customer"], r["items"], r["discount_paise"],
                                 r["tax_paise"], r["total_paise"], r["methods"] or "-",
                                 r["status"].title() + (" (returns)" if r["return_count"] else "")] for r in rows],
                   money_cols={4, 5, 6}, ids=[r["id"] for r in rows])
        done = [r for r in rows if r["status"] == "COMPLETED"]
        self.summary.setText(f"{len(rows)} bill(s) shown · completed total Rs. "
                             f"{fmt(sum(r['total_paise'] for r in done))}" + (" (max 1000 shown)" if len(rows) >= 1000
                                                                                  else ""))

    def open_sale(self, sale_id: int):
        SaleViewDialog(self.ctx, sale_id, self, self.start_return).exec()
        if self.isVisible():
            self.reload()

    def view(self):
        sid = selected_id(self.table)
        if sid:
            self.open_sale(sid)

    def reprint(self):
        sid = selected_id(self.table)
        if sid:
            receipt_actions.print_sale(self.ctx, sid, self, duplicate=True)

    def pdf(self):
        sid = selected_id(self.table)
        if sid:
            receipt_actions.save_sale_pdf(self.ctx, sid, self)

    def ret(self):
        sid = selected_id(self.table)
        if sid and self.start_return:
            self.start_return(sid)
