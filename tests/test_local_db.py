"""Tests for local_db.py — DuckDB local store."""

import pytest

from wikistash.local_db import LocalDB


@pytest.fixture
def db(tmp_path):
    local_db = LocalDB(tmp_path / "test.duckdb")
    yield local_db
    local_db.close()


class TestLocalDB:
    def test_get_missing_returns_none(self, db):
        assert db.get("Q99999") is None

    def test_put_and_get_roundtrip(self, db, sample_entity_raw):
        db.put(sample_entity_raw)
        entity = db.get("Q42")
        assert entity is not None
        assert entity.qid == "Q42"
        assert entity.label == "Douglas Adams"
        assert entity.description == "English author and humourist"

    def test_put_and_get_claims(self, db, sample_entity_raw):
        db.put(sample_entity_raw)
        entity = db.get("Q42")
        assert "P31" in entity.claims
        assert entity["P31"][0].value.entity_id == "Q5"

    def test_get_batch(self, db, sample_entity_raw, sample_entity_raw_q1):
        db.put(sample_entity_raw)
        db.put(sample_entity_raw_q1)
        result = db.get_batch(["Q42", "Q1", "Q99999"])
        assert "Q42" in result
        assert "Q1" in result
        assert "Q99999" not in result
        assert result["Q42"].label == "Douglas Adams"
        assert result["Q1"].label == "Universe"

    def test_get_batch_empty(self, db):
        assert db.get_batch([]) == {}

    def test_put_replaces_existing(self, db, sample_entity_raw):
        db.put(sample_entity_raw)
        modified = {**sample_entity_raw, "labels": {"en": {"language": "en", "value": "DNA"}}}
        db.put(modified)
        entity = db.get("Q42")
        assert entity.label == "DNA"

    def test_schema_idempotent(self, tmp_path):
        db = LocalDB(tmp_path / "test.duckdb")
        db._ensure_schema()  # second call should not error
        db.close()

    def test_decomposed_claims_table(self, db, sample_entity_raw):
        db.put(sample_entity_raw)
        rows = db.get_connection().execute(
            "SELECT property, rank FROM claims WHERE qid = 'Q42' ORDER BY property"
        ).fetchall()
        props = [r[0] for r in rows]
        assert "P31" in props
        assert "P569" in props

    def test_decomposed_labels_table(self, db, sample_entity_raw):
        db.put(sample_entity_raw)
        row = db.get_connection().execute(
            "SELECT value FROM labels WHERE qid = 'Q42' AND lang = 'en'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Douglas Adams"

    def test_get_connection(self, db):
        conn = db.get_connection()
        assert conn is not None
        result = conn.execute("SELECT 1").fetchone()
        assert result == (1,)

    def test_put_batch(self, db, sample_entity_raw, sample_entity_raw_q1):
        db.put_batch([sample_entity_raw, sample_entity_raw_q1])
        assert db.get("Q42") is not None
        assert db.get("Q1") is not None

    def test_sitelinks_count(self, db, sample_entity_raw, sample_entity_raw_q1):
        db.put(sample_entity_raw)
        db.put(sample_entity_raw_q1)
        row = db.get_connection().execute(
            "SELECT count FROM sitelinks WHERE qid = 'Q42'"
        ).fetchone()
        assert row is not None
        assert row[0] == 25  # 25 sitelinks in fixture
        row = db.get_connection().execute(
            "SELECT count FROM sitelinks WHERE qid = 'Q1'"
        ).fetchone()
        assert row is not None
        assert row[0] == 3

    def test_sitelinks_filter_query(self, db, sample_entity_raw, sample_entity_raw_q1):
        """Test the kind of sitelinks filter the consumer app uses."""
        db.put(sample_entity_raw)
        db.put(sample_entity_raw_q1)
        rows = db.get_connection().execute(
            "SELECT s.qid FROM sitelinks s WHERE s.count >= 20"
        ).fetchall()
        qids = [r[0] for r in rows]
        assert "Q42" in qids
        assert "Q1" not in qids  # only 3 sitelinks

    def test_sitelinks_no_sitelinks_field(self, db):
        """Entity without sitelinks field gets count 0."""
        raw = {"id": "Q999", "type": "item"}
        db.put(raw)
        row = db.get_connection().execute(
            "SELECT count FROM sitelinks WHERE qid = 'Q999'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0
