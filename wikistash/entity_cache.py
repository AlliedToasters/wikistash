"""SQLite-backed LRU entity cache for API results."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import orjson

from wikistash.models import Entity, parse_entity


class EntityCache:
    def __init__(
        self,
        db_path: Path | str,
        ttl_seconds: int = 7 * 24 * 3600,
        max_entries: int = 1_000_000,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                qid TEXT PRIMARY KEY,
                data BLOB NOT NULL,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL
            )
        """)
        self._conn.commit()

    def get(self, qid: str, lang: str = "en") -> Entity | None:
        """Fetch from cache. Returns None if not found or expired."""
        row = self._conn.execute(
            "SELECT data, created_at FROM cache WHERE qid = ?", (qid,)
        ).fetchone()
        if row is None:
            return None

        data_bytes, created_at = row
        now = time.time()

        # TTL check
        if created_at + self._ttl < now:
            self._conn.execute("DELETE FROM cache WHERE qid = ?", (qid,))
            self._conn.commit()
            return None

        # Update last_accessed
        self._conn.execute(
            "UPDATE cache SET last_accessed = ? WHERE qid = ?", (now, qid)
        )
        self._conn.commit()

        raw = orjson.loads(data_bytes)
        return parse_entity(raw, lang=lang)

    def put(self, qid: str, raw_data: dict[str, Any]) -> None:
        """Store an entity in cache. Evicts if at capacity."""
        now = time.time()
        data_bytes = orjson.dumps(raw_data)

        self._conn.execute(
            """INSERT OR REPLACE INTO cache (qid, data, created_at, last_accessed)
               VALUES (?, ?, ?, ?)""",
            (qid, data_bytes, now, now),
        )
        self._conn.commit()

        # Check if eviction needed
        count = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        if count > self._max_entries:
            self._evict()

    def _evict(self) -> None:
        """Delete oldest 10% of entries by last_accessed."""
        to_delete = max(1, self._max_entries // 10)
        self._conn.execute(
            "DELETE FROM cache WHERE qid IN (SELECT qid FROM cache ORDER BY last_accessed ASC LIMIT ?)",
            (to_delete,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
