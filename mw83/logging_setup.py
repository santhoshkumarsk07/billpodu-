"""Technical errors go to a rotating log file; the owner only sees plain messages."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import paths

_configured = False


def setup_logging() -> logging.Logger:
    global _configured
    logger = logging.getLogger("mw83")
    if _configured:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        paths.logs_dir() / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    _configured = True
    return logger


def log_path() -> str:
    return str(paths.logs_dir() / "app.log")
