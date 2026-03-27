"""DuckDB-backed local entity store."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import orjson

from wikistash.models import Entity, parse_entity


class LocalDB:
    def __init__(self, db_path: Path | str) -> None:
        self._conn = duckdb.connect(str(db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                qid TEXT PRIMARY KEY,
                data JSON NOT NULL,
                dump_date DATE,
                source TEXT DEFAULT 'dump'
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                qid TEXT NOT NULL,
                property TEXT NOT NULL,
                value JSON,
                rank TEXT DEFAULT 'normal',
                qualifiers JSON
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                qid TEXT NOT NULL,
                lang TEXT NOT NULL,
                value TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS aliases (
                qid TEXT NOT NULL,
                lang TEXT NOT NULL,
                values JSON NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS descriptions (
                qid TEXT NOT NULL,
                lang TEXT NOT NULL,
                value TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sitelinks (
                qid TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            )
        """)
        # Indices
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_claims_qid_prop ON claims (qid, property)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_claims_prop_value ON claims (property, value)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_labels_qid_lang ON labels (qid, lang)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_desc_qid_lang ON descriptions (qid, lang)"
        )

    def get(self, qid: str, lang: str = "en") -> Entity | None:
        """Fetch a single entity by QID. Returns None if not found."""
        result = self._conn.execute(
            "SELECT data FROM entities WHERE qid = ?", [qid]
        ).fetchone()
        if result is None:
            return None
        raw = orjson.loads(result[0]) if isinstance(result[0], (str, bytes)) else result[0]
        return parse_entity(raw, lang=lang)

    def get_batch(self, qids: list[str], lang: str = "en") -> dict[str, Entity]:
        """Fetch multiple entities. Returns dict of found entities."""
        if not qids:
            return {}
        placeholders = ", ".join(["?"] * len(qids))
        rows = self._conn.execute(
            f"SELECT qid, data FROM entities WHERE qid IN ({placeholders})", qids
        ).fetchall()
        result = {}
        for qid_val, data in rows:
            raw = orjson.loads(data) if isinstance(data, (str, bytes)) else data
            result[qid_val] = parse_entity(raw, lang=lang)
        return result

    def put(
        self,
        raw_data: dict[str, Any],
        dump_date: date | None = None,
        source: str = "dump",
        languages: list[str] | None = None,
    ) -> None:
        """Insert/replace an entity into the local store."""
        qid = raw_data.get("id", "")
        data_bytes = orjson.dumps(raw_data).decode("utf-8")

        # Upsert into entities table
        self._conn.execute(
            """INSERT OR REPLACE INTO entities (qid, data, dump_date, source)
               VALUES (?, ?, ?, ?)""",
            [qid, data_bytes, dump_date, source],
        )

        # Clear decomposed data for this entity
        for table in ("claims", "labels", "aliases", "descriptions", "sitelinks"):
            self._conn.execute(f"DELETE FROM {table} WHERE qid = ?", [qid])

        # Decompose claims
        for prop_id, statements in raw_data.get("claims", {}).items():
            for stmt in statements:
                mainsnak = stmt.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue")
                value_json = orjson.dumps(datavalue).decode("utf-8") if datavalue else None
                qualifiers = stmt.get("qualifiers")
                qual_json = orjson.dumps(qualifiers).decode("utf-8") if qualifiers else None
                self._conn.execute(
                    "INSERT INTO claims (qid, property, value, rank, qualifiers) VALUES (?, ?, ?, ?, ?)",
                    [qid, prop_id, value_json, stmt.get("rank", "normal"), qual_json],
                )

        # Decompose labels
        langs = languages or list(raw_data.get("labels", {}).keys())
        for lang_code in langs:
            label_data = raw_data.get("labels", {}).get(lang_code)
            if label_data and isinstance(label_data, dict):
                self._conn.execute(
                    "INSERT INTO labels (qid, lang, value) VALUES (?, ?, ?)",
                    [qid, lang_code, label_data["value"]],
                )

        # Decompose descriptions
        for lang_code in langs:
            desc_data = raw_data.get("descriptions", {}).get(lang_code)
            if desc_data and isinstance(desc_data, dict):
                self._conn.execute(
                    "INSERT INTO descriptions (qid, lang, value) VALUES (?, ?, ?)",
                    [qid, lang_code, desc_data["value"]],
                )

        # Decompose aliases
        for lang_code in langs:
            alias_data = raw_data.get("aliases", {}).get(lang_code)
            if alias_data and isinstance(alias_data, list):
                alias_json = orjson.dumps(alias_data).decode("utf-8")
                self._conn.execute(
                    "INSERT INTO aliases (qid, lang, values) VALUES (?, ?, ?)",
                    [qid, lang_code, alias_json],
                )

        # Sitelinks count
        sitelinks_data = raw_data.get("sitelinks", {})
        sitelink_count = len(sitelinks_data) if isinstance(sitelinks_data, dict) else 0
        self._conn.execute(
            "INSERT OR REPLACE INTO sitelinks (qid, count) VALUES (?, ?)",
            [qid, sitelink_count],
        )

    def put_batch(
        self,
        raw_entities: list[dict[str, Any]],
        dump_date: date | None = None,
        source: str = "dump",
        languages: list[str] | None = None,
    ) -> None:
        """Batch insert for dump loading performance."""
        self._conn.execute("BEGIN TRANSACTION")
        try:
            for raw_data in raw_entities:
                self.put(raw_data, dump_date=dump_date, source=source, languages=languages)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Return the raw DuckDB connection (escape hatch)."""
        return self._conn

    def close(self) -> None:
        self._conn.close()
