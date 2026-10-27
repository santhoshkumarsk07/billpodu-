# Backup and recovery guide

Your bills, stock, products and customers exist only on this computer. A computer can be stolen, a disk can fail.
**Backups are the only protection.**

## What a backup contains

One `.zip` file named like `83MW-backup-20261027-183005.zip` containing:

* `shop.db` — a consistent copy of the whole database (taken safely even while the app is running),
* `images/` — product pictures,
* `manifest.json` — app version, date and a checksum used to detect damaged files.

## Automatic backups

* **Settings → Backup → Automatic backup**: *Every day* (default), *Every week* or *Off*.
* The app makes the backup within a minute of starting and checks every hour while it is open; it also makes one
  when you close the app if one is due.
* Old backups beyond **Number of backups to keep** (default 30) are deleted automatically, oldest first.
  Safety copies made before a restore are never deleted automatically.
* If an automatic backup fails, you see a warning and the status bar shows "Automatic backup FAILED".
  Billing keeps working.

## Manual backup

**Backup & Restore → Backup now**. Do this before updating the app, before big changes (e.g. CSV import) and at
the end of each day if you don't use automatic backups.

## Where to keep backups (the 3-2-1 rule)

* Set the backup folder (**Settings → Backup → Change…**) to a **USB drive or external disk** that stays
  connected, or
* keep the default folder (`Documents\83MensWear Backups`) and **copy the newest backup to a pen drive every
  week** and keep that pen drive at home.
* Optionally also copy backups to your own Google Drive/OneDrive by hand. The app itself never uploads anything.

## Restore

Restoring **replaces all current data** with the backup.

1. **Backup & Restore** → choose a backup in the list → **Restore selected backup…**
   (or **Restore from another file…** for a backup on a pen drive).
2. The app **checks the file first**: it must be a real 83 MEN'S WEAR backup, not damaged (database integrity
   check and checksum), with all required tables, and not from a newer app version. Unsafe zip files are refused.
3. You see what the backup contains (date, products, bills, customers) and a warning. Confirm, then type
   `RESTORE`.
4. The app first saves a **safety backup** of the current data (`…-before-restore.zip`), then restores.
5. Check a few recent bills and stock levels.

If you restored the wrong backup, restore the `…-before-restore.zip` file to go back.

## Recovery scenarios

| Situation | What to do |
|---|---|
| Computer replaced / Windows reinstalled | Install the app, then *Restore from another file…* with the newest backup from your pen drive. Set up printers again. |
| "Cannot open data" when starting | Do **not** delete anything. Copy the whole `%APPDATA%\83MensWear` folder to a pen drive, then restore the newest backup. Send `logs\app.log` to your technician. |
| Accidental wrong stock change | Don't restore — record a correcting adjustment in Inventory with a reason (history is kept). |
| Wrong bill | Cancel it in Sales History (with a reason) and make a new one. Don't restore. |
| App update went wrong | A copy of the database from before the upgrade is saved next to it as `shop-before-upgrade-vN.db`; your technician can use it. Or restore the backup made before updating. |

## Uninstalling

Uninstalling removes only the program. Your data folder (`%APPDATA%\83MensWear`) and backups are **kept**. Delete
them by hand only if you are sure you never need the data again.

## Monthly check (2 minutes)

1. Open **Backup & Restore** and confirm there is a backup from today or yesterday.
2. Copy the newest backup to your pen drive.
3. Once a year, test a restore on another computer (install the app there and restore the backup).
