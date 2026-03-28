"""DuckDB-backed local entity store."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import orjson
import pyarrow as pa

from wikistash.models import Entity, parse_entity

_SNAPSHOT_HASH_KEY = "snapshot_hash"


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
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS db_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.create_indices()

    _INDEX_DEFS = [
        ("idx_claims_qid_prop", "claims (qid, property)"),
        ("idx_claims_prop_value", "claims (property, value)"),
        ("idx_labels_qid_lang", "labels (qid, lang)"),
        ("idx_desc_qid_lang", "descriptions (qid, lang)"),
    ]

    def create_indices(self) -> None:
        """Create all indices. Safe to call multiple times."""
        for name, definition in self._INDEX_DEFS:
            self._conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {definition}")

    def drop_indices(self) -> None:
        """Drop all indices for fast bulk loading."""
        for name, _ in self._INDEX_DEFS:
            self._conn.execute(f"DROP INDEX IF EXISTS {name}")

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

    def put_batch_fast(
        self,
        raw_entities: list[dict[str, Any]],
        languages: list[str] | None = None,
    ) -> None:
        """Fast bulk insert — decomposed tables only, skips raw entity JSON.

        Much faster for dump loading when only SPARQL queries are needed.
        """
        langs = languages or ["en"]
        claims_rows: list[tuple] = []
        labels_rows: list[tuple] = []
        desc_rows: list[tuple] = []
        alias_rows: list[tuple] = []
        sitelinks_rows: list[tuple] = []

        for raw_data in raw_entities:
            qid = raw_data.get("id", "")

            # Claims
            for prop_id, statements in raw_data.get("claims", {}).items():
                for stmt in statements:
                    mainsnak = stmt.get("mainsnak", {})
                    datavalue = mainsnak.get("datavalue")
                    value_json = orjson.dumps(datavalue).decode("utf-8") if datavalue else None
                    qualifiers = stmt.get("qualifiers")
                    qual_json = orjson.dumps(qualifiers).decode("utf-8") if qualifiers else None
                    claims_rows.append((
                        qid, prop_id, value_json, stmt.get("rank", "normal"), qual_json
                    ))

            # Labels
            for lang_code in langs:
                label_data = raw_data.get("labels", {}).get(lang_code)
                if label_data and isinstance(label_data, dict):
                    labels_rows.append((qid, lang_code, label_data["value"]))

            # Descriptions
            for lang_code in langs:
                desc_data = raw_data.get("descriptions", {}).get(lang_code)
                if desc_data and isinstance(desc_data, dict):
                    desc_rows.append((qid, lang_code, desc_data["value"]))

            # Aliases
            for lang_code in langs:
                alias_data = raw_data.get("aliases", {}).get(lang_code)
                if alias_data and isinstance(alias_data, list):
                    alias_json = orjson.dumps(alias_data).decode("utf-8")
                    alias_rows.append((qid, lang_code, alias_json))

            # Sitelinks
            sitelinks_data = raw_data.get("sitelinks", {})
            sitelink_count = len(sitelinks_data) if isinstance(sitelinks_data, dict) else 0
            sitelinks_rows.append((qid, sitelink_count))

        if claims_rows:
            cq, cp, cv, cr, ccq = zip(*claims_rows)
            tbl = pa.table({"qid": cq, "property": cp, "value": cv, "rank": cr, "qualifiers": ccq})
            self._conn.execute("INSERT INTO claims SELECT * FROM tbl")
        if labels_rows:
            lq, ll, lv = zip(*labels_rows)
            tbl = pa.table({"qid": lq, "lang": ll, "value": lv})
            self._conn.execute("INSERT INTO labels SELECT * FROM tbl")
        if desc_rows:
            dq, dl, dv = zip(*desc_rows)
            tbl = pa.table({"qid": dq, "lang": dl, "value": dv})
            self._conn.execute("INSERT INTO descriptions SELECT * FROM tbl")
        if alias_rows:
            aq, al, av = zip(*alias_rows)
            tbl = pa.table({"qid": aq, "lang": al, "values": av})
            self._conn.execute("INSERT INTO aliases SELECT * FROM tbl")
        if sitelinks_rows:
            sq, sc = zip(*sitelinks_rows)
            tbl = pa.table({"qid": sq, "count": sc})
            self._conn.execute("INSERT INTO sitelinks SELECT * FROM tbl")

    def put_labels_only(
        self,
        raw_entities: list[dict[str, Any]],
        languages: list[str] | None = None,
    ) -> None:
        """Insert only labels and descriptions for entities — no claims or sitelinks.

        Used during filtered dump loads to ensure label resolution works
        for all referenced entities, not just those matching the filter.
        """
        langs = languages or ["en"]
        labels_rows: list[tuple] = []
        desc_rows: list[tuple] = []

        for raw_data in raw_entities:
            qid = raw_data.get("id", "")
            for lang_code in langs:
                label_data = raw_data.get("labels", {}).get(lang_code)
                if label_data and isinstance(label_data, dict):
                    labels_rows.append((qid, lang_code, label_data["value"]))
                desc_data = raw_data.get("descriptions", {}).get(lang_code)
                if desc_data and isinstance(desc_data, dict):
                    desc_rows.append((qid, lang_code, desc_data["value"]))

        if labels_rows:
            lq, ll, lv = zip(*labels_rows)
            tbl = pa.table({"qid": lq, "lang": ll, "value": lv})
            self._conn.execute("INSERT INTO labels SELECT * FROM tbl")
        if desc_rows:
            dq, dl, dv = zip(*desc_rows)
            tbl = pa.table({"qid": dq, "lang": dl, "value": dv})
            self._conn.execute("INSERT INTO descriptions SELECT * FROM tbl")

    def set_metadata(self, key: str, value: str) -> None:
        """Upsert a metadata key/value pair."""
        self._conn.execute(
            "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
            [key, value],
        )

    def get_metadata(self, key: str) -> str | None:
        """Fetch a metadata value by key. Returns None if not set."""
        row = self._conn.execute(
            "SELECT value FROM db_metadata WHERE key = ?", [key]
        ).fetchone()
        return row[0] if row else None

    def snapshot_hash(self) -> str | None:
        """Return the snapshot hash stored at load time, or None if not set."""
        return self.get_metadata(_SNAPSHOT_HASH_KEY)

    def snapshot_info(self) -> dict[str, str]:
        """Return all metadata key/value pairs as a dict."""
        rows = self._conn.execute("SELECT key, value FROM db_metadata").fetchall()
        return {k: v for k, v in rows}

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Return the raw DuckDB connection (escape hatch)."""
        return self._conn

    def close(self) -> None:
        self._conn.close()
