"""Tests for resolver.py — EntityResolver tier routing."""

from unittest.mock import MagicMock

import pytest

from wikistash.config import WikiStashConfig
from wikistash.exceptions import EntityNotFoundError
from wikistash.models import Entity, parse_entity
from wikistash.resolver import EntityResolver


@pytest.fixture
def resolver_config():
    return WikiStashConfig(
        enable_live_fallback=True,
        enable_backfill=True,
    )


@pytest.fixture
def mock_local_db():
    return MagicMock()


@pytest.fixture
def mock_cache():
    return MagicMock()


@pytest.fixture
def mock_api():
    return MagicMock()


class TestEntityResolver:
    def test_local_hit(self, resolver_config, mock_local_db, mock_cache, mock_api, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        mock_local_db.get.return_value = entity
        resolver = EntityResolver(resolver_config, mock_local_db, mock_cache, mock_api)

        result = resolver.get("Q42")
        assert result.qid == "Q42"
        mock_local_db.get.assert_called_once()
        mock_cache.get.assert_not_called()
        mock_api.get_entity.assert_not_called()

    def test_cache_hit(self, resolver_config, mock_local_db, mock_cache, mock_api, sample_entity_raw):
        mock_local_db.get.return_value = None
        entity = parse_entity(sample_entity_raw)
        mock_cache.get.return_value = entity
        resolver = EntityResolver(resolver_config, mock_local_db, mock_cache, mock_api)

        result = resolver.get("Q42")
        assert result.qid == "Q42"
        mock_api.get_entity.assert_not_called()

    def test_api_fallback(self, resolver_config, mock_local_db, mock_cache, mock_api, sample_entity_raw):
        mock_local_db.get.return_value = None
        mock_cache.get.return_value = None
        mock_api.get_entity.return_value = sample_entity_raw
        resolver = EntityResolver(resolver_config, mock_local_db, mock_cache, mock_api)

        result = resolver.get("Q42")
        assert result.qid == "Q42"
        mock_cache.put.assert_called_once_with("Q42", sample_entity_raw)
        mock_local_db.put.assert_called_once()  # backfill

    def test_no_fallback_raises(self, mock_local_db, mock_cache):
        config = WikiStashConfig(enable_live_fallback=False)
        mock_local_db.get.return_value = None
        mock_cache.get.return_value = None
        resolver = EntityResolver(config, mock_local_db, mock_cache, None)

        with pytest.raises(EntityNotFoundError):
            resolver.get("Q42")

    def test_no_backfill(self, mock_local_db, mock_cache, mock_api, sample_entity_raw):
        config = WikiStashConfig(enable_live_fallback=True, enable_backfill=False)
        mock_local_db.get.return_value = None
        mock_cache.get.return_value = None
        mock_api.get_entity.return_value = sample_entity_raw
        resolver = EntityResolver(config, mock_local_db, mock_cache, mock_api)

        resolver.get("Q42")
        mock_local_db.put.assert_not_called()

    def test_batch_splits(self, resolver_config, mock_local_db, mock_cache, mock_api, sample_entity_raw, sample_entity_raw_q1):
        # Q42 is local, Q1 needs API
        q42_entity = parse_entity(sample_entity_raw)
        mock_local_db.get_batch.return_value = {"Q42": q42_entity}
        mock_cache.get.return_value = None
        mock_api.get_entities.return_value = {"Q1": sample_entity_raw_q1}
        resolver = EntityResolver(resolver_config, mock_local_db, mock_cache, mock_api)

        result = resolver.get_batch(["Q42", "Q1"])
        assert "Q42" in result
        assert "Q1" in result
        # API should only be called with Q1
        mock_api.get_entities.assert_called_once_with(["Q1"])

    def test_batch_all_local(self, resolver_config, mock_local_db, mock_cache, mock_api, sample_entity_raw, sample_entity_raw_q1):
        q42 = parse_entity(sample_entity_raw)
        q1 = parse_entity(sample_entity_raw_q1)
        mock_local_db.get_batch.return_value = {"Q42": q42, "Q1": q1}
        resolver = EntityResolver(resolver_config, mock_local_db, mock_cache, mock_api)

        result = resolver.get_batch(["Q42", "Q1"])
        assert len(result) == 2
        mock_api.get_entities.assert_not_called()

    def test_no_local_db(self, resolver_config, mock_cache, mock_api, sample_entity_raw):
        mock_cache.get.return_value = None
        mock_api.get_entity.return_value = sample_entity_raw
        resolver = EntityResolver(resolver_config, None, mock_cache, mock_api)

        result = resolver.get("Q42")
        assert result.qid == "Q42"
