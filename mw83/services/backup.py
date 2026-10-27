"""Backups are zip files holding a consistent copy of the database, the product
images and a manifest. Restore validates everything before touching live data
and always takes a safety backup first."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .. import APP_NAME, APP_VERSION, paths
from ..db import Database, today_str
from ..db.migrations import LATEST_VERSION
from ..errors import UserError
from .settings import Settings

log = logging.getLogger("mw83.backup")

PREFIX = "83MW-backup-"
NAME_RE = re.compile(r"^83MW-backup-\d{8}-\d{6}(?:-\d+)?(?:-[a-z-]+)?\.zip$")
IMAGE_NAME_RE = re.compile(r"^images/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}$")
REQUIRED_TABLES = {"settings", "products", "variants", "sales", "sale_items", "sale_payments", "stock_movements",
                   "customers", "returns"}
MAX_UNCOMPRESSED = 4 * 1024 ** 3
MAX_MEMBERS = 200_000


class BackupError(UserError):
    def __init__(self, message: str):
        super().__init__(message, "Backup problem")


class RestoreError(UserError):
    def __init__(self, message: str):
        super().__init__(message, "Restore problem")


def backup_dir(settings: Settings) -> Path:
    chosen = settings.get("backup_dir").strip()
    return Path(chosen) if chosen else paths.default_backup_dir()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(db: Database, dest_dir: str | Path, tag: str = "") -> Path:
    dest = Path(dest_dir)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"Cannot create the backup folder {dest}.\n{exc.strerror or exc}") from None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{PREFIX}{stamp}" + (f"-{tag}" if tag else "") + ".zip"
    counter = 1
    while (dest / name).exists():
        name = f"{PREFIX}{stamp}-{counter}" + (f"-{tag}" if tag else "") + ".zip"
        counter += 1
    final = dest / name
    part = dest / (name + ".part")
    with tempfile.TemporaryDirectory(prefix="mw83-bk-") as tmp:
        copy = Path(tmp) / "shop.db"
        try:
            target = sqlite3.connect(str(copy))
            with target:
                db.conn.backup(target)  # consistent snapshot even while the app is running
            ok = target.execute("PRAGMA integrity_check").fetchone()[0]
            target.close()
            if ok != "ok":
                raise BackupError("The database failed its integrity check. Contact support before continuing.")
            manifest = {
                "app": APP_NAME, "app_version": APP_VERSION, "schema_version": db.schema_version(),
                "created_at": datetime.now().isoformat(timespec="seconds"), "db_sha256": _sha256(copy),
            }
            with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(copy, "shop.db")
                images = paths.images_dir()
                for img in sorted(images.iterdir()):
                    if img.is_file() and IMAGE_NAME_RE.match("images/" + img.name):
                        zf.write(img, "images/" + img.name)
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            os.replace(part, final)
        except OSError as exc:
            part.unlink(missing_ok=True)
            log.exception("backup failed")
            raise BackupError(f"Backup could not be written to {dest}.\n"
                              f"{exc.strerror or exc}\nCheck the drive is connected and has free space.") from None
        except sqlite3.Error:
            part.unlink(missing_ok=True)
            log.exception("backup failed")
            raise BackupError("Backup failed while copying the database. See the log file for details.") from None
    log.info("backup written: %s", final)
    return final


def list_backups(dest_dir: str | Path) -> list[Path]:
    d = Path(dest_dir)
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.is_file() and NAME_RE.match(p.name)),
                  key=lambda p: p.name, reverse=True)


def prune_backups(dest_dir: str | Path, keep: int) -> list[Path]:
    """Delete the oldest backups beyond `keep`. Safety copies made before a restore are kept."""
    keep = max(1, int(keep))
    regular = [p for p in list_backups(dest_dir) if "before-restore" not in p.name]
    removed = []
    for p in regular[keep:]:
        try:
            p.unlink()
            removed.append(p)
        except OSError:
            log.warning("could not delete old backup %s", p)
    return removed


def auto_backup_if_due(db: Database, settings: Settings) -> Path | None:
    if not settings.get_bool("auto_backup") or settings.get("last_auto_backup") == today_str():
        return None
    path = create_backup(db, backup_dir(settings), "auto")
    settings.set("last_auto_backup", today_str())
    prune_backups(backup_dir(settings), settings.get_int("backups_to_keep"))
    return path


def manual_backup(db: Database, settings: Settings) -> Path:
    path = create_backup(db, backup_dir(settings))
    prune_backups(backup_dir(settings), settings.get_int("backups_to_keep"))
    return path


# ------------------------------------------------------------------ restore
def _safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise RestoreError("This backup has too many files and is not a valid 83 MEN'S WEAR backup.")
    total = 0
    for info in infos:
        name = info.filename
        if info.is_dir() and name == "images/":
            continue
        if name not in ("shop.db", "manifest.json") and not IMAGE_NAME_RE.match(name):
            raise RestoreError(f"This backup contains an unexpected file ('{name[:60]}'). It was not restored.")
        total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise RestoreError("This backup is too large to be valid.")
    return infos


def validate_backup(path: str | Path, extract_to: str | Path | None = None) -> dict:
    """Check a backup file thoroughly. Optionally extract it (safely) to a folder."""
    p = Path(path)
    if not p.is_file():
        raise RestoreError("Backup file not found.")
    if not zipfile.is_zipfile(p):
        raise RestoreError("This is not a backup file (it is not a .zip made by this app).")
    with tempfile.TemporaryDirectory(prefix="mw83-rs-") as tmp:
        out = Path(extract_to) if extract_to else Path(tmp)
        out.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(p) as zf:
                infos = _safe_members(zf)
                names = {i.filename for i in infos}
                if "shop.db" not in names or "manifest.json" not in names:
                    raise RestoreError("This zip is not an 83 MEN'S WEAR backup (database or manifest missing).")
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                if not isinstance(manifest, dict):
                    raise RestoreError("Backup manifest is damaged.")
                for info in infos:
                    if info.is_dir():
                        continue
                    target = (out / info.filename).resolve()
                    if out.resolve() not in target.parents:
                        raise RestoreError("Backup contains an unsafe file path. It was not restored.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except (zipfile.BadZipFile, ValueError, KeyError, UnicodeDecodeError):
            raise RestoreError("The backup file is damaged and cannot be read.") from None
        db_file = out / "shop.db"
        if manifest.get("db_sha256") and _sha256(db_file) != manifest["db_sha256"]:
            raise RestoreError("The backup's database does not match its checksum. The file may be damaged.")
        try:
            conn = sqlite3.connect(db_file.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RestoreError("The database inside the backup is damaged.")
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 fixed names
                          for t in ("products", "sales", "customers") if t in tables}
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            raise RestoreError("The file inside the backup is not a valid database.") from None
        missing = REQUIRED_TABLES - tables
        if missing:
            raise RestoreError("This backup is missing required data tables: " + ", ".join(sorted(missing)))
        if version > LATEST_VERSION:
            raise RestoreError("This backup was made by a newer version of the app. Please update the app first.")
        manifest["counts"] = counts
        manifest["schema_version"] = version
        return manifest


def restore_backup(db: Database, settings: Settings, path: str | Path) -> Path:
    """Replace current data with the backup. Returns the path of the safety backup taken first."""
    data = paths.data_dir()
    staging = Path(tempfile.mkdtemp(prefix="restore-", dir=data))
    try:
        validate_backup(path, staging)
        safety = create_backup(db, backup_dir(settings), "before-restore")
        live = db.path
        new_db = staging / "shop.db"
        db.close()
        try:
            for suffix in ("-wal", "-shm"):
                Path(str(live) + suffix).unlink(missing_ok=True)
            os.replace(new_db, live)
            images = paths.images_dir()
            old_images = data / "images-old"
            shutil.rmtree(old_images, ignore_errors=True)
            os.replace(images, old_images)
            new_images = staging / "images"
            if new_images.is_dir():
                os.replace(new_images, images)
            else:
                images.mkdir()
            shutil.rmtree(old_images, ignore_errors=True)
        except OSError as exc:
            log.exception("restore swap failed")
            raise RestoreError(f"Restore could not finish: {exc.strerror or exc}.\n"
                               f"Your data before the restore is saved in:\n{safety}") from None
        finally:
            db.reopen()
            settings.invalidate()
        log.info("restored backup %s (safety copy %s)", path, safety)
        return safety
    finally:
        shutil.rmtree(staging, ignore_errors=True)
