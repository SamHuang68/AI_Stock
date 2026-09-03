# -*- coding: utf-8 -*-
"""Append-only SQLite audit log (stdlib sqlite3)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from .state import DATA, now_iso

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    data_path = Path(DATA)
    data_path.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(data_path / "wavedeck_audit.db"))
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          kind TEXT NOT NULL,
          payload TEXT NOT NULL
        )
        """
    )
    c.commit()
    return c


def write(kind: str, payload: dict[str, Any]) -> None:
    with _lock:
        with closing(_conn()) as connection:
            connection.execute(
                "INSERT INTO audit(ts, kind, payload) VALUES (?,?,?)",
                (now_iso(), kind, json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()


def recent(limit: int = 40) -> list[dict[str, Any]]:
    with _lock:
        with closing(_conn()) as connection:
            rows = connection.execute(
                "SELECT id, ts, kind, payload FROM audit ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
    out = []
    for i, ts, kind, payload in rows:
        try:
            body = json.loads(payload)
        except Exception:
            body = {"raw": payload}
        out.append({"id": i, "ts": ts, "kind": kind, "payload": body})
    return out
