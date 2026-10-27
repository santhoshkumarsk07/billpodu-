"""Billing / POS: scan, adjust, take payment, save, print. Built for keyboard speed.

Keys: F2 scan box · F3 search · F4 customer · F5 bill discount · F6 item discount
      F7 hold · F8 resume · F9 payment · F12 or Ctrl+Enter complete · Ctrl+N new bill
      Ctrl+P print last bill again · +/- change quantity · Delete remove line
"""
from __future__ import annotations

import copy
import logging
import uuid

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ...errors import UserError, ValidationError
from ...money import fmt, fmt_percent
from ...services import catalog, customers, returns, sales
from ...services.cart import AMOUNT, NONE, PERCENT, BillDiscount, CartLine
from ...services.settings import INDIAN_STATES
from ..common import (AppContext, button, confirm, fill_table, hint_label, hrow, make_table, money_edit,
                      selected_id, show_error)
from ..dialogs import CustomerPicker, DiscountDialog, VariantSearchDialog
from .. import receipt_actions

log = logging.getLogger("mw83.pos")


class SaleDoneDialog(QDialog):
    def __init__(self, ctx: AppContext, sale_id: int, printed: bool | None, parent=None):
        super().__init__(parent)
        self.ctx, self.sale_id = ctx, sale_id
        sale = sales.get_sale(ctx.db, sale_id)
        self.setWindowTitle("Bill saved")
        lay = QVBoxLayout(self)
        ok = QLabel(f"✔ Bill {sale['invoice_no']} saved")
        ok.setObjectName("ok")
        lay.addWidget(ok)
        grid = QGridLayout()
        total = QLabel(f"Rs. {fmt(sale['total_paise'])}")
        total.setObjectName("total")
        grid.addWidget(QLabel("Total"), 0, 0)
        grid.addWidget(total, 0, 1)
        if sale["change_paise"]:
            ch = QLabel(f"Rs. {fmt(sale['change_paise'])}")
            ch.setObjectName("change")
            grid.addWidget(QLabel("Give change"), 1, 0)
            grid.addWidget(ch, 1, 1)
        lay.addLayout(grid)
        lay.addWidget(QLabel(sales.describe_payments(sale["payments"])))
        self.status = QLabel()
        lay.addWidget(self.status)
        if printed is True:
            self.status.setText("Receipt printed.")
        elif printed is False:
            self.status.setText("Receipt was NOT printed. Fix the printer and press Print.")
            self.status.setObjectName("error")
        self.print_btn = button("Print receipt  [Enter]" if printed is None else "Print again  [Enter]",
                                self.do_print, primary=True)
        pdf = button("Save as PDF", lambda: receipt_actions.save_sale_pdf(ctx, sale_id, self))
        new = button("New bill  [Esc]", self.accept)
        lay.addLayout(hrow(self.print_btn, pdf, new, stretch=False))
        self.print_btn.setDefault(True)
        self.print_btn.setFocus()

    def do_print(self):
        dup = self.print_btn.text().startswith("Print again")
        if receipt_actions.print_sale(self.ctx, self.sale_id, self, duplicate=dup):
            self.accept()
        else:
            self.status.setText("Receipt was NOT printed. The bill is saved; you can reprint later.")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(e)


class HeldBillsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Held bills")
        self.resize(560, 360)
        self.table = make_table(["Label", "Held at", "Items", "Value"])
        self.table.doubleClicked.connect(lambda _: self.pick())
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(hrow(button("Delete held bill", self.delete), None,
                           button("Resume selected  [Enter]", self.pick, primary=True), stretch=False))
        self.held_id = None
        self.reload()

    def reload(self):
        rows = sales.list_held(self.ctx.db)
        fill_table(self.table, [[r["label"], r["created_at"], r["items"], r["value"]] for r in rows],
                   money_cols={3}, ids=[r["id"] for r in rows])
        if rows:
            self.table.selectRow(0)
        self.table.setFocus()

    def pick(self):
        self.held_id = selected_id(self.table)
        if self.held_id:
            self.accept()

    def delete(self):
        hid = selected_id(self.table)
        if hid and confirm(self, "Delete held bill", "Delete this held bill? Its items will be lost.", True):
            sales.delete_held(self.ctx.db, hid)
            self.reload()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.pick()
            return
        super().keyPressEvent(e)


class PosPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.lines: list[CartLine] = []
        self.bill = BillDiscount()
        self.customer_id = customers.walkin_id(ctx.db)
        self.client_ref = uuid.uuid4().hex
        self.last_sale_id: int | None = None
        self.totals = None
        self._build()
        self._shortcuts()
        self.new_bill(confirm_first=False)

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.scan = QLineEdit()
        self.scan.setObjectName("scan")
        self.scan.setPlaceholderText("Scan barcode here (or type barcode / SKU and press Enter)   [F2]")
        self.scan.returnPressed.connect(self.on_scan)
        self.scan.installEventFilter(self)
        left.addLayout(hrow(self.scan, button("Search  [F3]", self.open_search), stretch=False))
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.hide()
        self.banner_timer = QTimer(self, singleShot=True, interval=6000, timeout=self.banner.hide)
        left.addWidget(self.banner)
        self.table = make_table(["#", "Item", "SKU", "Qty", "Price", "Discount", "Total"], stretch_col=1)
        self.table.doubleClicked.connect(self.on_double_click)
        left.addWidget(self.table, 1)
        left.addLayout(hrow(
            button("Qty +  [+]", lambda: self.change_qty(1)), button("Qty −  [-]", lambda: self.change_qty(-1)),
            button("Set qty", self.set_qty), button("Item discount  [F6]", self.item_discount),
            button("Remove item  [Del]", self.remove_line), None,
            button("Cancel bill", self.clear_bill, tip="Clears this unsaved bill after asking you"), stretch=False))
        left.addWidget(hint_label("Keys: F2 scan · F3 search · F4 customer · F5 bill discount · F6 item discount · "
                                  "F7 hold · F8 resume · F9 payment · F12 complete · Ctrl+N new bill · "
                                  "Ctrl+P reprint last bill"))
        root.addLayout(left, 3)

        right = QVBoxLayout()
        cust_box = QGroupBox("Customer")
        cl = QVBoxLayout(cust_box)
        self.cust_label = QLabel()
        cl.addLayout(hrow(self.cust_label, None, button("Change  [F4]", self.pick_customer), stretch=False))
        self.inter_state = QCheckBox("Customer from another state (IGST)")
        self.inter_state.toggled.connect(self._inter_state_changed)
        self.cust_state = QComboBox()
        self.cust_state.addItem("Choose customer's state…", "")
        for st in INDIAN_STATES:
            self.cust_state.addItem(st, st)
        cl.addWidget(self.inter_state)
        cl.addWidget(self.cust_state)
        right.addWidget(cust_box)

        disc_box = QGroupBox("Bill discount  [F5]")
        dl = QFormLayout(disc_box)
        self.bill_disc_label = QLabel("None")
        self.disc_reason = QLineEdit()
        self.disc_reason.setPlaceholderText("Reason (optional)")
        dl.addRow(self.bill_disc_label, button("Set…", self.bill_discount))
        dl.addRow("Reason", self.disc_reason)
        right.addWidget(disc_box)

        tot_box = QGroupBox("Totals")
        tl = QFormLayout(tot_box)
        self.lbl = {k: QLabel("0.00") for k in ("gross", "item_disc", "bill_disc", "tax", "round", "count")}
        for k in self.lbl.values():
            k.setAlignment(Qt.AlignmentFlag.AlignRight)
        tl.addRow("Items", self.lbl["count"])
        tl.addRow("Subtotal", self.lbl["gross"])
        tl.addRow("Item discounts", self.lbl["item_disc"])
        tl.addRow("Bill discount", self.lbl["bill_disc"])
        self.tax_title = QLabel("GST")
        tl.addRow(self.tax_title, self.lbl["tax"])
        self.round_title = QLabel("Round off")
        tl.addRow(self.round_title, self.lbl["round"])
        self.total_lbl = QLabel("0.00")
        self.total_lbl.setObjectName("total")
        self.total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        tl.addRow(QLabel("<b>PAYABLE</b>"), self.total_lbl)
        right.addWidget(tot_box)

        pay_box = QGroupBox("Payment  [F9]")
        pl = QFormLayout(pay_box)
        self.cash = money_edit("exact amount")
        self.upi = money_edit()
        self.upi_ref = QLineEdit()
        self.upi_ref.setPlaceholderText("UPI ref (optional)")
        self.card = money_edit()
        self.card_ref = QLineEdit()
        self.card_ref.setPlaceholderText("Card ref (optional)")
        self.exchange = QComboBox()
        for w in (self.cash, self.upi, self.card):
            w.textChanged.connect(lambda _: self.update_change())
            w.returnPressed.connect(self.complete)
        self.exchange.currentIndexChanged.connect(lambda _: self.update_change())
        pl.addRow("Cash received", self.cash)
        pl.addRow("UPI amount", hrow(self.upi, self.upi_ref, stretch=False))
        pl.addRow("Card amount", hrow(self.card, self.card_ref, stretch=False))
        pl.addRow("Exchange credit", self.exchange)
        self.change_lbl = QLabel()
        self.change_lbl.setObjectName("change")
        pl.addRow(self.change_lbl)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Bill note (optional)")
        self.note.setMaxLength(300)
        pl.addRow("Note", self.note)
        right.addWidget(pay_box)
        pay_hint = hint_label("Leave cash empty for exact cash. For split payment, enter the UPI/card part; "
                              "the rest is cash.")
        right.addWidget(pay_hint)

        self.complete_btn = QPushButton("COMPLETE BILL  [F12]")
        self.complete_btn.setObjectName("big")
        self.complete_btn.clicked.connect(self.complete)
        right.addWidget(self.complete_btn)
        actions = QGridLayout()
        actions.addWidget(button("Hold bill  [F7]", self.hold), 0, 0)
        actions.addWidget(button("Resume held  [F8]", self.resume), 0, 1)
        actions.addWidget(button("New bill  [Ctrl+N]", self.new_bill), 1, 0)
        actions.addWidget(button("Reprint last  [Ctrl+P]", self.reprint_last), 1, 1)
        right.addLayout(actions)
        right.addStretch(1)
        panel = QFrame()
        panel.setLayout(right)
        panel.setFixedWidth(430)
        root.addWidget(panel)

    def _shortcuts(self):
        keys = {
            "F2": self.focus_scan, "F3": self.open_search, "F4": self.pick_customer, "F5": self.bill_discount,
            "F6": self.item_discount, "F7": self.hold, "F8": self.resume, "F9": self.focus_payment,
            "F12": self.complete, "Ctrl+Return": self.complete, "Ctrl+Enter": self.complete,
            "Ctrl+N": self.new_bill, "Ctrl+P": self.reprint_last,
        }
        for seq, fn in keys.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(fn)

    def eventFilter(self, obj, event):
        if obj is self.scan and event.type() == QEvent.Type.KeyPress and not self.scan.text():
            key = event.key()
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self.change_qty(1)
                return True
            if key == Qt.Key.Key_Minus:
                self.change_qty(-1)
                return True
            if key == Qt.Key.Key_Delete:
                self.remove_line()
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.table.rowCount():
                row = self.table.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                self.table.selectRow(max(0, min(self.table.rowCount() - 1, row)))
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------- messages
    def flash(self, text: str, error: bool = True):
        self.banner.setObjectName("error" if error else "ok")
        self.banner.setStyleSheet("")  # re-apply object-name style
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.setText(text)
        self.banner.show()
        self.banner_timer.start()
        if error:
            QApplication.beep()

    def focus_scan(self):
        self.scan.setFocus()
        self.scan.selectAll()

    def focus_payment(self):
        self.cash.setFocus()
        self.cash.selectAll()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        QTimer.singleShot(0, self.focus_scan)

    def refresh(self):
        gst = self.ctx.settings.get_bool("gst_enabled")
        self.inter_state.setVisible(gst)
        self.cust_state.setVisible(gst and self.inter_state.isChecked())
        self.cash.setPlaceholderText("exact amount" if self.ctx.settings.get("default_payment") == "CASH" else "")
        self._load_exchange_credits()
        self._update_customer_label()
        self.recalc()

    def _inter_state_changed(self, checked: bool):
        self.cust_state.setVisible(checked and self.ctx.settings.get_bool("gst_enabled"))
        self.recalc()

    # ------------------------------------------------------------- cart edits
    def _apply(self, change, success_msg: str = "") -> bool:
        """Apply a change to the cart; undo it if the totals become invalid."""
        before = (copy.deepcopy(self.lines), copy.deepcopy(self.bill))
        try:
            change()
            self.totals = sales.compute_for(self.ctx.settings, self.lines, self.bill, self.inter_state.isChecked())
        except UserError as exc:
            self.lines, self.bill = before
            self.flash(exc.message)
            self.recalc()
            return False
        if success_msg:
            self.flash(success_msg, error=False)
        self.render()
        return True

    def add_variant(self, v: dict, code: str = "") -> None:
        try:
            sales.check_sellable(v, code)
        except UserError as exc:
            self.flash(exc.message)
            return
        for i, ln in enumerate(self.lines):
            if ln.variant_id == v["variant_id"]:
                if ln.qty + 1 > v["stock"]:
                    self.flash(f"Only {v['stock']} in stock for {ln.description}.")
                    return

                def inc(ln=ln):
                    ln.qty += 1
                    ln.stock = v["stock"]
                if self._apply(inc, f"{ln.description}: quantity {ln.qty + 1}"):
                    self.table.selectRow(i)
                return
        line = sales.line_from_variant(v)
        if self._apply(lambda: self.lines.append(line), f"Added {line.description} — Rs. {fmt(line.unit_price)}"):
            self.table.selectRow(len(self.lines) - 1)

    def on_scan(self):
        code = self.scan.text().strip()
        self.scan.clear()
        if not code:
            return
        try:
            v = catalog.variant_by_code(self.ctx.db, code)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "looking up the barcode")
            return
        if v is None:
            self.flash(f"Unknown barcode '{code}'. Not found as a barcode or SKU. Press F3 to search by name.")
            return
        self.add_variant(v, code)
        self.focus_scan()

    def open_search(self):
        dlg = VariantSearchDialog(self.ctx, self, self.scan.text().strip())
        self.scan.clear()
        if dlg.exec() and dlg.selected:
            self.add_variant(catalog.get_variant(self.ctx.db, dlg.selected[0]))
        self.focus_scan()

    def current_index(self) -> int:
        row = self.table.currentRow()
        if row < 0 and self.lines:
            row = len(self.lines) - 1
        return row if 0 <= row < len(self.lines) else -1

    def change_qty(self, delta: int):
        i = self.current_index()
        if i < 0:
            return
        ln = self.lines[i]
        new = ln.qty + delta
        if new < 1:
            self.flash("Quantity cannot be less than 1. Use Remove item instead.")
            return
        stock = catalog.get_variant(self.ctx.db, ln.variant_id)["stock"]
        if delta > 0 and new > stock:
            self.flash(f"Only {stock} in stock for {ln.description}.")
            return
        self._apply(lambda: setattr(ln, "qty", new))
        self.table.selectRow(i)

    def set_qty(self):
        i = self.current_index()
        if i < 0:
            return
        ln = self.lines[i]
        stock = catalog.get_variant(self.ctx.db, ln.variant_id)["stock"]
        qty, ok = QInputDialog.getInt(self, "Quantity", f"Quantity for {ln.description} (in stock: {stock})",
                                      ln.qty, 1, 9999)
        if ok:
            if qty > stock:
                self.flash(f"Only {stock} in stock for {ln.description}.")
            else:
                self._apply(lambda: setattr(ln, "qty", qty))
                self.table.selectRow(i)
        self.focus_scan()

    def remove_line(self):
        i = self.current_index()
        if i >= 0:
            name = self.lines[i].description
            self._apply(lambda: self.lines.pop(i), f"Removed {name}")
        self.focus_scan()

    def item_discount(self):
        i = self.current_index()
        if i < 0:
            self.flash("Select an item first.")
            return
        ln = self.lines[i]
        dlg = DiscountDialog(f"Discount on {ln.description}", ln.unit_price * ln.qty, ln.disc_type, ln.disc_value,
                             self)
        if dlg.exec():
            def change():
                ln.disc_type, ln.disc_value = dlg.type, dlg.result_value
            self._apply(change)
            self.table.selectRow(i)
        self.focus_scan()

    def bill_discount(self):
        if not self.lines:
            self.flash("Add items before giving a bill discount.")
            return
        base = self.totals.gross - self.totals.item_discount if self.totals else 0
        dlg = DiscountDialog("Bill discount", base, self.bill.type, self.bill.value, self)
        if dlg.exec():
            def change():
                self.bill.type, self.bill.value = dlg.type, dlg.result_value
            self._apply(change)
        self.focus_scan()

    def on_double_click(self, index):
        if index.column() == 3:
            self.set_qty()
        elif index.column() == 5:
            self.item_discount()

    def clear_bill(self):
        if self.lines and not confirm(self, "Cancel bill", "Cancel this bill and remove all items?\n"
                                                           "(Nothing has been saved yet.)", danger=True):
            return
        self.new_bill(confirm_first=False)

    def new_bill(self, confirm_first: bool = True):
        if confirm_first and self.lines and not confirm(
                self, "New bill", "The current bill has items. Start a new bill and discard them?\n"
                                  "Tip: use Hold (F7) to keep it for later.", danger=True):
            return
        self.lines = []
        self.bill = BillDiscount()
        self.customer_id = self._default_customer()
        self.client_ref = uuid.uuid4().hex
        for w in (self.cash, self.upi, self.upi_ref, self.card, self.card_ref, self.note, self.disc_reason):
            w.clear()
        self.inter_state.setChecked(False)
        self.cust_state.setCurrentIndex(0)
        self._load_exchange_credits()
        self._update_customer_label()
        self.recalc()
        self.focus_scan()

    # ------------------------------------------------------------- customer
    def _default_customer(self) -> int:
        chosen = self.ctx.settings.get("default_customer_id")
        if chosen.isdigit():
            row = self.ctx.db.one("SELECT id FROM customers WHERE id = ? AND active = 1", (int(chosen),))
            if row:
                return int(row["id"])
        return customers.walkin_id(self.ctx.db)

    def pick_customer(self):
        dlg = CustomerPicker(self.ctx, self)
        if dlg.exec() and dlg.customer_id:
            self.customer_id = dlg.customer_id
            self._update_customer_label()
        self.focus_scan()

    def _update_customer_label(self):
        try:
            c = customers.get_customer(self.ctx.db, self.customer_id)
        except UserError:
            self.customer_id = customers.walkin_id(self.ctx.db)
            c = customers.get_customer(self.ctx.db, self.customer_id)
        self.cust_label.setText(f"<b>{c['name']}</b>" + (f"  ({c['phone']})" if c["phone"] else ""))

    def _load_exchange_credits(self):
        self.exchange.blockSignals(True)
        self.exchange.clear()
        self.exchange.addItem("None", None)
        for r in returns.open_exchange_credits(self.ctx.db):
            self.exchange.addItem(f"{r['return_no']} (bill {r['invoice_no']}) — Rs. {fmt(r['refund_paise'])}",
                                  (r["id"], r["refund_paise"]))
        self.exchange.blockSignals(False)

    # ------------------------------------------------------------- display
    def recalc(self):
        try:
            self.totals = sales.compute_for(self.ctx.settings, self.lines, self.bill, self.inter_state.isChecked())
        except UserError as exc:
            # e.g. the discount limit was lowered in Settings; drop the bill discount
            self.flash(exc.message)
            self.bill = BillDiscount()
            for ln in self.lines:
                ln.disc_type, ln.disc_value = NONE, 0
            self.totals = sales.compute_for(self.ctx.settings, self.lines, self.bill, self.inter_state.isChecked())
        self.render()

    def render(self):
        t = self.totals
        rows = []
        for n, (ln, r) in enumerate(zip(self.lines, t.lines, strict=True), start=1):
            disc = ""
            if r.item_discount:
                disc = (f"{fmt_percent(ln.disc_value)}% = " if ln.disc_type == PERCENT else "") + fmt(r.item_discount)
            rows.append([n, ln.description, ln.sku, ln.qty, ln.unit_price, disc, r.gross - r.item_discount])
        cur = self.table.currentRow()
        fill_table(self.table, rows, money_cols={4, 6}, right_cols={3, 5})
        if rows:
            self.table.selectRow(min(max(cur, 0), len(rows) - 1))
        gst = self.ctx.settings.get_bool("gst_enabled")
        self.lbl["count"].setText(str(t.item_count))
        self.lbl["gross"].setText(fmt(t.gross))
        self.lbl["item_disc"].setText("-" + fmt(t.item_discount) if t.item_discount else "0.00")
        self.lbl["bill_disc"].setText("-" + fmt(t.bill_discount) if t.bill_discount else "0.00")
        if gst:
            incl = self.ctx.settings.get_bool("prices_include_tax")
            kind = "IGST" if self.inter_state.isChecked() else "CGST+SGST"
            self.tax_title.setText(f"{kind} ({'included' if incl else 'added'})")
        else:
            self.tax_title.setText("GST (off)")
        self.lbl["tax"].setText(fmt(t.tax))
        self.round_title.setVisible(bool(t.round_off))
        self.lbl["round"].setVisible(bool(t.round_off))
        self.lbl["round"].setText(fmt(t.round_off))
        self.total_lbl.setText(fmt(t.total))
        if self.bill.type == PERCENT:
            self.bill_disc_label.setText(f"{fmt_percent(self.bill.value)}% = Rs. {fmt(t.bill_discount)}")
        elif self.bill.type == AMOUNT:
            self.bill_disc_label.setText(f"Rs. {fmt(t.bill_discount)}")
        else:
            self.bill_disc_label.setText("None")
        self.complete_btn.setEnabled(bool(self.lines))
        self.update_change()

    def _payment_values(self) -> dict:
        """Read payment boxes. Empty cash means 'exact cash for whatever is left'."""
        from ..common import money_text

        total = self.totals.total if self.totals else 0
        upi = money_text(self.upi, "UPI amount")
        card = money_text(self.card, "Card amount")
        ex = self.exchange.currentData()
        exchange = ex[1] if ex else 0
        if self.cash.text().strip() == "":
            if not upi and not card and not exchange:
                default = self.ctx.settings.get("default_payment")
                if default == "UPI":
                    upi = total
                elif default == "CARD":
                    card = total
            cash = max(0, total - upi - card - exchange)
        else:
            cash = money_text(self.cash, "Cash received")
        return {"upi": upi, "card": card, "cash": cash, "exchange": exchange, "exchange_id": ex[0] if ex else None}

    def update_change(self):
        if not self.totals or not self.lines:
            self.change_lbl.setText("")
            return
        try:
            p = self._payment_values()
            st = sales.cartmod.settle(self.totals.total, upi=p["upi"], card=p["card"], exchange=p["exchange"],
                                      cash_received=p["cash"])
            self.change_lbl.setText(f"Change due: Rs. {fmt(st.change)}" if st.change else "No change due")
            self.change_lbl.setStyleSheet("")
        except UserError as exc:
            self.change_lbl.setText(exc.message)
            self.change_lbl.setStyleSheet("color:#b91c1c; font-size:10.5pt;")

    # ------------------------------------------------------------- hold / resume
    def _state(self) -> dict:
        return {"lines": [ln.to_dict() for ln in self.lines], "bill": vars(self.bill).copy(),
                "customer_id": self.customer_id, "note": self.note.text(), "reason": self.disc_reason.text(),
                "inter_state": self.inter_state.isChecked(), "customer_state": self.cust_state.currentData() or ""}

    def hold(self):
        if not self.lines:
            self.flash("There is nothing to hold. The bill is empty.")
            return
        label, ok = QInputDialog.getText(self, "Hold bill", "Name for this held bill (e.g. customer name):")
        if not ok:
            return
        try:
            sales.hold_bill(self.ctx.db, label, self._state())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "holding the bill")
            return
        self.new_bill(confirm_first=False)
        self.flash("Bill held. Press F8 to resume it.", error=False)

    def resume(self):
        if not sales.list_held(self.ctx.db):
            self.flash("There are no held bills.")
            return
        dlg = HeldBillsDialog(self.ctx, self)
        if not dlg.exec() or not dlg.held_id:
            self.focus_scan()
            return
        if self.lines:
            if not confirm(self, "Resume bill", "Hold the current bill first and then resume the selected one?"):
                return
            sales.hold_bill(self.ctx.db, "Auto-held", self._state())
        try:
            state = sales.resume_held(self.ctx.db, dlg.held_id)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "resuming the bill")
            return
        self.new_bill(confirm_first=False)
        dropped = []
        for d in state.get("lines", []):
            try:
                ln = CartLine.from_dict(d)
                v = catalog.get_variant(self.ctx.db, ln.variant_id)
                ln.stock = v["stock"]
                if not (v["variant_active"] and v["product_active"]):
                    raise ValidationError("archived")
                self.lines.append(ln)
            except (UserError, TypeError, KeyError, ValueError):
                dropped.append(d.get("product_name", "item") if isinstance(d, dict) else "item")
        b = state.get("bill") or {}
        self.bill = BillDiscount(b.get("type", NONE), int(b.get("value", 0)), b.get("reason", ""))
        cid = state.get("customer_id")
        if cid:
            self.customer_id = cid
        self.note.setText(state.get("note", ""))
        self.disc_reason.setText(state.get("reason", ""))
        self.inter_state.setChecked(bool(state.get("inter_state")))
        idx = self.cust_state.findData(state.get("customer_state", ""))
        self.cust_state.setCurrentIndex(max(0, idx))
        self._update_customer_label()
        self.recalc()
        if dropped:
            self.flash("Some items are no longer available and were removed: " + ", ".join(dropped))
        self.focus_scan()

    # ------------------------------------------------------------- complete
    def complete(self):
        if not self.isVisible():
            return
        if not self.lines:
            self.flash("The bill is empty. Scan an item first.")
            return
        try:
            p = self._payment_values()
            req = sales.SaleRequest(
                lines=self.lines, bill_discount=BillDiscount(self.bill.type, self.bill.value,
                                                             self.disc_reason.text()),
                customer_id=self.customer_id,
                payment=sales.PaymentInput(upi=p["upi"], card=p["card"], cash_received=p["cash"],
                                           upi_ref=self.upi_ref.text(), card_ref=self.card_ref.text(),
                                           exchange_return_id=p["exchange_id"]),
                note=self.note.text(), inter_state=self.inter_state.isChecked(),
                customer_state=self.cust_state.currentData() or "", client_ref=self.client_ref)
            self.complete_btn.setEnabled(False)
            QApplication.processEvents()
            sale_id = sales.complete_sale(self.ctx.db, self.ctx.settings, req)
        except Exception as exc:  # noqa: BLE001
            self.complete_btn.setEnabled(True)
            show_error(self, exc, "saving the bill")
            return
        # The sale is committed. From here on nothing can duplicate it.
        self.last_sale_id = sale_id
        log.info("sale %s saved", sale_id)
        self.new_bill(confirm_first=False)
        printed = None
        if self.ctx.settings.get_bool("auto_print_receipt"):
            printed = receipt_actions.print_sale(self.ctx, sale_id, self, quiet=True)
        SaleDoneDialog(self.ctx, sale_id, printed, self).exec()
        self.focus_scan()

    def reprint_last(self):
        if not self.isVisible():
            return
        if not self.last_sale_id:
            rows = sales.search_sales(self.ctx.db, limit=1)
            if not rows:
                self.flash("No bills yet.")
                return
            self.last_sale_id = rows[0]["id"]
        sale = sales.get_sale(self.ctx.db, self.last_sale_id)
        if confirm(self, "Reprint", f"Print a duplicate receipt for bill {sale['invoice_no']} "
                                    f"(Rs. {fmt(sale['total_paise'])})?"):
            if receipt_actions.print_sale(self.ctx, self.last_sale_id, self, duplicate=True):
                self.flash(f"Duplicate receipt printed for {sale['invoice_no']}.", error=False)
        self.focus_scan()
