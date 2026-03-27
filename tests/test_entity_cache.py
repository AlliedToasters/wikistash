"""Tests for entity_cache.py — SQLite LRU cache."""

import time

import pytest

from wikistash.entity_cache import EntityCache


@pytest.fixture
def cache(tmp_path):
    c = EntityCache(tmp_path / "cache.sqlite", ttl_seconds=3600, max_entries=100)
    yield c
    c.close()


class TestEntityCache:
    def test_get_missing_returns_none(self, cache):
        assert cache.get("Q99999") is None

    def test_put_and_get_roundtrip(self, cache, sample_entity_raw):
        cache.put("Q42", sample_entity_raw)
        entity = cache.get("Q42")
        assert entity is not None
        assert entity.qid == "Q42"
        assert entity.label == "Douglas Adams"

    def test_ttl_expiry(self, tmp_path, sample_entity_raw):
        cache = EntityCache(tmp_path / "cache.sqlite", ttl_seconds=1, max_entries=100)
        cache.put("Q42", sample_entity_raw)
        assert cache.get("Q42") is not None
        time.sleep(1.5)
        assert cache.get("Q42") is None
        cache.close()

    def test_lru_eviction(self, tmp_path):
        cache = EntityCache(tmp_path / "cache.sqlite", ttl_seconds=3600, max_entries=5)
        for i in range(6):
            cache.put(f"Q{i}", {"id": f"Q{i}", "type": "item"})
        # After inserting 6 with max 5, oldest should be evicted
        count = cache._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        assert count <= 5
        cache.close()

    def test_put_replaces_existing(self, cache, sample_entity_raw):
        cache.put("Q42", sample_entity_raw)
        modified = {**sample_entity_raw, "labels": {"en": {"language": "en", "value": "DNA"}}}
        cache.put("Q42", modified)
        entity = cache.get("Q42")
        assert entity.label == "DNA"

    def test_updates_last_accessed(self, cache, sample_entity_raw):
        cache.put("Q42", sample_entity_raw)
        time.sleep(0.1)
        cache.get("Q42")
        row = cache._conn.execute(
            "SELECT created_at, last_accessed FROM cache WHERE qid = 'Q42'"
        ).fetchone()
        assert row[1] > row[0]
