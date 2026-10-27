"""SQLite access. Every query is parameterised; never build SQL from user text."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import migrations

log = logging.getLogger("mw83.db")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def connect(path: str | Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False, timeout=10)
    else:
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
    return conn


class Database:
    """One connection for the UI thread. Report threads open their own read-only connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = connect(self.path)
        self._depth = 0
        migrations.migrate(self)

    # -- transactions -------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any error. Nested calls join the outer one."""
        if self._depth > 0:
            self._depth += 1
            try:
                yield self.conn
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield self.conn
        except BaseException:
            self._depth = 0
            try:
                self.conn.execute("ROLLBACK")
            except sqlite3.Error:
                log.exception("rollback failed")
            raise
        else:
            self._depth = 0
            self.conn.execute("COMMIT")

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    # -- helpers ------------------------------------------------------------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = (), default: Any = None) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return default if row is None or row[0] is None else row[0]

    def next_sequence(self, name: str) -> int:
        """Atomically take the next number of a counter. Must run inside a transaction."""
        if not self.in_transaction:
            raise RuntimeError("next_sequence must be called inside a transaction")
        self.conn.execute("INSERT OR IGNORE INTO sequences(name, value) VALUES (?, 0)", (name,))
        self.conn.execute("UPDATE sequences SET value = value + 1 WHERE name = ?", (name,))
        return int(self.scalar("SELECT value FROM sequences WHERE name = ?", (name,)))

    def schema_version(self) -> int:
        return int(self.scalar("PRAGMA user_version", default=0))

    def close(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.conn.close()

    def reopen(self) -> None:
        self.conn = connect(self.path)
        self._depth = 0
        migrations.migrate(self)
