"""Products with size/colour variants, images, archive, CSV import/export."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ... import paths
from ...errors import ValidationError
from ...money import fmt_percent, fmt_plain, parse_percent, parse_rupees
from ...services import catalog, csv_io
from ...services.catalog import ProductInput, VariantInput
from ..common import (AppContext, button, confirm, fill_table, hint_label, hrow, info, int_edit, make_table,
                      money_edit, percent_edit, run_safely, selected_id, show_error, title_label)

GST_CHOICES = [("Use default rate from Settings", "DEFAULT"), ("Fixed rate for this product", "FIXED"),
               ("Clothing slab (rate depends on price)", "SLAB"), ("No GST (exempt)", "EXEMPT")]
VAR_COLS = ["Size", "Colour", "SKU", "Barcode", "Price *", "MRP *", "Cost *", "Opening stock", "In stock",
            "Active"]


class ProductDialog(QDialog):
    def __init__(self, ctx: AppContext, product_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.product_id = ctx, product_id
        self.setWindowTitle("Edit product" if product_id else "Add product")
        self.resize(1100, 680)
        self.variant_ids: list[int | None] = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.category = QComboBox()
        for c in catalog.list_categories(ctx.db):
            self.category.addItem(c["name"], c["id"])
        self.brand = QLineEdit()
        self.brand.setMaxLength(60)
        self.sku = QLineEdit()
        self.sku.setPlaceholderText("optional style code")
        self.price, self.mrp, self.cost = money_edit(), money_edit(), money_edit()
        self.min_stock = int_edit(f"default ({ctx.settings.get('default_min_stock')})")
        self.hsn = QLineEdit()
        self.hsn.setPlaceholderText("optional, e.g. 6205")
        self.gst_mode = QComboBox()
        for label, code in GST_CHOICES:
            self.gst_mode.addItem(label, code)
        self.gst_rate = percent_edit()
        self.gst_mode.currentIndexChanged.connect(lambda _: self.gst_rate.setEnabled(
            self.gst_mode.currentData() == "FIXED"))
        form.addRow("Product name *", self.name)
        form.addRow("Category", self.category)
        form.addRow("Brand", self.brand)
        form.addRow("Style SKU", self.sku)
        form.addRow("Selling price (Rs.) *", self.price)
        form.addRow("MRP (Rs.)", self.mrp)
        form.addRow("Purchase cost (Rs.)", self.cost)
        form.addRow("Low-stock alert at", self.min_stock)
        form.addRow("HSN code", self.hsn)
        form.addRow("GST", self.gst_mode)
        form.addRow("GST rate % (fixed)", self.gst_rate)
        top.addLayout(form, 2)
        img_box = QGroupBox("Picture (optional)")
        il = QVBoxLayout(img_box)
        self.img = QLabel("No picture")
        self.img.setFixedSize(220, 220)
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setStyleSheet("background:#f3f4f6;border:1px dashed #cbd5e1;")
        il.addWidget(self.img)
        self.img_btn = button("Choose picture…", self.choose_image)
        self.img_rm = button("Remove picture", self.remove_image)
        il.addLayout(hrow(self.img_btn, self.img_rm))
        if not product_id:
            il.addWidget(hint_label("Save the product first, then add a picture."))
            self.img_btn.setEnabled(False)
            self.img_rm.setEnabled(False)
        top.addWidget(img_box)
        lay.addLayout(top)

        lay.addWidget(QLabel("<b>Sizes / colours</b> — each row has its own SKU, barcode and stock. "
                             "Leave SKU or barcode empty to create one automatically. "
                             "* leave blank to use the product's price."))
        self.vt = QTableWidget(0, len(VAR_COLS))
        self.vt.setHorizontalHeaderLabels(VAR_COLS)
        from PySide6.QtWidgets import QHeaderView

        hh = self.vt.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, width in enumerate((70, 110, 130, 150, 85, 85, 85, 115, 75, 60)):
            self.vt.setColumnWidth(col, width)
        hh.setStretchLastSection(True)
        self.vt.verticalHeader().setVisible(False)
        lay.addWidget(self.vt, 1)
        lay.addLayout(hrow(button("Add row", lambda: self.add_row()), button("Add sizes…", self.add_sizes),
                           button("Archive / restore selected row", self.toggle_row)))
        lay.addWidget(hint_label("Opening stock is only used when a row is first saved. Change stock later in "
                                 "Inventory so every change is recorded."))
        lay.addLayout(hrow(None, button("Cancel", self.reject), button("Save product", self.save, primary=True),
                           stretch=False))
        if product_id:
            self.load()
        else:
            self.gst_rate.setEnabled(False)
            self.add_row()

    def _cell(self, r, c, text, editable=True):
        it = QTableWidgetItem(text)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.vt.setItem(r, c, it)

    def add_row(self, v: dict | None = None):
        r = self.vt.rowCount()
        self.vt.insertRow(r)
        v = v or {}
        self.variant_ids.append(v.get("id"))
        self._cell(r, 0, v.get("size", ""))
        self._cell(r, 1, v.get("colour", ""))
        self._cell(r, 2, v.get("sku", ""))
        self._cell(r, 3, v.get("barcode", ""))
        for c, key in ((4, "price_paise"), (5, "mrp_paise"), (6, "cost_paise")):
            self._cell(r, c, "" if v.get(key) is None else fmt_plain(v[key]))
        self._cell(r, 7, "0", editable=v.get("id") is None)
        self._cell(r, 8, str(v.get("stock", 0)), editable=False)
        self._cell(r, 9, "Yes" if v.get("active", 1) else "No", editable=False)

    def add_sizes(self):
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Add sizes", "Sizes separated by commas (e.g. S, M, L, XL):")
        if not ok:
            return
        colour, ok = QInputDialog.getText(self, "Colour", "Colour for these sizes (optional):")
        if not ok:
            return
        for size in [s.strip() for s in text.split(",") if s.strip()]:
            self.add_row({"size": size, "colour": colour.strip()})

    def toggle_row(self):
        r = self.vt.currentRow()
        if r < 0:
            return
        if self.variant_ids[r] is None:
            self.vt.removeRow(r)
            self.variant_ids.pop(r)
            return
        cur = self.vt.item(r, 9).text()
        self._cell(r, 9, "No" if cur == "Yes" else "Yes", editable=False)

    def load(self):
        p = catalog.get_product(self.ctx.db, self.product_id)
        self.name.setText(p["name"])
        idx = self.category.findData(p["category_id"])
        self.category.setCurrentIndex(max(0, idx))
        self.brand.setText(p["brand"])
        self.sku.setText(p["sku"] or "")
        self.price.setText(fmt_plain(p["price_paise"]))
        self.mrp.setText(fmt_plain(p["mrp_paise"]) if p["mrp_paise"] else "")
        self.cost.setText(fmt_plain(p["cost_paise"]) if p["cost_paise"] else "")
        self.min_stock.setText("" if p["min_stock"] is None else str(p["min_stock"]))
        self.hsn.setText(p["hsn_code"])
        self.gst_mode.setCurrentIndex(max(0, self.gst_mode.findData(p["gst_mode"])))
        self.gst_rate.setText(fmt_percent(p["gst_rate_bp"]) if p["gst_rate_bp"] else "")
        self.gst_rate.setEnabled(p["gst_mode"] == "FIXED")
        for v in p["variants"]:
            self.add_row(v)
        self.show_image(p["image_file"])

    def show_image(self, name: str):
        path = catalog.image_path(name)
        if path:
            pm = QPixmap(str(path))
            self.img.setPixmap(pm.scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
        else:
            self.img.setPixmap(QPixmap())
            self.img.setText("No picture")

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose picture", "", "Pictures (*.jpg *.jpeg *.png *.bmp *.webp)")
        if path:
            name = run_safely(self, lambda: catalog.set_product_image(self.ctx.db, self.product_id, path),
                              "saving the picture")
            if name:
                self.show_image(name)

    def remove_image(self):
        if confirm(self, "Remove picture", "Remove this product's picture?"):
            run_safely(self, lambda: catalog.set_product_image(self.ctx.db, self.product_id, None))
            self.show_image("")

    def _money_or_none(self, text: str, what: str):
        return None if not text.strip() else parse_rupees(text, what)

    def collect(self) -> ProductInput:
        if not self.price.text().strip():
            raise ValidationError("Enter the selling price.")
        mode = self.gst_mode.currentData()
        p = ProductInput(
            name=self.name.text(), category_id=self.category.currentData(), brand=self.brand.text(),
            sku=self.sku.text(), price=parse_rupees(self.price.text(), "Selling price"),
            mrp=parse_rupees(self.mrp.text() or "0", "MRP"), cost=parse_rupees(self.cost.text() or "0", "Cost"),
            min_stock=int(self.min_stock.text()) if self.min_stock.text().strip() else None,
            hsn_code=self.hsn.text(), gst_mode=mode,
            gst_rate_bp=parse_percent(self.gst_rate.text(), "GST rate") if mode == "FIXED" else 0)
        for r in range(self.vt.rowCount()):
            def t(c, r=r):
                it = self.vt.item(r, c)
                return it.text().strip() if it else ""
            label = " / ".join(x for x in (t(0), t(1)) if x) or f"row {r + 1}"
            opening = t(7) or "0"
            if not opening.isdigit():
                raise ValidationError(f"Opening stock for {label} must be a whole number.")
            p.variants.append(VariantInput(
                id=self.variant_ids[r], size=t(0), colour=t(1), sku=t(2), barcode=t(3),
                price=self._money_or_none(t(4), f"Price for {label}"), mrp=self._money_or_none(t(5), f"MRP for {label}"),
                cost=self._money_or_none(t(6), f"Cost for {label}"),
                opening_stock=int(opening) if self.variant_ids[r] is None else 0, active=t(9) == "Yes"))
        return p

    def save(self):
        try:
            p = self.collect()
            self.product_id = catalog.save_product(self.ctx.db, p, self.product_id)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "saving the product")
            return
        self.accept()


class ProductsPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Products"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, brand, SKU or barcode…")
        self.category = QComboBox()
        self.brand = QComboBox()
        self.status = QComboBox()
        self.status.addItems(["Active", "Archived", "All"])
        self.timer = QTimer(self, singleShot=True, interval=200, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self.timer.start())
        for cb in (self.category, self.brand, self.status):
            cb.currentIndexChanged.connect(lambda _: self.reload())
        lay.addLayout(hrow(self.search, QLabel("Category"), self.category, QLabel("Brand"), self.brand,
                           QLabel("Show"), self.status, stretch=False))
        self.table = make_table(["Product", "Category", "Brand", "Style SKU", "Price", "MRP", "Sizes", "Stock",
                                 "Status"])
        self.table.doubleClicked.connect(lambda _: self.edit())
        lay.addWidget(self.table, 1)
        lay.addLayout(hrow(button("Add product", self.add, primary=True), button("Edit", self.edit),
                           button("Archive / restore", self.toggle_archive), None,
                           button("Import CSV…", self.import_csv), button("Export CSV…", self.export_csv),
                           button("Download CSV template…", self.template), stretch=False))
        lay.addWidget(hint_label("Products that were sold are never deleted — archive them to hide them from billing."))

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        for cb, items in ((self.category, [(c["name"], c["id"]) for c in catalog.list_categories(self.ctx.db)]),
                          (self.brand, [(b, b) for b in catalog.list_brands(self.ctx.db)])):
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("All", None)
            for label, data in items:
                cb.addItem(label, data)
            cb.setCurrentIndex(max(0, cb.findData(cur)))
            cb.blockSignals(False)
        self.reload()

    def reload(self):
        status = {"Active": "ACTIVE", "Archived": "ARCHIVED", "All": "ALL"}[self.status.currentText()]
        rows = catalog.list_products(self.ctx.db, self.search.text(), self.category.currentData(), status,
                                     self.brand.currentData() or "")
        fill_table(self.table, [[r["name"], r["category"] or "", r["brand"], r["sku"] or "", r["price_paise"],
                                 r["mrp_paise"], r["variant_count"], r["stock"],
                                 "Active" if r["active"] else "Archived"] for r in rows],
                   money_cols={4, 5}, ids=[r["id"] for r in rows])

    def add(self):
        dlg = ProductDialog(self.ctx, None, self)
        if dlg.exec():
            self.refresh()
            if confirm(self, "Product saved", "Product saved. Do you want to add a picture now?\n"
                                              "(Print its tags from 'Barcode & Tags'.)"):
                ProductDialog(self.ctx, dlg.product_id, self).exec()
                self.reload()

    def edit(self):
        pid = selected_id(self.table)
        if pid and ProductDialog(self.ctx, pid, self).exec():
            self.reload()

    def toggle_archive(self):
        pid = selected_id(self.table)
        if not pid:
            return
        p = catalog.get_product(self.ctx.db, pid)
        if p["active"]:
            if confirm(self, "Archive product", f"Archive '{p['name']}'? It will no longer appear in billing. "
                                                "Old bills keep it."):
                catalog.set_product_active(self.ctx.db, pid, False)
        else:
            catalog.set_product_active(self.ctx.db, pid, True)
        self.reload()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import products", str(paths.exports_dir()), "CSV files (*.csv)")
        if not path:
            return
        res = run_safely(self, lambda: csv_io.import_products(self.ctx.db, path, dry_run=True), "reading the CSV")
        if res is None:
            return
        if not res.ok:
            text = "\n".join(f"Row {n}: {m}" for n, m in res.errors[:40])
            more = f"\n… and {len(res.errors) - 40} more" if len(res.errors) > 40 else ""
            QMessageBox.warning(self, "CSV has problems", "Nothing was imported. Fix these rows and try again:\n\n"
                                + text + more)
            return
        if not confirm(self, "Import products", f"The file looks good: {res.products} product(s) with "
                                                f"{res.variants} size/colour row(s).\n\nImport now?"):
            return
        res = run_safely(self, lambda: csv_io.import_products(self.ctx.db, path), "importing the CSV")
        if res and res.ok:
            extra = f"\nNew categories: {', '.join(res.new_categories)}" if res.new_categories else ""
            info(self, "Imported", f"Imported {res.products} product(s), {res.variants} row(s).{extra}")
            self.refresh()

    def export_csv(self):
        paths.exports_dir().mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Export products", str(paths.exports_dir() / "products.csv"),
                                              "CSV files (*.csv)")
        if path:
            n = run_safely(self, lambda: csv_io.export_products(self.ctx.db, path), "exporting")
            if n is not None:
                info(self, "Exported", f"Exported {n} row(s) to\n{path}")

    def template(self):
        paths.exports_dir().mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV template",
                                              str(paths.exports_dir() / "products-template.csv"), "CSV files (*.csv)")
        if path:
            run_safely(self, lambda: csv_io.template_csv(path))
