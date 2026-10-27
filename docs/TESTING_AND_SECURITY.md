# Testing and security report

Version 1.0.0. Re-run all checks with the commands at the end of this page.

## Automated tests — 86 test runs (82 test functions, some repeated for several cases), all passing

| File | Tests | What is proven |
|---|---|---|
| `tests/test_money_cart.py` | 19 | Rupee/percent parsing (rejects negative, NaN, >2 decimals), exact rounding and allocation, cart totals, item/bill discounts (% and amount), discount caps and the discount limit setting, invalid quantities, GST inclusive/exclusive, CGST+SGST, IGST, clothing slab, fixed/exempt, round-off, cash change, split payments, over/under-payment |
| `tests/test_sales_flow.py` | 28 | Product + variant creation, auto SKU and valid EAN-13 barcodes, duplicate barcode/SKU refused with nothing half-saved, archived and unknown items blocked, category delete rules, stock reduced on the exact size/colour, stock movement logged with balance, insufficient stock blocks the whole bill, sequential invoice numbers never reused (after cancel and prefix change), **database failure mid-sale rolls back everything**, **same bill saved twice creates one sale**, split payment stored, GST stored with the bill and unchanged when settings change, cancel restores stock exactly once, hold/resume, returns restore stock and cannot exceed quantity sold, refunds add up exactly, exchange credit used once, adjustments need a reason and cannot make stock negative, stock lists/valuation, refreshed product details at save, schema document up to date, packaged self-test mode, data preserved on reopen |
| `tests/test_printing_backup_reports.py` | 20 | EAN-13/Code 128 encoding, receipt fits 58 mm and 80 mm, receipt PDF, **printer failure keeps a single sale and reprint works**, unknown printer gives a clear message, ESC/POS bytes, tag rendering, **printed tag barcodes decoded back by a real barcode reader** (Code 128 and EAN-13, 203 and 300 dpi), backup → restore round trip with pictures, safety backup before restore, restore refuses non-zip / damaged / wrong / **path-traversal ("zip slip")** files, backup retention, daily/weekly/off, unwritable backup folder, CSV export/import round trip, **row-level CSV errors save nothing**, **CSV formula-injection protection**, reports from real data (sales, refunds, payments, category, profit, returns, movements), report PDF/CSV, image validation, settings validation (GSTIN, prefix, paper width) |
| `tests/test_ui_smoke.py` | 15 | The real PySide6 screens driven offscreen: opens on Billing; **simulated keyboard-wedge scanner** adds, increments and completes a bill; unknown/out-of-stock scans; +/−/Delete keys; hold/resume; split payment; every screen opens; product editor with variants and duplicate barcode; returns screen; settings validation; restore while the app is running; default customer; multi-select search; adding items by item number, style code and name (with whole-word size/colour matching); bill discount box (10 = 10%, never above 100%, owner's limit enforced, invalid discount blocks completion); stylesheet and icons load |

## Performance (3 years of data: 5,000 products, 20,000 sizes/colours, 60,000 bills, 53 MB database)

| Operation | Time |
|---|---|
| Barcode or SKU lookup (each scan) | 0.02 ms |
| Recalculate a 30-line bill | 0.6 ms |
| Save a bill (with full disk sync) | 6 ms |
| Name search across all products | 13 ms |
| Sales history for today / by barcode over 3 years | 0.3 ms / 68 ms |
| Any report over 3 years | 0.05 – 0.45 s (runs in the background; the screen never freezes) |
| Dashboard | 8 ms |

## Security and data-safety review

| Area | Measure |
|---|---|
| SQL injection | Every query uses `?` parameters. No user text is ever placed into SQL. Checked with ruff (all flake8-bandit `S` rules, including S608 SQL-string checks) and bandit: **0 findings**. |
| Data integrity | Foreign keys on; CHECK constraints (stock ≥ 0, quantities > 0, valid statuses/methods); unique barcode, SKU, invoice number; `BEGIN IMMEDIATE` transactions; WAL journal with `synchronous=FULL`. |
| Money | Integer paise only; largest-remainder allocation so discounts, taxes and refunds always add up exactly. |
| Duplicate bills | Unique per-bill token (`client_ref`), checked inside the transaction; printing only after commit. |
| Restore (zip files) | Only `shop.db`, `manifest.json` and `images/<safe-name>` allowed; path traversal, absolute paths and too-large/too-many files refused; checksum, `PRAGMA integrity_check`, required tables and version checked **before** touching live data; safety backup first; atomic file replace. |
| Product pictures | Size limit, decompression-bomb limit, opened and **re-encoded** with Pillow (only pixel data is stored), random file names, no path components accepted. |
| CSV import | Size and row limits, strict types per column, whole file validated before saving, all-or-nothing transaction. |
| CSV export | Cells starting with `= + - @` are prefixed so Excel cannot run them as formulas. |
| PDF output | Product/customer text escaped before reportlab markup. |
| Held bills | Stored as JSON, every field type-checked when resumed. |
| Errors | Owner sees plain messages; stack traces go only to a rotating log file (2 MB × 5). No passwords or payment data are stored or logged. |
| Network | The app makes **no network connections**. UPI/card are only recorded, never processed. |
| Single instance | Lock file prevents two copies writing to the same data (recovers automatically after a crash). |
| Dependencies | Pinned versions. `pip-audit`: **no known vulnerabilities** (Pillow upgraded to 13.0.0 to fix CVEs found in 12.3.0). |
| Destructive actions | No "delete all data". Confirmations for cancelling bills, deleting categories, large stock adjustments and restores (restore also requires typing RESTORE). |

## Not covered by automated tests (must be checked on the shop's devices)

* Physical receipt and tag printing with the shop's printers, drivers and paper/labels.
* The shop's barcode scanner configuration (Enter suffix, keyboard layout).
* GST rates and invoice format for the shop's registration — confirm with an accountant.
* The Windows installer itself is built and the `.exe` is self-tested on a clean Windows machine by the GitHub
  Actions workflow; install it once on the shop PC and run through the first-time setup.

## How to re-run every check

```bat
pip install -r requirements-dev.txt
python -m pytest -q
ruff check --select F,E9,B,S --per-file-ignores "tests/*:S101" mw83 tests main.py
bandit -q -r mw83 main.py
pip-audit -r requirements.txt
```
