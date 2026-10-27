"""Reports run on a background thread so the screen never freezes."""
from __future__ import annotations

import re

from PySide6.QtWidgets import QComboBox, QFileDialog, QLabel, QVBoxLayout, QWidget

from ... import paths
from ...printing.pdf import report_pdf
from ...services import csv_io, reports
from ..common import (AppContext, DateRange, button, fill_table, hint_label, hrow, info, make_table,
                      run_in_background, run_safely, title_label)


class ReportsPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.report: reports.Report | None = None
        self._job = None
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("Reports"))
        self.kind = QComboBox()
        self.kind.addItems(list(reports.REPORTS))
        self.kind.currentIndexChanged.connect(lambda _: self.run())
        self.range = DateRange(days_back=0)
        self.range.this_month()
        self.run_btn = button("Show report", self.run, primary=True)
        lay.addLayout(hrow(QLabel("Report"), self.kind, self.range, self.run_btn, stretch=False))
        self.subtitle = QLabel()
        self.subtitle.setWordWrap(True)
        lay.addWidget(self.subtitle)
        self.table = make_table(["…"])
        lay.addWidget(self.table, 1)
        lay.addLayout(hrow(button("Export CSV…", self.export_csv), button("Export PDF…", self.export_pdf)))
        lay.addWidget(hint_label("All figures come from saved bills, returns and stock records. Cancelled bills are "
                                 "not counted as sales. Returns are counted on the day they were made."))

    def showEvent(self, e):
        super().showEvent(e)
        self.run()

    def run(self):
        name = self.kind.currentText()
        kind, fn = reports.REPORTS[name]
        a, b = self.range.values()
        self.range.setEnabled(kind == "range")
        dm = self.ctx.settings.get_int("default_min_stock")
        work = (lambda conn: fn(conn, dm)) if kind == "stock" else (lambda conn: fn(conn, a, b))
        self.run_btn.setEnabled(False)
        self.subtitle.setText("Working…")
        self._job = run_in_background(self.ctx, work, self.show_report, self, "making the report")
        self._job.signals.failed.connect(lambda _: self.run_btn.setEnabled(True))

    def show_report(self, rep: reports.Report):
        self.run_btn.setEnabled(True)
        self.report = rep
        self.subtitle.setText(rep.subtitle + ("" if rep.rows else "  —  No data for this period."))
        self.table.clear()
        self.table.setColumnCount(len(rep.headers))
        self.table.setHorizontalHeaderLabels(rep.headers)
        fill_table(self.table, rep.formatted_rows(), right_cols=rep.money_cols)

    def _name(self, ext: str) -> str:
        base = re.sub(r"[^A-Za-z0-9-]+", "-", self.report.title).strip("-")
        a, b = self.range.values()
        return str(paths.exports_dir() / f"{base}-{a}-to-{b}.{ext}")

    def export_csv(self):
        if not self.report:
            return
        paths.exports_dir().mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", self._name("csv"), "CSV files (*.csv)")
        if path and run_safely(self, lambda: csv_io.write_csv(path, self.report.headers,
                                                              self.report.formatted_rows()) or True, "exporting"):
            info(self, "Exported", f"Saved:\n{path}")

    def export_pdf(self):
        if not self.report:
            return
        paths.exports_dir().mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", self._name("pdf"), "PDF files (*.pdf)")
        if path and run_safely(self, lambda: report_pdf(self.report, path, self.ctx.settings.get("shop_name")),
                               "exporting the PDF"):
            info(self, "Exported", f"Saved:\n{path}")
