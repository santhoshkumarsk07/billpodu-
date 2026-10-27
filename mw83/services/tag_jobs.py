"""Remember tag print jobs so they can be reprinted. Never touches stock or prices."""
from __future__ import annotations

import json

from ..db import Database, now_str


def log_job(db: Database, label: str, items: list[tuple[int, int]]) -> int:
    with db.transaction():
        return db.execute("INSERT INTO tag_print_jobs(created_at, label, items_json) VALUES (?,?,?)",
                          (now_str(), label[:100], json.dumps([[int(v), int(c)] for v, c in items]))).lastrowid


def list_jobs(db: Database, limit: int = 100) -> list[dict]:
    out = []
    for r in db.all("SELECT id, created_at, label, items_json FROM tag_print_jobs ORDER BY id DESC LIMIT ?", (limit,)):
        try:
            items = [(int(v), int(c)) for v, c in json.loads(r["items_json"])]
        except (ValueError, TypeError):
            items = []
        out.append({"id": r["id"], "created_at": r["created_at"], "label": r["label"], "items": items,
                    "tags": sum(c for _, c in items)})
    return out
