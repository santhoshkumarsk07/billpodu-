# Printer and scanner setup

The app prints through the **printer drivers installed in Windows**. It does not include drivers. Every printer
model is different, so **test on your own printers** using the steps below. Write the printer models here once
known:

| Device | Model | Connection | Notes |
|---|---|---|---|
| Receipt printer | _to be filled_ | USB / LAN | 58 or 80 mm |
| Tag printer | _to be filled_ | USB | label size |
| Barcode scanner | _to be filled_ | USB | keyboard mode |

---

## 1. Barcode scanner

Most USB scanners work like a keyboard — no driver needed.

1. Plug in the scanner. Open Notepad and scan a tag: the number should appear **and the cursor should move to
   the next line**. That means the scanner sends **Enter** after each code, which the app needs.
2. If the cursor does not move to a new line, scan the "Add CR suffix" / "Enter suffix" setup barcode in the
   scanner's manual.
3. If letters come out wrong (e.g. `@` instead of `"`), set the scanner's keyboard language to **US English**
   (from the manual) and make sure Windows is using the English (US or India) keyboard.
4. In the app, go to **Billing** and scan a tag. The item should be added and the scan box cleared.

## 2. Receipt printer (58 mm or 80 mm thermal)

1. Install the manufacturer's Windows driver. In **Windows Settings → Bluetooth & devices → Printers & scanners**,
   open the printer and click **Print test page**. Fix any problem here first.
2. In the driver's **Printing preferences**, set the paper to the roll size (e.g. *80mm × Receipt* or
   *72mm × 297mm*), and turn on auto-cut if available.
3. In the app: **Settings → Printers**
   * **Receipt printer** — choose it (or "Windows default printer").
   * **Receipt paper width** — 80 mm (48 characters per line) or 58 mm (32 characters).
   * **Print mode** — start with **Windows printer driver**.
   * Click **Test print**. Every line, including the line of digits, should fit without being cut off.
4. If text is too small or large, change **Receipt font size**. The app shrinks the font automatically if a line
   would not fit.

### When to use "Raw ESC/POS text" mode

Some thermal printers print blank pages, print very slowly, or leave a long blank strip with the driver.
Choose **Raw ESC/POS text**. The app then sends plain text with ESC/POS commands (bold, centre, cut) straight to
the printer. Tick **Cut paper after receipt** if your printer has a cutter. Raw mode needs the printer to
understand ESC/POS (most Epson-compatible thermal printers do) and only prints basic characters ("Rs." is used
instead of the ₹ sign).

### Troubleshooting receipts

| Problem | Fix |
|---|---|
| "Printer '…' was not found" | The printer was renamed or removed. Choose it again in Settings → Printers. |
| Nothing prints, no error | Check the Windows print queue; try "Print test page" from Windows; try Raw mode. |
| Text cut on the right | Choose the correct paper width; lower the font size. |
| Long blank paper after receipt | Set the paper size in the driver to the receipt/roll size, or use Raw mode. |
| Printer was off during a sale | The bill is saved. Turn the printer on and press Ctrl+P (reprint last bill). |

## 3. Tag / label printer (barcode tags)

1. Install the Windows driver (for example from the printer maker's website, or a "Seagull"/BarTender driver
   for many label printers). Print a Windows test page.
2. In the driver's **Printing preferences** create/choose a **label stock** that matches your labels:
   width × height (e.g. 50 × 25 mm), **gap** (or black mark) sensing, and the correct darkness/speed.
   Calibrate the printer (most have a button or a "calibrate" option in the driver) so it stops at each label.
3. In the app: **Barcode & Tags**
   * Set **Width** and **Height** to the label size, choose the **Tag printer**.
   * Choose which fields to show; check the **preview**.
   * **Test print**. Then **scan the printed test tag** with your scanner on the Billing screen or in Notepad —
     it must read `2000000000015`.
   * **Save as default layout**.
4. Tips for reliable scanning: keep tags at least 38 mm wide for long codes; if bars look smudged, lower the
   darkness or speed in the driver; leave Code 128 selected unless all your barcodes are valid EAN-13.

The app draws barcode bars on whole printer dots so they stay sharp at 203 and 300 dpi. Before release, printed
barcodes were decoded automatically with a barcode reader in testing at 203 and 300 dpi (Code 128 and EAN-13).

### Troubleshooting tags

| Problem | Fix |
|---|---|
| Prints across two labels / skips labels | Set the label size and gap in the driver; calibrate the printer. |
| Barcode does not scan | Increase tag width, use a shorter barcode, reduce darkness, check scanner suffix/keyboard setup. |
| "Tag is too small for this text and a barcode" | Increase height, reduce font size or hide some fields. |
| "Barcode is too long for a … mm wide tag" | Use a wider tag or a shorter code. |

## What must be tested on your real devices

Software tests cannot prove that a particular printer, driver and label stock work together. Before relying on
the system, do this once:

1. Receipt test print (Settings → Printers) at your paper width; a real sale with automatic printing.
2. Turn the receipt printer off, complete a sale, check the "not printed" message, turn it on, reprint.
3. Tag test print; scan the test tag; print and scan a real product tag; sell it by scanning.
4. Fill in the device table at the top of this page.
