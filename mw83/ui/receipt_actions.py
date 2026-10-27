"""Print / reprint / save PDF for a saved bill. These never modify the sale."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

from .. import paths
from ..errors import PrinterError
from ..printing import printers
from ..printing.pdf import receipt_pdf
from ..printing.receipt import WIDTH_CHARS, build_receipt
from ..services import sales
from .common import AppContext, info, run_safely, show_error

SHOP_KEYS = ("shop_name", "shop_address", "shop_phone", "shop_gstin", "receipt_footer", "return_policy")


def shop_info(ctx: AppContext) -> dict:
    return {k: ctx.settings.get(k) for k in SHOP_KEYS}


def receipt_lines(ctx: AppContext, sale_id: int, duplicate: bool):
    sale = sales.get_sale(ctx.db, sale_id)
    width = WIDTH_CHARS.get(ctx.settings.get("receipt_width_mm"), 48)
    return sale, build_receipt(sale, shop_info(ctx), width, duplicate=duplicate)


def print_sale(ctx: AppContext, sale_id: int, parent: QWidget, duplicate: bool = False, quiet: bool = False) -> bool:
    """Print a receipt. Returns True on success. The sale stays saved whatever happens."""
    try:
        sale, lines = receipt_lines(ctx, sale_id, duplicate)
        printers.print_receipt(ctx.settings, lines)
        return True
    except PrinterError as exc:
        if not quiet:
            show_error(parent, PrinterError(
                f"{exc.message}\n\nThe bill is saved. You can reprint it any time from Billing (Ctrl+P) "
                "or Sales History."))
        return False
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            show_error(parent, exc, "printing the receipt")
        return False


def save_sale_pdf(ctx: AppContext, sale_id: int, parent: QWidget) -> Path | None:
    def work():
        sale, lines = receipt_lines(ctx, sale_id, duplicate=False)
        out_dir = paths.exports_dir() / "Invoices"
        out_dir.mkdir(parents=True, exist_ok=True)
        default = str(out_dir / f"{sale['invoice_no'].replace('/', '-')}.pdf")
        target, _ = QFileDialog.getSaveFileName(parent, "Save receipt as PDF", default, "PDF files (*.pdf)")
        if not target:
            return None
        paper = int(ctx.settings.get("receipt_width_mm") or 80)
        return receipt_pdf(lines, target, paper, WIDTH_CHARS.get(str(paper), 48))

    path = run_safely(parent, work, "saving the PDF")
    if path:
        info(parent, "PDF saved", f"Saved:\n{path}")
    return path
