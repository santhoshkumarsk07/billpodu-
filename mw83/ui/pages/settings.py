"""Shop, billing, GST, printer, inventory and backup settings."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ...errors import ValidationError
from ...money import fmt_percent, fmt_plain, parse_percent, parse_rupees
from ...printing import printers
from ...printing.receipt import WIDTH_CHARS, build_test_receipt
from ...services import backup, customers
from ...services.settings import INDIAN_STATES
from ..common import (AppContext, button, hint_label, hrow, info, money_edit, percent_edit, show_error,
                      title_label)


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Settings"))
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)
        lay.addLayout(hrow(None, button("Save settings", self.save, primary=True), stretch=False))

        # shop
        shop = QWidget()
        f = QFormLayout(shop)
        self.shop_name = QLineEdit()
        self.shop_address = QPlainTextEdit()
        self.shop_address.setFixedHeight(70)
        self.shop_phone = QLineEdit()
        self.shop_gstin = QLineEdit()
        self.shop_gstin.setMaxLength(15)
        self.invoice_prefix = QLineEdit()
        self.invoice_prefix.setMaxLength(12)
        self.financial_year = QLineEdit()
        self.financial_year.setPlaceholderText("optional, e.g. 2026-27 (adds it to bill numbers)")
        self.footer = QLineEdit()
        self.policy = QLineEdit()
        self.policy.setPlaceholderText("e.g. Exchange within 7 days with bill and tags")
        f.addRow("Shop name", self.shop_name)
        f.addRow("Address", self.shop_address)
        f.addRow("Phone", self.shop_phone)
        f.addRow("GSTIN", self.shop_gstin)
        f.addRow("Invoice prefix", self.invoice_prefix)
        f.addRow("Financial year", self.financial_year)
        f.addRow("Receipt thank-you line", self.footer)
        f.addRow("Return policy line", self.policy)
        f.addRow(hint_label("Bill numbers look like 83MW-0001 and are never reused. Changing the prefix or financial "
                            "year starts a new series."))
        tabs.addTab(shop, "Shop")

        # billing & GST
        bill = QWidget()
        f = QFormLayout(bill)
        self.default_payment = QComboBox()
        for label, code in (("Cash", "CASH"), ("UPI", "UPI"), ("Card", "CARD")):
            self.default_payment.addItem(label, code)
        self.default_customer = QComboBox()
        self.max_disc = percent_edit()
        self.auto_print = QCheckBox("Print the receipt automatically when a bill is completed")
        self.round_off = QCheckBox("Round bill total to the nearest rupee")
        f.addRow("Default payment method", self.default_payment)
        f.addRow("Default customer on new bills", self.default_customer)
        f.addRow("Maximum discount on a bill (%)", self.max_disc)
        f.addRow(self.auto_print)
        f.addRow(self.round_off)
        f.addRow(QLabel("<b>GST</b>"))
        self.gst_enabled = QCheckBox("My shop is GST-registered — calculate GST on bills")
        self.shop_state = QComboBox()
        self.shop_state.addItems([""] + INDIAN_STATES)
        self.inclusive = QComboBox()
        self.inclusive.addItem("Prices include GST (MRP-style)", "1")
        self.inclusive.addItem("GST is added on top of prices", "0")
        self.default_rate = percent_edit()
        self.slab_threshold = money_edit()
        self.slab_low, self.slab_high = percent_edit(), percent_edit()
        f.addRow(self.gst_enabled)
        f.addRow("Shop state", self.shop_state)
        f.addRow("Pricing", self.inclusive)
        f.addRow("Default GST rate (%)", self.default_rate)
        f.addRow("Clothing slab: price per piece up to (Rs.)", self.slab_threshold)
        f.addRow("Clothing slab: rate at or below (%)", self.slab_low)
        f.addRow("Clothing slab: rate above (%)", self.slab_high)
        f.addRow(hint_label("Local sales use CGST + SGST; tick 'another state' on the bill for IGST. Confirm the "
                            "rates and slab with your accountant — GST rules change. This app does not file returns "
                            "or create e-invoices."))
        tabs.addTab(bill, "Billing && GST")

        # printers
        prn = QWidget()
        f = QFormLayout(prn)
        self.receipt_printer = QComboBox()
        self.receipt_width = QComboBox()
        self.receipt_width.addItem("80 mm (48 characters)", "80")
        self.receipt_width.addItem("58 mm (32 characters)", "58")
        self.receipt_mode = QComboBox()
        self.receipt_mode.addItem("Windows printer driver (recommended)", "DRIVER")
        self.receipt_mode.addItem("Raw ESC/POS text (for thermal printers that print blank or slow)", "RAW")
        self.receipt_font = QSpinBox()
        self.receipt_font.setRange(5, 20)
        self.receipt_cut = QCheckBox("Cut paper after receipt (raw mode)")
        self.tag_printer = QComboBox()
        self.tag_w, self.tag_h = QDoubleSpinBox(), QDoubleSpinBox()
        for sp, lo, hi in ((self.tag_w, 15, 150), (self.tag_h, 10, 150)):
            sp.setRange(lo, hi)
            sp.setDecimals(1)
            sp.setSuffix(" mm")
        f.addRow("Receipt printer", hrow(self.receipt_printer, button("Test print", self.test_receipt),
                                         stretch=False))
        f.addRow("Receipt paper width", self.receipt_width)
        f.addRow("Print mode", self.receipt_mode)
        f.addRow("Receipt font size (pt)", self.receipt_font)
        f.addRow(self.receipt_cut)
        f.addRow("Tag printer", hrow(self.tag_printer, button("Test print", self.test_tag), stretch=False))
        f.addRow("Tag size (width × height)", hrow(self.tag_w, QLabel("×"), self.tag_h, stretch=False))
        f.addRow(hint_label("Tag fields, font and margins are on the 'Barcode & Tags' screen. Install the printer's "
                            "Windows driver first and print a Windows test page. Test print saves these settings "
                            "first."))
        tabs.addTab(prn, "Printers")

        # inventory
        inv = QWidget()
        f = QFormLayout(inv)
        self.default_min = QSpinBox()
        self.default_min.setRange(0, 100000)
        self.confirm_adj = QCheckBox("Ask for confirmation before every stock adjustment")
        self.large_adj = QSpinBox()
        self.large_adj.setRange(1, 100000)
        f.addRow("Default low-stock alert quantity", self.default_min)
        f.addRow(self.confirm_adj)
        f.addRow("Warn strongly when an adjustment is this large", self.large_adj)
        tabs.addTab(inv, "Inventory")

        # backup
        bk = QWidget()
        f = QFormLayout(bk)
        self.backup_dir = QLineEdit()
        self.backup_dir.setReadOnly(True)
        self.backup_freq = QComboBox()
        for label, code in (("Every day (recommended)", "DAILY"), ("Every week", "WEEKLY"), ("Off", "OFF")):
            self.backup_freq.addItem(label, code)
        self.keep = QSpinBox()
        self.keep.setRange(1, 365)
        f.addRow("Backup folder", hrow(self.backup_dir, button("Change…", self.choose_dir), stretch=False))
        f.addRow("Automatic backup (while the app is open)", self.backup_freq)
        f.addRow("Number of backups to keep", self.keep)
        f.addRow(hint_label("Best: choose a folder on a USB drive or an external disk, and copy backups off the "
                            "computer regularly."))
        tabs.addTab(bk, "Backup")

    def showEvent(self, e):
        super().showEvent(e)
        self.load()

    def load(self):
        s = self.ctx.settings
        self.shop_name.setText(s.get("shop_name"))
        self.shop_address.setPlainText(s.get("shop_address"))
        self.shop_phone.setText(s.get("shop_phone"))
        self.shop_gstin.setText(s.get("shop_gstin"))
        self.invoice_prefix.setText(s.get("invoice_prefix"))
        self.financial_year.setText(s.get("financial_year"))
        self.footer.setText(s.get("receipt_footer"))
        self.policy.setText(s.get("return_policy"))
        self.default_payment.setCurrentIndex(max(0, self.default_payment.findData(s.get("default_payment"))))
        self.default_customer.clear()
        for c in customers.search(self.ctx.db, limit=1000):
            self.default_customer.addItem(c["name"] + (f" ({c['phone']})" if c["phone"] else ""),
                                          "" if c["is_walkin"] else str(c["id"]))
        self.default_customer.setCurrentIndex(max(0, self.default_customer.findData(s.get("default_customer_id"))))
        self.max_disc.setText(fmt_percent(s.get_int("max_discount_percent_bp")))
        self.auto_print.setChecked(s.get_bool("auto_print_receipt"))
        self.round_off.setChecked(s.get_bool("round_off_total"))
        self.gst_enabled.setChecked(s.get_bool("gst_enabled"))
        self.shop_state.setCurrentIndex(max(0, self.shop_state.findText(s.get("shop_state"))))
        self.inclusive.setCurrentIndex(max(0, self.inclusive.findData(s.get("prices_include_tax"))))
        self.default_rate.setText(fmt_percent(s.get_int("default_gst_rate_bp")))
        self.slab_threshold.setText(fmt_plain(s.get_int("slab_threshold_paise")))
        self.slab_low.setText(fmt_percent(s.get_int("slab_low_rate_bp")))
        self.slab_high.setText(fmt_percent(s.get_int("slab_high_rate_bp")))
        names = printers.available_printers()
        for combo, key in ((self.receipt_printer, "receipt_printer"), (self.tag_printer, "tag_printer")):
            combo.clear()
            combo.addItem("(Windows default printer)", "")
            for n in names:
                combo.addItem(n, n)
            saved = s.get(key)
            if saved and combo.findData(saved) < 0:
                combo.addItem(f"{saved} (not found)", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
        self.receipt_width.setCurrentIndex(max(0, self.receipt_width.findData(s.get("receipt_width_mm"))))
        self.receipt_mode.setCurrentIndex(max(0, self.receipt_mode.findData(s.get("receipt_mode"))))
        self.receipt_font.setValue(int(s.get_float("receipt_font_pt")))
        self.receipt_cut.setChecked(s.get_bool("receipt_cut"))
        self.tag_w.setValue(s.get_float("tag_width_mm"))
        self.tag_h.setValue(s.get_float("tag_height_mm"))
        self.default_min.setValue(s.get_int("default_min_stock"))
        self.confirm_adj.setChecked(s.get_bool("confirm_adjustments"))
        self.large_adj.setValue(s.get_int("large_adjustment_qty"))
        self.backup_dir.setText(str(backup.backup_dir(s)))
        self.backup_freq.setCurrentIndex(max(0, self.backup_freq.findData(s.get("backup_frequency"))))
        self.keep.setValue(s.get_int("backups_to_keep"))

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose backup folder", self.backup_dir.text())
        if d:
            self.backup_dir.setText(d)

    def collect(self) -> dict:
        threshold = self.slab_threshold.text().strip() or "0"
        values = {
            "shop_name": self.shop_name.text().strip(), "shop_address": self.shop_address.toPlainText().strip(),
            "shop_phone": self.shop_phone.text().strip(), "shop_gstin": self.shop_gstin.text().strip().upper(),
            "invoice_prefix": self.invoice_prefix.text().strip(),
            "financial_year": self.financial_year.text().strip(),
            "receipt_footer": self.footer.text().strip(), "return_policy": self.policy.text().strip(),
            "default_payment": self.default_payment.currentData(),
            "default_customer_id": self.default_customer.currentData() or "",
            "max_discount_percent_bp": parse_percent(self.max_disc.text() or "100", "Maximum discount"),
            "auto_print_receipt": self.auto_print.isChecked(), "round_off_total": self.round_off.isChecked(),
            "gst_enabled": self.gst_enabled.isChecked(), "shop_state": self.shop_state.currentText(),
            "prices_include_tax": self.inclusive.currentData(),
            "default_gst_rate_bp": parse_percent(self.default_rate.text(), "Default GST rate"),
            "slab_threshold_paise": parse_rupees(threshold, "Slab price limit"),
            "slab_low_rate_bp": parse_percent(self.slab_low.text(), "Slab lower rate"),
            "slab_high_rate_bp": parse_percent(self.slab_high.text(), "Slab higher rate"),
            "receipt_printer": self.receipt_printer.currentData() or "",
            "receipt_width_mm": self.receipt_width.currentData(), "receipt_mode": self.receipt_mode.currentData(),
            "receipt_font_pt": self.receipt_font.value(), "receipt_cut": self.receipt_cut.isChecked(),
            "tag_printer": self.tag_printer.currentData() or "",
            "tag_width_mm": self.tag_w.value(), "tag_height_mm": self.tag_h.value(),
            "default_min_stock": self.default_min.value(), "confirm_adjustments": self.confirm_adj.isChecked(),
            "large_adjustment_qty": self.large_adj.value(),
            "backup_dir": self.backup_dir.text().strip(), "backup_frequency": self.backup_freq.currentData(),
            "backups_to_keep": self.keep.value(),
        }
        if self.financial_year.text().strip() and not all(
                ch.isalnum() or ch in "-/" for ch in self.financial_year.text().strip()):
            raise ValidationError("Financial year may only use digits, letters, '-' or '/' (e.g. 2026-27).")
        if len(values["financial_year"]) > 9:
            raise ValidationError("Financial year is too long (e.g. 2026-27).")
        return values

    def save(self) -> bool:
        try:
            self.ctx.settings.set_many(self.collect())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "saving settings")
            return False
        info(self, "Saved", "Settings saved.")
        return True

    def test_receipt(self):
        try:
            self.ctx.settings.set_many(self.collect())
            width = WIDTH_CHARS.get(self.ctx.settings.get("receipt_width_mm"), 48)
            lines = build_test_receipt({"shop_name": self.ctx.settings.get("shop_name")}, width)
            printers.print_receipt(self.ctx.settings, lines)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "printing a test receipt")
            return
        info(self, "Test sent", "Settings saved and a test receipt was sent to the printer.")

    def test_tag(self):
        from ...printing.tags import TagTemplate, print_tags
        from .tags import TEST_ITEM

        try:
            self.ctx.settings.set_many(self.collect())
            print_tags(self.ctx.settings.get("tag_printer"), [(TEST_ITEM, 1)],
                       TagTemplate.from_settings(self.ctx.settings))
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "printing a test tag")
            return
        info(self, "Test sent", "Settings saved and a test tag was sent. Scan it: it should read 2000000000015.")
