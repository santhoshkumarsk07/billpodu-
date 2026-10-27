"""Where the application keeps its data on disk.

On Windows everything lives under %APPDATA%\\83MensWear (never a temp folder).
Default backups go to Documents\\83MensWear Backups so that they survive an
uninstall. MW83_DATA_DIR overrides the data folder (used by tests).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "83MensWear"


def data_dir() -> Path:
    override = os.environ.get("MW83_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_FOLDER
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_FOLDER
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "shop.db"


def images_dir() -> Path:
    p = data_dir() / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_backup_dir() -> Path:
    override = os.environ.get("MW83_BACKUP_DIR")
    if override:
        return Path(override)
    return Path.home() / "Documents" / "83MensWear Backups"


def exports_dir() -> Path:
    p = Path.home() / "Documents" / "83MensWear Exports"
    return p


def resource_path(relative: str) -> Path:
    """Path to a bundled read-only resource (works inside PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
