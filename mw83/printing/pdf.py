"""PDF copies of receipts and reports (reportlab, no internet needed)."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from ..services.reports import Report
from .receipt import Line


def receipt_pdf(lines: list[Line], path: str | Path, paper_mm: int = 80, width_chars: int = 48) -> Path:
    path = Path(path)
    margin = 3 * mm
    usable = paper_mm * mm - 2 * margin
    size = 10.0
    while size > 4 and stringWidth("M" * width_chars, "Courier", size) > usable:
        size -= 0.25
    leading = size * 1.25
    height = max(60 * mm, 2 * margin + leading * (len(lines) + 2) + 6 * mm)
    c = canvas.Canvas(str(path), pagesize=(paper_mm * mm, height))
    c.setTitle("Receipt")
    y = height - margin - leading
    for ln in lines:
        font = "Courier-Bold" if ln.bold else "Courier"
        c.setFont(font, size)
        c.drawString(margin, y, ln.text)
        y -= leading
    c.showPage()
    c.save()
    return path


def report_pdf(report: Report, path: str | Path, shop_name: str) -> Path:
    path = Path(path)
    wide = len(report.headers) > 6
    pagesize = landscape(A4) if wide else A4
    doc = SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=report.title)
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=7.5, leading=9)
    story = [Paragraph(escape(f"{shop_name} - {report.title}"), styles["Title"])]
    if report.subtitle:
        story.append(Paragraph(escape(report.subtitle), styles["Normal"]))
    story.append(Spacer(1, 4 * mm))
    rows = report.formatted_rows()
    if not rows:
        story.append(Paragraph("No data for the selected period.", styles["Normal"]))
    else:
        data = [[Paragraph(f"<b>{escape(h)}</b>", cell) for h in report.headers]]
        data += [[Paragraph(escape(v), cell) for v in r] for r in rows]
        t = Table(data, repeatRows=1)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if report.totals:
            style.append(("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), colors.HexColor("#f2f2f2")))
        t.setStyle(TableStyle(style))
        story.append(t)
    doc.build(story)
    return path
