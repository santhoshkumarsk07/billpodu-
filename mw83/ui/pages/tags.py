"""Barcode & tag printing. Printing tags never changes stock or prices."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from ...errors import UserError
from ...printing import tags as tagprint
from ...printing.printers import available_printers
from ...services import catalog, tag_jobs
from ..common import (AppContext, button, confirm, fill_table, hint_label, hrow, info, make_table, run_safely,
                      selected_id, show_error, title_label)
from ..dialogs import VariantSearchDialog

TEST_ITEM = {"product_name": "TEST TAG - Sample Shirt", "size": "XL", "colour": "Blue", "sku": "TEST-SKU",
             "barcode": "2000000000015", "mrp": 129900, "price": 99900}


class TagsPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.queue: list[list] = []  # [variant_id, copies]
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Barcode & Tag Printing"))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.table = make_table(["Product", "Size", "Colour", "Barcode", "In stock", "Tags to print"], stretch_col=0)
        self.table.itemSelectionChanged.connect(self.preview)
        self.table.doubleClicked.connect(lambda _: self.set_copies())
        left.addWidget(self.table, 1)
        left.addLayout(hrow(button("Add items…", self.add_items, primary=True), button("Set tag count", self.set_copies),
                            button("Tags = stock for all", self.copies_from_stock), button("Remove", self.remove),
                            button("Clear list", self.clear), stretch=False))
        jobs_box = QGroupBox("Reprint an earlier tag job")
        jl = QVBoxLayout(jobs_box)
        self.jobs = QComboBox()
        jl.addLayout(hrow(self.jobs, button("Load into list", self.load_job), stretch=False))
        left.addWidget(jobs_box)
        body.addLayout(left, 3)

        right = QVBoxLayout()
        tpl = QGroupBox("Tag layout")
        f = QFormLayout(tpl)
        s = ctx.settings
        self.w, self.h, self.m, self.font = (QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox())
        for sp, lo, hi, val in ((self.w, 15, 150, s.get_float("tag_width_mm")),
                                (self.h, 10, 150, s.get_float("tag_height_mm")),
                                (self.m, 0, 20, s.get_float("tag_margin_mm")),
                                (self.font, 4, 30, s.get_float("tag_font_pt"))):
            sp.setRange(lo, hi)
            sp.setDecimals(1)
            sp.setValue(val)
            sp.valueChanged.connect(lambda _: self.preview())
        self.kind = QComboBox()
        self.kind.addItem("Code 128 (works for any code)", "CODE128")
        self.kind.addItem("EAN-13 (only for valid 13-digit codes)", "EAN13")
        self.kind.setCurrentIndex(max(0, self.kind.findData(s.get("tag_barcode_type"))))
        self.kind.currentIndexChanged.connect(lambda _: self.preview())
        f.addRow("Width (mm)", self.w)
        f.addRow("Height (mm)", self.h)
        f.addRow("Margin (mm)", self.m)
        f.addRow("Font size (pt)", self.font)
        f.addRow("Barcode type", self.kind)
        self.checks = {}
        for key, label in (("tag_show_shop", "Shop name"), ("tag_show_name", "Product name"), ("tag_show_size", "Size"),
                           ("tag_show_colour", "Colour"), ("tag_show_sku", "SKU"), ("tag_show_mrp", "MRP"),
                           ("tag_show_price", "Selling price")):
            cb = QCheckBox(label)
            cb.setChecked(s.get_bool(key))
            cb.toggled.connect(lambda _: self.preview())
            self.checks[key] = cb
        grid = QHBoxLayout()
        col1, col2 = QVBoxLayout(), QVBoxLayout()
        for i, cb in enumerate(self.checks.values()):
            (col1 if i < 4 else col2).addWidget(cb)
        grid.addLayout(col1)
        grid.addLayout(col2)
        f.addRow("Show", grid)
        f.addRow(button("Save as default layout", self.save_template))
        right.addWidget(tpl)
        self.preview_lbl = QLabel("Preview")
        self.preview_lbl.setMinimumSize(360, 200)
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setStyleSheet("background:#e5e7eb;border:1px solid #cbd5e1;")
        right.addWidget(self.preview_lbl)
        self.printer = QComboBox()
        right.addLayout(hrow(QLabel("Tag printer"), self.printer, stretch=False))
        right.addLayout(hrow(button("Test print", self.test_print), button("Print selected", self.print_selected),
                             button("Print all", self.print_all, primary=True), stretch=False))
        right.addWidget(hint_label("Preview is shown at the real label size. Do a test print first and check that "
                                   "the barcode scans. Printing tags does not change stock or prices."))
        right.addStretch(1)
        body.addLayout(right, 2)
        lay.addLayout(body)

    def showEvent(self, e):
        super().showEvent(e)
        cur = self.printer.currentData() if self.printer.count() else self.ctx.settings.get("tag_printer")
        self.printer.clear()
        self.printer.addItem("(Windows default printer)", "")
        for name in available_printers():
            self.printer.addItem(name, name)
        self.printer.setCurrentIndex(max(0, self.printer.findData(cur)))
        self.jobs.clear()
        for j in tag_jobs.list_jobs(self.ctx.db):
            self.jobs.addItem(f"{j['created_at']} — {j['label']} ({j['tags']} tags)", j["items"])
        self.render()

    def template(self) -> tagprint.TagTemplate:
        return tagprint.TagTemplate(
            width_mm=self.w.value(), height_mm=self.h.value(), margin_mm=self.m.value(), font_pt=self.font.value(),
            barcode_kind=self.kind.currentData(), shop_name=self.ctx.settings.get("shop_name"),
            show_shop=self.checks["tag_show_shop"].isChecked(), show_name=self.checks["tag_show_name"].isChecked(),
            show_size=self.checks["tag_show_size"].isChecked(), show_colour=self.checks["tag_show_colour"].isChecked(),
            show_sku=self.checks["tag_show_sku"].isChecked(), show_mrp=self.checks["tag_show_mrp"].isChecked(),
            show_price=self.checks["tag_show_price"].isChecked())

    def save_template(self):
        t = self.template()
        values = {"tag_width_mm": t.width_mm, "tag_height_mm": t.height_mm, "tag_margin_mm": t.margin_mm,
                  "tag_font_pt": t.font_pt, "tag_barcode_type": t.barcode_kind, "tag_printer": self.printer.currentData() or ""}
        values.update({k: cb.isChecked() for k, cb in self.checks.items()})
        if run_safely(self, lambda: self.ctx.settings.set_many(values) or True, "saving the layout"):
            info(self, "Saved", "Tag layout saved as default.")

    @staticmethod
    def _item(v: dict) -> dict:
        return {"product_name": v["product_name"], "size": v["size"], "colour": v["colour"], "sku": v["sku"],
                "barcode": v["barcode"], "mrp": v["mrp"], "price": v["price"]}

    def render(self):
        rows, ids = [], []
        for vid, copies in self.queue:
            try:
                v = catalog.get_variant(self.ctx.db, vid)
            except UserError:
                continue
            rows.append([v["product_name"], v["size"], v["colour"], v["barcode"], v["stock"], copies])
            ids.append(vid)
        cur = self.table.currentRow()
        fill_table(self.table, rows, ids=ids)
        if rows:
            self.table.selectRow(max(0, min(cur, len(rows) - 1)))
        self.preview()

    def preview(self):
        vid = selected_id(self.table)
        item = self._item(catalog.get_variant(self.ctx.db, vid)) if vid else TEST_ITEM
        try:
            img = tagprint.render_preview(item, self.template(), dpi=203)
        except UserError as exc:
            self.preview_lbl.setPixmap(QPixmap())
            self.preview_lbl.setText(exc.message)
            self.preview_lbl.setWordWrap(True)
            return
        pm = QPixmap.fromImage(img)
        self.preview_lbl.setPixmap(pm.scaled(self.preview_lbl.width() - 10, self.preview_lbl.height() - 10,
                                             Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))

    def add_items(self):
        dlg = VariantSearchDialog(self.ctx, self, multi=True, active_only=False, title="Choose items for tags")
        if dlg.exec():
            have = {vid for vid, _ in self.queue}
            for vid in dlg.selected:
                if vid not in have:
                    self.queue.append([vid, 1])
            self.render()

    def set_copies(self):
        from PySide6.QtWidgets import QInputDialog

        row = self.table.currentRow()
        if row < 0:
            return
        n, ok = QInputDialog.getInt(self, "Tags", "How many tags for this item?", self.queue[row][1], 0, 999)
        if ok:
            self.queue[row][1] = n
            self.render()

    def copies_from_stock(self):
        for q in self.queue:
            q[1] = max(0, catalog.get_variant(self.ctx.db, q[0])["stock"])
        self.render()

    def remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.queue.pop(row)
            self.render()

    def clear(self):
        if self.queue and confirm(self, "Clear list", "Remove all items from the tag list?"):
            self.queue = []
            self.render()

    def load_job(self):
        items = self.jobs.currentData()
        if items:
            self.queue = [[v, c] for v, c in items]
            self.render()

    def _print(self, jobs: list[tuple[int, int]], label: str):
        jobs = [(v, c) for v, c in jobs if c > 0]
        if not jobs:
            info(self, "Nothing to print", "Set how many tags to print first.")
            return
        total = sum(c for _, c in jobs)
        if total > 20 and not confirm(self, "Print tags", f"Print {total} tags on {self.printer.currentText()}?"):
            return
        try:
            items = [(self._item(catalog.get_variant(self.ctx.db, v)), c) for v, c in jobs]
            n = tagprint.print_tags(self.printer.currentData() or "", items, self.template())
            tag_jobs.log_job(self.ctx.db, label, jobs)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "printing tags")
            return
        info(self, "Sent to printer", f"{n} tag(s) sent to {self.printer.currentText()}.")

    def print_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            v, c = self.queue[row]
            self._print([(v, c)], self.table.item(row, 0).text())

    def print_all(self):
        self._print([(v, c) for v, c in self.queue], f"{len(self.queue)} item(s)")

    def test_print(self):
        try:
            tagprint.print_tags(self.printer.currentData() or "", [(TEST_ITEM, 1)], self.template())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "printing a test tag")
            return
        info(self, "Test tag sent", "A test tag was sent. Check that text fits and scan the barcode — it should "
                                    "read 2000000000015.")
