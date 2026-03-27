"""Tests for stash.py — public Stash facade."""

from unittest.mock import MagicMock, patch

import pytest

from wikistash.exceptions import WikiStashError
from wikistash.models import Entity, parse_entity
from wikistash.stash import Stash


class TestStash:
    def test_get_single(self, sample_entity_raw, tmp_path):
        entity = parse_entity(sample_entity_raw)
        with patch("wikistash.stash.EntityResolver") as MockResolver:
            MockResolver.return_value.get.return_value = entity
            stash = Stash(
                local_db_path=tmp_path / "nonexistent.duckdb",
                cache_db_path=tmp_path / "cache.sqlite",
                enable_live_fallback=False,
            )
            result = stash.get("Q42")
            assert result.qid == "Q42"
            assert result.label == "Douglas Adams"
            stash.close()

    def test_get_batch(self, sample_entity_raw, sample_entity_raw_q1, tmp_path):
        q42 = parse_entity(sample_entity_raw)
        q1 = parse_entity(sample_entity_raw_q1)
        with patch("wikistash.stash.EntityResolver") as MockResolver:
            MockResolver.return_value.get_batch.return_value = {"Q42": q42, "Q1": q1}
            stash = Stash(
                local_db_path=tmp_path / "nonexistent.duckdb",
                cache_db_path=tmp_path / "cache.sqlite",
                enable_live_fallback=False,
            )
            result = stash.get(["Q42", "Q1"])
            assert isinstance(result, dict)
            assert "Q42" in result
            assert "Q1" in result
            stash.close()

    def test_context_manager(self, tmp_path):
        with patch("wikistash.stash.EntityResolver"):
            with Stash(
                local_db_path=tmp_path / "nonexistent.duckdb",
                cache_db_path=tmp_path / "cache.sqlite",
                enable_live_fallback=False,
            ) as stash:
                assert stash is not None

    def test_duckdb_without_local_db_raises(self, tmp_path):
        with patch("wikistash.stash.EntityResolver"):
            stash = Stash(
                local_db_path=tmp_path / "nonexistent.duckdb",
                cache_db_path=tmp_path / "cache.sqlite",
                enable_live_fallback=False,
            )
            with pytest.raises(WikiStashError, match="No local database"):
                stash.duckdb()
            stash.close()

    def test_search_without_api_raises(self, tmp_path):
        with patch("wikistash.stash.EntityResolver"):
            stash = Stash(
                local_db_path=tmp_path / "nonexistent.duckdb",
                cache_db_path=tmp_path / "cache.sqlite",
                enable_live_fallback=False,
            )
            with pytest.raises(WikiStashError, match="requires live API"):
                stash.search("Douglas Adams")
            stash.close()
