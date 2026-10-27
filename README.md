# 83 MEN'S WEAR — Billing & Inventory (offline, Windows 11)

A simple, fast, fully offline desktop billing (POS) and inventory application for one shop owner on one
Windows computer. No login, no internet, no cloud, no subscription.

Built with Python 3.11+, PySide6 (Qt), SQLite, python-barcode, reportlab and Pillow.

## What it does

| Screen | What you can do |
|---|---|
| **Billing / POS** (opens first) | Scan barcodes (scanner works like a keyboard), or type an item number, SKU or product name in the same box, change quantity, item and bill discounts (type 10 = 10% off, never above 100%), walk-in or saved customer, cash / UPI / card / split payment with change due, exchange credit, hold & resume bills, cancel the current bill, save & print, reprint |
| **Dashboard** | Today's sales, bills, items, cash/UPI/card collected, discounts, refunds, low-stock count, stock value |
| **Products** | Products with size/colour variants (each with own SKU, barcode, stock and optional price), MRP, cost, GST option, HSN, picture, archive, CSV import/export with row-level errors |
| **Categories** | Add, rename, delete (only when unused) — men's wear categories are pre-filled |
| **Barcode & Tags** | Code 128 / EAN-13 tags, live preview at real size, single/bulk printing, tags = stock, reprint earlier jobs, test print |
| **Inventory** | Stock per size/colour, low/out-of-stock, receive stock, damaged/lost/adjustment with reason and confirmation, full stock movement history, stock valuation |
| **Customers** | Add, edit, search by name/phone, purchase history, archive |
| **Sales History** | Search by bill no, dates, customer, product, barcode/SKU, payment method, status; view, reprint, PDF, cancel (with reversal), start a return |
| **Returns** | Return against the original bill, limits to quantity sold, refund by cash/UPI/card or exchange credit, damaged items not restocked |
| **Reports** | Daily, monthly, by category, top products, payment summary, low stock, stock movements, returns, profit estimate — CSV and PDF export |
| **Settings** | Shop details, invoice prefix, GST, billing defaults, printers, inventory, backup |
| **Backup & Restore** | Backup now, automatic daily/weekly backup, keep N backups, validated restore with a safety backup first |

## Data safety rules built into the code

* Money is stored as **integer paise**, never floating point.
* A bill is saved in **one database transaction** (items, payments, stock, invoice number). If anything fails,
  nothing is saved.
* **Printing happens only after the bill is saved.** A printer failure never creates a duplicate bill; each bill
  carries a unique token so pressing *Complete* twice saves it once. Reprint any time.
* **Invoice numbers** (e.g. `83MW-0001`) are sequential and never reused — not even after a cancellation.
* Completed bills are **never edited or deleted**. Cancelling records a reason and restores stock through
  stock movements. Returns are separate records.
* **Stock only changes through logged stock movements**, and can never go below zero (database constraint).
* Products used in bills are **archived, not deleted**. There is no "delete all data" button.
* Each bill stores a snapshot of product names, prices, discounts and GST so old bills never change.

## Quick start (development)

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python main.py
```

Data is stored in `%APPDATA%\83MensWear` (database, product pictures, logs). Backups go to
`Documents\83MensWear Backups` by default.

## Tests and checks

```bat
python -m pytest -q
ruff check --select F,E9,B,S --per-file-ignores "tests/*:S101" mw83 tests main.py
bandit -q -r mw83 main.py
pip-audit -r requirements.txt
```

The tests cover products and variants, barcode/SKU uniqueness, cart maths, discounts, GST (inclusive, exclusive,
CGST/SGST, IGST, clothing slab), stock reduction and restoration, invoice numbering, payments and split payments,
returns and exchanges, backup and restore (including malicious zip files), CSV import/export, reports, printer
failure without duplicate sales, scannability of printed barcodes, and the real UI driven by a simulated scanner.
See [docs/TESTING_AND_SECURITY.md](docs/TESTING_AND_SECURITY.md).

## App icon

The 83 MEN'S WEAR icon (`assets/app.ico`, used for the program, desktop shortcut, taskbar and installer) is drawn
by `python packaging/icon/make_icon.py`.

## Build the Windows program and installer

Run `build.bat` on Windows (needs Python 3.11+; Inno Setup 6 for the installer). Or push to GitHub: the
**Windows build** workflow tests, builds, self-tests the `.exe` and uploads `83MensWear-Setup-x.y.z.exe`.

## Documentation

* [Installation guide](docs/INSTALLATION.md)
* [User manual](docs/USER_MANUAL.md)
* [Printer and scanner setup](docs/PRINTER_SETUP.md)
* [Backup and recovery](docs/BACKUP_AND_RECOVERY.md)
* [Testing and security report](docs/TESTING_AND_SECURITY.md)
* [Database schema](docs/schema.sql)

## Project layout

```
main.py                    start the app
mw83/
  app.py                   start-up, error handling, single-instance lock, --self-test
  paths.py                 data, image, log and backup folders
  money.py                 paise parsing/formatting, exact allocation
  db/                      SQLite connection, transactions, migrations (schema)
  services/                business logic: cart & GST, sales, returns, catalog, inventory,
                           customers, reports, backup, CSV, settings
  printing/                receipt layout, ESC/POS, Windows-driver printing, tags, barcodes, PDF
  ui/                      PySide6 screens (ui/pages/*), dialogs, styles
tests/                     pytest suite
packaging/                 PyInstaller spec and Inno Setup installer script
docs/                      guides and schema
```

## Must be tested on the shop's real devices

These depend on hardware and cannot be fully proven in software:

1. **Receipt printer** — paper width (58/80 mm), driver vs raw ESC/POS mode, paper cut. Use *Settings → Printers →
   Test print*.
2. **Tag printer** — label size, gap/black-mark settings in the Windows driver, and that the printed barcode scans.
   Use *Barcode & Tags → Test print*.
3. **Barcode scanner** — must send Enter (CR) after each code. Scan a few tags into the Billing screen.
4. **GST** — rates, the clothing slab, and invoice wording must be confirmed with your accountant. The app does
   not file returns or create e-invoices.
