# Installation guide

## What you need

* A Windows 11 (or Windows 10, 64-bit) computer.
* About 400 MB of free disk space for the program, plus space for your data and backups.
* Your barcode scanner, receipt printer and tag printer, with their **Windows drivers installed**
  (see [PRINTER_SETUP.md](PRINTER_SETUP.md)).
* A USB pen drive or external disk for backups (strongly recommended).

No internet connection is needed to run the app.

## Install

1. Copy `83MensWear-Setup-1.0.0.exe` to the shop computer.
2. Double-click it. If Windows SmartScreen shows "Windows protected your PC", click **More info → Run anyway**
   (the installer is not code-signed).
3. Follow the steps. Tick **Create a desktop shortcut**.
4. Click **Finish**. The app opens on the **Billing / POS** screen.

The program is installed in `C:\Program Files\83MensWear`.

## Where your data is kept

| What | Where |
|---|---|
| Shop database (products, bills, stock, customers, settings) | `%APPDATA%\83MensWear\shop.db` |
| Product pictures | `%APPDATA%\83MensWear\images` |
| Technical log (for support) | `%APPDATA%\83MensWear\logs\app.log` |
| Backups (default) | `Documents\83MensWear Backups` |
| Exported CSV/PDF files (default) | `Documents\83MensWear Exports` |

Tip: type `%APPDATA%\83MensWear` in the File Explorer address bar to open the data folder.

Uninstalling the program **does not delete** your data or backups.

## First-time setup (10 minutes)

1. **Settings → Shop**: shop name, address, phone, GSTIN (if registered), invoice prefix (default `83MW`).
2. **Settings → Billing & GST**: default payment method, discount limit, automatic printing, GST options
   (see the user manual). Click **Save settings**.
3. **Settings → Printers**: choose the receipt printer and paper width, the tag printer and tag size.
   Click **Test print** for each.
4. **Settings → Backup**: choose a backup folder (ideally on a USB drive) and keep "Every day".
5. **Products**: add your products (or import a CSV — *Download CSV template* shows the columns).
   Enter the opening stock for each size/colour.
6. **Barcode & Tags**: print tags and stick them on the garments.
7. Scan a tag on the **Billing** screen to check everything works end to end.

## Updating to a new version

1. Make a backup (**Backup & Restore → Backup now**).
2. Close the app and run the new installer. Your data is kept; the database is upgraded automatically and a
   copy of the old database is saved next to it as `shop-before-upgrade-vN.db`.

## Moving to a new computer

1. On the old computer: **Backup & Restore → Backup now**, copy the backup `.zip` to a USB drive.
2. On the new computer: install the app, then **Backup & Restore → Restore from another file…** and choose the
   `.zip`. Then set up printers again in **Settings → Printers** (printer names differ per computer).

## Building from source (for a technician)

```bat
git clone <repository>
cd <repository>
build.bat
```

`build.bat` creates a virtual environment, installs pinned dependencies, runs the tests, builds
`dist\83MensWear\83MensWear.exe` with PyInstaller, and — if Inno Setup 6 is installed — builds the installer in
`dist\`. The GitHub Actions workflow `.github/workflows/windows-build.yml` does the same on a clean Windows
machine and also runs `83MensWear.exe --self-test`.
