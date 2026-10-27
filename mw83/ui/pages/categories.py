from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QVBoxLayout, QWidget

from ...services import catalog
from ..common import (AppContext, button, confirm, fill_table, hint_label, hrow, make_table, run_safely, selected_id,
                      title_label)


class CategoriesPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Categories"))
        self.table = make_table(["Category", "Products"])
        self.table.doubleClicked.connect(lambda _: self.rename())
        lay.addWidget(self.table, 1)
        lay.addLayout(hrow(button("Add category", self.add, primary=True), button("Rename", self.rename),
                           button("Delete", self.delete)))
        lay.addWidget(hint_label("A category can only be deleted when no product uses it."))

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        rows = catalog.list_categories(self.ctx.db)
        fill_table(self.table, [[r["name"], r["products"]] for r in rows], ids=[r["id"] for r in rows])

    def add(self):
        name, ok = QInputDialog.getText(self, "Add category", "Category name:")
        if ok and run_safely(self, lambda: catalog.add_category(self.ctx.db, name), "adding the category"):
            self.reload()

    def rename(self):
        cid = selected_id(self.table)
        if not cid:
            return
        old = self.table.item(self.table.currentRow(), 0).text()
        name, ok = QInputDialog.getText(self, "Rename category", "New name:", text=old)
        if ok:
            run_safely(self, lambda: catalog.rename_category(self.ctx.db, cid, name), "renaming the category")
            self.reload()

    def delete(self):
        cid = selected_id(self.table)
        if not cid:
            return
        name = self.table.item(self.table.currentRow(), 0).text()
        if confirm(self, "Delete category", f"Delete the category '{name}'?", danger=True):
            run_safely(self, lambda: catalog.delete_category(self.ctx.db, cid), "deleting the category")
            self.reload()
