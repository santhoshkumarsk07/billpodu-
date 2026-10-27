"""Printing through installed Windows printer drivers (Qt), with an optional raw
ESC/POS text mode for thermal receipt printers.

Printing never touches the database, so a printer failure cannot change a sale.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from ..errors import PrinterError
from .receipt import Line

log = logging.getLogger("mw83.print")

TROUBLESHOOT = (
    "\n\nPlease check:\n"
    "• The printer is switched on and the cable is connected\n"
    "• It has paper and the cover is closed\n"
    "• The correct printer is chosen in Settings → Printers\n"
    "• Windows can print a test page to it (Settings → Bluetooth & devices → Printers)")


def available_printers() -> list[str]:
    return [p.printerName() for p in QPrinterInfo.availablePrinters()]


def default_printer() -> str:
    return QPrinterInfo.defaultPrinter().printerName()


def _make_printer(name: str, width_mm: float, height_mm: float) -> QPrinter:
    if not name:
        name = default_printer()
        if not name:
            raise PrinterError("No printer is selected and Windows has no default printer." + TROUBLESHOOT)
    info = QPrinterInfo.printerInfo(name)
    if info.isNull():
        raise PrinterError(f"Printer '{name}' was not found on this computer." + TROUBLESHOOT)
    printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
    printer.setFullPage(True)
    layout = QPageLayout(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter, "custom",
                                   QPageSize.SizeMatchPolicy.ExactMatch),
                         QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    printer.setPageLayout(layout)
    return printer


def _mono_font(pt: float, bold: bool = False) -> QFont:
    f = QFont("Consolas" if sys.platform == "win32" else "Monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


def print_receipt_driver(printer_name: str, lines: list[Line], paper_mm: int, width_chars: int,
                         font_pt: float = 8.0) -> None:
    margin_mm = 2.0 if paper_mm == 58 else 3.0
    est_height = 10 + len(lines) * (font_pt * 0.3528 * 1.35) + 15
    printer = _make_printer(printer_name, paper_mm, est_height)
    painter = QPainter()
    if not painter.begin(printer):
        raise PrinterError(f"Could not start printing on '{printer.printerName()}'." + TROUBLESHOOT)
    try:
        dpi = printer.resolution()
        px_per_mm = dpi / 25.4
        usable = (paper_mm - 2 * margin_mm) * px_per_mm
        pt = font_pt
        while pt > 4:
            if QFontMetricsF(_mono_font(pt), printer).horizontalAdvance("M" * width_chars) <= usable:
                break
            pt -= 0.25
        y = 2 * px_per_mm
        x = margin_mm * px_per_mm
        for ln in lines:
            font = _mono_font(pt * (1.25 if ln.big and len(ln.text.strip()) * 1.25 <= width_chars else 1), ln.bold)
            painter.setFont(font)
            fm = QFontMetricsF(font, printer)
            y += fm.ascent()
            if ln.center:
                painter.drawText(QRectF(0, y - fm.ascent(), paper_mm * px_per_mm, fm.height()),
                                 int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), ln.text.strip())
            else:
                painter.drawText(int(x), int(y), ln.text)
            y += fm.descent() + fm.leading() + 1
    finally:
        if not painter.end():
            log.error("painter.end() failed for %s", printer_name)


# ESC/POS raw mode -----------------------------------------------------------
ESC, GS = b"\x1b", b"\x1d"


def escpos_bytes(lines: list[Line], cut: bool = True) -> bytes:
    data = bytearray(ESC + b"@")
    for ln in lines:
        data += ESC + b"a" + (b"\x01" if ln.center else b"\x00")
        data += ESC + b"E" + (b"\x01" if ln.bold else b"\x00")
        data += GS + b"!" + (b"\x01" if ln.big else b"\x00")  # double height only, width unchanged
        text = ln.text.strip() if ln.center else ln.text
        data += text.encode("ascii", "replace") + b"\n"
    data += ESC + b"a\x00" + ESC + b"E\x00" + GS + b"!\x00" + b"\n\n\n\n"
    if cut:
        data += GS + b"V\x42\x00"
    return bytes(data)


def print_raw(printer_name: str, payload: bytes, job_name: str = "83MW receipt") -> None:
    if sys.platform != "win32":
        raise PrinterError("Raw ESC/POS printing only works on Windows. Use 'Windows driver' mode instead.")
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError:
        raise PrinterError("Raw printing support (pywin32) is not installed. Use 'Windows driver' mode.") from None
    name = printer_name or win32print.GetDefaultPrinter()
    try:
        handle = win32print.OpenPrinter(name)
    except Exception as exc:  # pywin32 raises pywintypes.error
        log.exception("OpenPrinter failed")
        raise PrinterError(f"Printer '{name}' could not be opened." + TROUBLESHOOT) from exc
    try:
        win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, payload)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    except Exception as exc:
        log.exception("raw print failed")
        raise PrinterError(f"Printing to '{name}' failed." + TROUBLESHOOT) from exc
    finally:
        win32print.ClosePrinter(handle)


def print_receipt(settings, lines: list[Line]) -> None:
    """Print using the receipt settings. Raises PrinterError with a plain message on failure."""
    from .receipt import WIDTH_CHARS

    paper = settings.get("receipt_width_mm")
    width_chars = WIDTH_CHARS.get(paper, 48)
    name = settings.get("receipt_printer")
    try:
        if settings.get("receipt_mode") == "RAW":
            print_raw(name, escpos_bytes(lines, settings.get_bool("receipt_cut")))
        else:
            print_receipt_driver(name, lines, int(paper), width_chars, settings.get_float("receipt_font_pt"))
    except PrinterError:
        raise
    except Exception as exc:
        log.exception("receipt print failed")
        raise PrinterError("The receipt could not be printed." + TROUBLESHOOT) from exc
