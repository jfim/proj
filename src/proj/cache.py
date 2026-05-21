"""On-disk cache for expensive column values."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                project TEXT NOT NULL,
                column TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (project, column, key)
            )
            """
        )
        self._conn.commit()

    def lookup(self, project: str, column: str, key: str) -> Any:
        row = self._conn.execute(
            "SELECT value FROM entries WHERE project=? AND column=? AND key=?",
            (project, column, key),
        ).fetchone()
        if row is None:
            return None
        decoded = json.loads(row[0])
        return None if decoded is None else decoded

    def store(self, project: str, column: str, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        self._conn.execute(
            "INSERT OR REPLACE INTO entries (project, column, key, value) VALUES (?, ?, ?, ?)",
            (project, column, key, encoded),
        )
        self._conn.commit()

    @staticmethod
    def command_hash(command: str) -> str:
        return hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]

    def close(self) -> None:
        self._conn.close()
