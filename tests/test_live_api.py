"""Tests for live_api.py — Wikidata API client with mocked httpx."""

import httpx
import pytest
import respx

from wikistash.config import WikiStashConfig
from wikistash.exceptions import APIError, EntityNotFoundError
from wikistash.live_api import LiveAPIClient, RateLimiter


@pytest.fixture
def api_config():
    return WikiStashConfig(
        max_qps=100.0,  # high limit for tests
        max_retries=2,
        request_timeout=5.0,
        enable_live_fallback=True,
    )


@pytest.fixture
def client(api_config):
    c = LiveAPIClient(api_config)
    yield c
    c.close()


class TestRateLimiter:
    def test_acquire_does_not_block_under_limit(self):
        limiter = RateLimiter(max_qps=100.0)
        import time
        start = time.monotonic()
        for _ in range(10):
            limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0


class TestLiveAPIClient:
    @respx.mock
    def test_get_entity_success(self, client, sample_entity_raw):
        api_response = {"entities": {"Q42": sample_entity_raw}}
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json=api_response)
        )
        result = client.get_entity("Q42")
        assert result["id"] == "Q42"

    @respx.mock
    def test_get_entity_not_found(self, client):
        api_response = {"entities": {"Q99999": {"id": "Q99999", "missing": ""}}}
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json=api_response)
        )
        with pytest.raises(EntityNotFoundError):
            client.get_entity("Q99999")

    @respx.mock
    def test_get_entities_batch(self, client, sample_entity_raw, sample_entity_raw_q1):
        api_response = {
            "entities": {"Q42": sample_entity_raw, "Q1": sample_entity_raw_q1}
        }
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json=api_response)
        )
        result = client.get_entities(["Q42", "Q1"])
        assert "Q42" in result
        assert "Q1" in result

    @respx.mock
    def test_retry_on_429(self, client, sample_entity_raw):
        api_response = {"entities": {"Q42": sample_entity_raw}}
        route = respx.get("https://www.wikidata.org/w/api.php")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=api_response),
        ]
        result = client.get_entity("Q42")
        assert result["id"] == "Q42"

    @respx.mock
    def test_retry_on_500(self, client, sample_entity_raw):
        api_response = {"entities": {"Q42": sample_entity_raw}}
        route = respx.get("https://www.wikidata.org/w/api.php")
        route.side_effect = [
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json=api_response),
        ]
        result = client.get_entity("Q42")
        assert result["id"] == "Q42"

    @respx.mock
    def test_all_retries_exhausted(self, client):
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        with pytest.raises(APIError):
            client.get_entity("Q42")

    @respx.mock
    def test_search(self, client):
        api_response = {
            "search": [
                {"id": "Q42", "label": "Douglas Adams", "description": "English author"},
                {"id": "Q101352", "label": "Douglas Adams", "description": "American football player"},
            ]
        }
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json=api_response)
        )
        results = client.search("Douglas Adams")
        assert len(results) == 2
        assert results[0].qid == "Q42"
        assert results[0].label == "Douglas Adams"

    @respx.mock
    def test_client_error_raises(self, client):
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        with pytest.raises(APIError):
            client.get_entity("Q42")
