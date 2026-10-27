"""Clothing price tags with a barcode, drawn with QPainter.

Bars are drawn on whole device pixels so they stay crisp and scannable on
203/300 dpi label printers. Printing tags never changes stock or prices.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

from ..errors import PrinterError, ValidationError
from ..money import fmt
from . import barcodes

log = logging.getLogger("mw83.print")
MAX_TAGS_PER_JOB = 2000


@dataclass
class TagTemplate:
    width_mm: float = 50
    height_mm: float = 25
    margin_mm: float = 1.5
    font_pt: float = 7
    barcode_kind: str = "CODE128"
    shop_name: str = "83 MEN'S WEAR"
    show_shop: bool = True
    show_name: bool = True
    show_size: bool = True
    show_colour: bool = True
    show_sku: bool = False
    show_mrp: bool = True
    show_price: bool = True

    @classmethod
    def from_settings(cls, s) -> "TagTemplate":
        return cls(width_mm=s.get_float("tag_width_mm"), height_mm=s.get_float("tag_height_mm"),
                   margin_mm=s.get_float("tag_margin_mm"), font_pt=s.get_float("tag_font_pt"),
                   barcode_kind=s.get("tag_barcode_type"), shop_name=s.get("shop_name"),
                   show_shop=s.get_bool("tag_show_shop"), show_name=s.get_bool("tag_show_name"),
                   show_size=s.get_bool("tag_show_size"), show_colour=s.get_bool("tag_show_colour"),
                   show_sku=s.get_bool("tag_show_sku"), show_mrp=s.get_bool("tag_show_mrp"),
                   show_price=s.get_bool("tag_show_price"))


def tag_money(paise: int) -> str:
    """Rs. 999 rather than 999.00 when there are no paise, to save space on small tags."""
    text = fmt(paise)
    return text[:-3] if text.endswith(".00") else text


def _font(pt: float, bold: bool = False) -> QFont:
    f = QFont("Arial")
    f.setPointSizeF(max(3.0, pt))
    f.setBold(bold)
    return f


def draw_tag(painter: QPainter, dpi: float, item: dict, t: TagTemplate) -> None:
    """Draw one tag at the painter's origin. `item` has product_name, size, colour, sku, barcode, mrp, price."""
    px = dpi / 25.4
    W, H = t.width_mm * px, t.height_mm * px
    m = t.margin_mm * px
    painter.fillRect(QRectF(0, 0, W, H), QColor("white"))
    painter.setPen(QColor("black"))
    x0, x1 = m, W - m
    y = m
    device = painter.device()

    def text_line(text: str, pt: float, bold=False, align=Qt.AlignmentFlag.AlignHCenter):
        nonlocal y
        if not text:
            return
        f = _font(pt, bold)
        fm = QFontMetricsF(f, device)
        painter.setFont(f)
        txt = fm.elidedText(text, Qt.TextElideMode.ElideRight, x1 - x0)
        painter.drawText(QRectF(x0, y, x1 - x0, fm.height()), int(align | Qt.AlignmentFlag.AlignTop), txt)
        y += fm.height()

    if t.show_shop:
        text_line(t.shop_name, t.font_pt, True)
    if t.show_name:
        text_line(item.get("product_name", ""), t.font_pt)
    detail = []
    if t.show_size and item.get("size"):
        detail.append(f"Size: {item['size']}")
    if t.show_colour and item.get("colour"):
        detail.append(f"Colour: {item['colour']}" if not detail else item["colour"])
    if t.show_sku and item.get("sku"):
        detail.append(item["sku"])
    if detail:
        text_line("  |  ".join(detail), t.font_pt)

    # bottom block: price line and human-readable code
    price_parts = []
    if t.show_mrp and item.get("mrp"):
        price_parts.append(f"MRP Rs.{tag_money(item['mrp'])}")
    if t.show_price and item.get("price") is not None and (not item.get("mrp") or item["price"] != item["mrp"]
                                                            or not t.show_mrp):
        price_parts.append(f"Price Rs.{tag_money(item['price'])}")
    price_text = "  ".join(price_parts)
    pt = t.font_pt + 1
    price_font = _font(pt, True)
    while pt > 4 and QFontMetricsF(price_font, device).horizontalAdvance(price_text) > x1 - x0:
        pt -= 0.5
        price_font = _font(pt, True)
    code_font = _font(max(4.0, t.font_pt - 1))
    pfm, cfm = QFontMetricsF(price_font, device), QFontMetricsF(code_font, device)
    bottom = H - m
    price_h = pfm.height() if price_parts else 0
    code_top = bottom - price_h - cfm.height()
    bar_top = y + 0.5 * px
    bar_h = code_top - bar_top
    if bar_h < 3 * px:
        raise ValidationError("The tag is too small for this text and a barcode. Increase the tag height, "
                              "reduce the font size or hide some fields.")
    code = item.get("barcode", "")
    kind = barcodes.effective_kind(code, t.barcode_kind)
    pattern = barcodes.modules(code, kind)
    quiet = 10  # modules of white space each side
    module = int((x1 - x0) // (len(pattern) + 2 * quiet))
    if module < 1:
        raise ValidationError(f"Barcode '{code}' is too long for a {t.width_mm:g} mm wide tag. "
                              "Use a wider tag or a shorter barcode.")
    bar_w = module * len(pattern)
    bx = int(x0 + ((x1 - x0) - bar_w) / 2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("black"))
    i = 0
    while i < len(pattern):
        if pattern[i] == "1":
            j = i
            while j < len(pattern) and pattern[j] == "1":
                j += 1
            painter.drawRect(QRectF(bx + i * module, int(bar_top), (j - i) * module, int(bar_h)))
            i = j
        else:
            i += 1
    painter.setPen(QColor("black"))
    painter.setFont(code_font)
    painter.drawText(QRectF(x0, code_top, x1 - x0, cfm.height()),
                     int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), code)
    if price_parts:
        painter.setFont(price_font)
        txt = pfm.elidedText(price_text, Qt.TextElideMode.ElideRight, x1 - x0)
        painter.drawText(QRectF(x0, bottom - price_h, x1 - x0, price_h),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), txt)


def render_preview(item: dict, t: TagTemplate, dpi: float = 300) -> QImage:
    px = dpi / 25.4
    img = QImage(int(t.width_mm * px), int(t.height_mm * px), QImage.Format.Format_RGB32)
    img.setDotsPerMeterX(int(dpi / 0.0254))
    img.setDotsPerMeterY(int(dpi / 0.0254))
    img.fill(QColor("white"))
    p = QPainter(img)
    try:
        draw_tag(p, dpi, item, t)
    finally:
        p.end()
    return img


def print_tags(printer_name: str, jobs: list[tuple[dict, int]], t: TagTemplate) -> int:
    """Print each item `copies` times, one tag per label/page. Returns tags printed."""
    from .printers import TROUBLESHOOT, _make_printer

    total = sum(c for _, c in jobs)
    if total <= 0:
        raise ValidationError("Enter how many tags to print.")
    if total > MAX_TAGS_PER_JOB:
        raise ValidationError(f"Please print at most {MAX_TAGS_PER_JOB} tags at a time.")
    for item, _ in jobs:  # validate every barcode before sending anything to the printer
        barcodes.modules(item["barcode"], barcodes.effective_kind(item["barcode"], t.barcode_kind))
    printer = _make_printer(printer_name, t.width_mm, t.height_mm)
    painter = QPainter()
    if not painter.begin(printer):
        raise PrinterError(f"Could not start printing on '{printer.printerName()}'." + TROUBLESHOOT)
    printed = 0
    try:
        dpi = printer.resolution()
        for item, copies in jobs:
            for _ in range(copies):
                if printed:
                    printer.newPage()
                draw_tag(painter, dpi, item, t)
                printed += 1
    except (ValidationError, PrinterError):
        painter.end()
        raise
    except Exception as exc:
        painter.end()
        log.exception("tag print failed")
        raise PrinterError("Tags could not be printed." + TROUBLESHOOT) from exc
    painter.end()
    return printed
