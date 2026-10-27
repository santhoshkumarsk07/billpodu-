# User manual — 83 MEN'S WEAR Billing & Inventory

The app opens on **Billing / POS**. Use the menu on the left to move between screens. Press **F1** from anywhere
to come back to Billing.

---

## 1. Making a bill (Billing / POS)

### Fast keyboard workflow

1. **Scan** each tag. The item is added; scanning the same size/colour again adds 1 to its quantity.
   The scan box stays ready for the next scan — no clicking needed.
   No barcode? Type into the same box and press **Enter**:
   * the **item no.** (shown in the *Item no.* column of Inventory and Search, e.g. `25`),
   * the **SKU** or style code (e.g. `MW000012`),
   * or the **product name** — e.g. `cotton shirt l black`. If one item matches it is added; if several match,
     a list opens so you can pick the size/colour with ↑/↓ and Enter.
2. To give a bill discount, press **F5** and type the number: **10 means 10% off** the whole bill (from 0 to 100).
   Change "% off" to "Rs. off" for a rupee amount. The box turns red and the bill cannot be completed if the
   discount is not allowed (more than 100%, more than the bill, or above the limit in Settings).
3. Press **F9** and type the cash received (or leave it empty for exact cash).
4. Press **F12**. The bill is saved and the receipt prints (if automatic printing is on).
5. The "Bill saved" window shows the **change to give**. Press **Enter** to print, or **Esc** for the next bill.

### Keys

| Key | Action |
|---|---|
| F2 | Go to the scan box |
| F3 | Search a product by name / brand / size / colour / item no. / SKU |
| F4 | Choose or add a customer |
| F5 | Bill discount box (type 10 = 10% off) |
| F6 | Discount on the selected item |
| F7 | Hold this bill |
| F8 | Resume a held bill |
| F9 | Go to payment |
| F12 or Ctrl+Enter | Complete the bill |
| Ctrl+N | New bill |
| Ctrl+P | Reprint the last bill (marked DUPLICATE) |
| + / − | Increase / decrease quantity of the selected item (when the scan box is empty) |
| Delete | Remove the selected item (when the scan box is empty) |
| ↑ / ↓ | Move between items (when the scan box is empty) |

### Messages while scanning

A red bar under the scan box tells you about problems without stopping you:

* **No product found** — nothing matches the barcode, item no., SKU or name. Check the spelling or press F3.
* **Out of stock** — stock is 0. Receive stock in Inventory first.
* **Archived** — the product was archived; restore it in Products if you still sell it.
* **Only N in stock** — you cannot sell more than you have.

### Discounts

* **Item discount (F6)**: choose *Percentage* or *Amount*. The amount is for the whole line (all pieces).
* **Bill discount (F5)**: in the *Discount & payment* box. Type `10` for 10% off (0–100 only), or switch to
  "Rs. off" for an amount. Applied after item discounts; you can type a reason.
* A discount can never be more than the amount, and the total discount cannot exceed the limit set in
  **Settings → Billing & GST → Maximum discount**.

### Payment

* **Cash**: type the amount received; the change is shown. Leave it empty for exact cash.
* **UPI / Card**: type the amount and optionally the reference number. The app only **records** the payment —
  it does not take money electronically. Check the payment on your UPI app / card machine.
* **Split payment**: type the UPI or card part; whatever is left is cash.
* **Exchange credit**: choose a credit created by an exchange return (see Returns).

### Hold and resume

Press **F7** to keep a bill aside (e.g. the customer is trying another size). Give it a name. Press **F8** to bring
it back. Held bills are saved in the database, so they survive closing the app.

### Cancel the current bill

**Cancel bill** clears the unsaved bill after asking you. Nothing is recorded because nothing was saved.

### If the printer fails

The bill is **already saved**. Fix the printer, then press **Print again** in the "Bill saved" window, or
**Ctrl+P**, or reprint from **Sales History**. Pressing Complete again will never create a second bill.

### GST on a bill

When GST is enabled, local sales use CGST + SGST. For a customer from another state, tick
**Customer from another state (IGST)** and choose their state.

---

## 2. Products

* **Add product**: name, category, brand, selling price, MRP, purchase cost, low-stock level, HSN, GST option.
* **Sizes / colours**: each row is one sellable item with its own SKU, barcode and stock. For a product without
  sizes, leave Size and Colour blank. Leave SKU/Barcode empty and the app creates them (barcodes are valid
  EAN-13 numbers starting with 2, for in-store use).
* **Add sizes…** adds several sizes in one go (e.g. `S, M, L, XL` in Black).
* **Price / MRP / Cost** columns on a size row are only needed if that size has a different price.
* **Opening stock** is used only when a row is first saved. After that, change stock in **Inventory** so every
  change is recorded.
* **Duplicate barcodes or SKUs are refused** with a message saying which product already uses it.
* **Archive** hides a product from billing. Old bills are not affected. Products are never deleted.
* **Picture**: open a saved product and click *Choose picture* (JPG or PNG).

### CSV import / export

* **Download CSV template** to see the columns. One row per size/colour; rows with the same product name,
  category and brand become one product.
* The whole file is checked first. If any row has a problem, **nothing is imported** and you see a list like
  `Row 4: Duplicate barcode …`. Fix the rows and import again.
* Missing categories are created automatically.

## 3. Categories

Add, rename or delete categories. A category used by any product cannot be deleted (move those products first).

## 4. Barcode & Tags

1. **Add items…** — choose one or many sizes/colours (Ctrl+click to choose several).
2. Set **how many tags** per item (double-click), or **Tags = stock for all**.
3. Check the **preview** (shown at the real tag size).
4. **Test print** first, then **Print all** or **Print selected**.
5. **Reprint an earlier tag job** from the list at the bottom.

Tag layout: width, height, margin, font, barcode type and which fields to show (shop name, product, size, colour,
SKU, MRP, price). **Save as default layout** to keep it. *Code 128* works for every code; *EAN-13* is used only
when the code is a valid 13-digit EAN.

Printing tags never changes stock or prices.

## 5. Inventory

* **Current stock** — search, show *Low stock* or *Out of stock*, filter by category. The top line shows total
  pieces and stock value at cost and at selling price.
* **Receive stock…** — add new stock (enter supplier / bill no. as a note).
* **Damaged / lost / adjust…** — reduce stock for damaged or lost items, or correct the stock after counting
  (*Set to counted quantity*). A **reason is required** and you confirm before saving; large changes show a
  stronger warning.
* **Stock movement history** — every change with date, type, quantity, new stock, bill number or reason.

## 6. Customers

Add, edit, search by name or phone, see purchase history (double-click a bill to open it), archive. The
**Walk-in Customer** is used when you don't choose one — no name or phone needed.

## 7. Sales History

Search by bill number, dates, customer, product, barcode/SKU, payment method and status. Open a bill to:

* **Reprint receipt** (marked DUPLICATE) or **Save PDF**.
* **Return / exchange** — opens the Returns screen for that bill.
* **Cancel bill** — for a wrong bill. You must give a reason and confirm. Stock is added back, the bill stays in
  history marked CANCELLED, and its number is never reused. Bills with returns cannot be cancelled.

Completed bills cannot be edited.

## 8. Returns & Exchanges

1. Type or scan the **original bill number** and press Enter.
2. Enter the **return quantity** for each item (you cannot return more than was sold, minus earlier returns).
3. Untick **Sellable** for damaged items — they will not go back into stock.
4. Choose the **reason** and how to refund: **Cash, UPI, Card** or **Exchange**.
5. **Save return**. The refund includes the original discounts and GST.

**Exchange**: after saving, go to Billing, scan the replacement items, and choose the credit under
**Payment → Exchange credit**. If the new items cost more, the customer pays the difference. The credit cannot be
more than the new bill — add items or refund in cash instead. A credit can be used once.

## 9. Reports

Choose a report and dates, then **Show report**. Export with **CSV** (opens in Excel) or **PDF**.

* Daily / Monthly sales — bills, items, gross, discount, tax, sales, refunds, net.
* Sales by category, Top-selling products, Payment-method summary.
* Low-stock report, Stock movement report, Return report.
* **Profit estimate** — sales before GST minus purchase cost of items sold. It is an estimate: it ignores rent,
  salaries and other expenses.

Cancelled bills are not counted as sales. Returns count on the day they were made.

## 10. Settings

* **Shop**: name, address, phone, GSTIN, invoice prefix, financial year (optional — adds e.g. `2026-27` to bill
  numbers), receipt thank-you and return-policy lines.
* **Billing & GST**: default payment, default customer, maximum discount, automatic receipt printing, rounding to
  the nearest rupee, GST on/off, shop state, prices include / exclude GST, default rate, clothing slab.
* **Printers**: receipt printer, paper width, mode, font size, paper cut, tag printer, tag size, test prints.
* **Inventory**: default low-stock quantity, confirmation for adjustments, "large adjustment" warning level.
* **Backup**: folder, frequency (daily/weekly/off), number of backups to keep.

### GST — please read

* Turn GST on only if your shop is GST-registered.
* **Prices include GST** (usual for MRP retail): the price on the tag is what the customer pays; the app works out
  the tax inside it. **GST added on top**: tax is added to the price.
* Per product you can choose: *Default rate*, *Fixed rate*, *Clothing slab* (rate depends on the price per piece —
  enter the limit and the two rates in Settings) or *No GST*.
* Rates and rules change. Confirm the rates, HSN codes and invoice wording with your accountant. The app does
  **not** file GST returns, generate e-invoices or e-way bills, and is not GST-certified software.

## 11. Backup & Restore

See [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md).

## 12. Problems?

* Every error message says what to do. Technical details are written to
  `%APPDATA%\83MensWear\logs\app.log` — send this file to your technician.
* If the app says it is already open, look for it on the taskbar.
