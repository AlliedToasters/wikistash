"""Wikidata API client with rate limiting and retries."""

from __future__ import annotations

import time
from collections import deque

import httpx
import orjson
import structlog

from wikistash.config import WikiStashConfig
from wikistash.exceptions import APIError, EntityNotFoundError, RateLimitError
from wikistash.models import SearchResult

log = structlog.get_logger()


class RateLimiter:
    """Token bucket rate limiter based on request timestamps."""

    def __init__(self, max_qps: float) -> None:
        self._max_qps = max_qps
        self._min_interval = 1.0 / max_qps if max_qps > 0 else 0
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        now = time.monotonic()
        # Remove timestamps older than 1 second
        while self._timestamps and now - self._timestamps[0] > 1.0:
            self._timestamps.popleft()
        # If we've hit the limit, wait
        if len(self._timestamps) >= self._max_qps:
            sleep_time = 1.0 - (now - self._timestamps[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        self._timestamps.append(time.monotonic())


class LiveAPIClient:
    def __init__(self, config: WikiStashConfig) -> None:
        self._config = config
        self._rate_limiter = RateLimiter(config.max_qps)
        self._client = httpx.Client(
            timeout=config.request_timeout,
            headers={"User-Agent": config.user_agent},
        )

    def get_entity(self, qid: str) -> dict:
        """Fetch a single entity. Returns raw API JSON for that entity."""
        result = self.get_entities([qid])
        if qid not in result:
            raise EntityNotFoundError(qid)
        return result[qid]

    def get_entities(self, qids: list[str]) -> dict[str, dict]:
        """Fetch entities (splits into chunks of 50). Returns {qid: raw_json}."""
        all_results: dict[str, dict] = {}
        for i in range(0, len(qids), 50):
            chunk = qids[i : i + 50]
            params = {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "format": "json",
            }
            data = self._request(params)
            entities = data.get("entities", {})
            for entity_id, entity_data in entities.items():
                if "missing" not in entity_data:
                    all_results[entity_id] = entity_data
        return all_results

    def search(
        self, query: str, lang: str = "en", limit: int = 10
    ) -> list[SearchResult]:
        """Search for entities via wbsearchentities."""
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": lang,
            "limit": str(limit),
            "format": "json",
        }
        data = self._request(params)
        results = []
        for item in data.get("search", []):
            results.append(
                SearchResult(
                    qid=item.get("id", ""),
                    label=item.get("label"),
                    description=item.get("description"),
                )
            )
        return results

    def _request(self, params: dict) -> dict:
        """Make an API request with rate limiting, retries, and error handling."""
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            self._rate_limiter.acquire()
            try:
                response = self._client.get(
                    self._config.wikidata_api_url, params=params
                )
            except httpx.HTTPError as e:
                last_error = APIError(0, str(e))
                backoff = min(2**attempt, 30)
                log.warning("http_error", error=str(e), attempt=attempt, backoff=backoff)
                time.sleep(backoff)
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "5"))
                retry_after = max(retry_after, 5.0)
                log.warning("rate_limited", retry_after=retry_after, attempt=attempt)
                time.sleep(retry_after)
                last_error = RateLimitError(retry_after)
                continue

            if response.status_code >= 500:
                backoff = min(2**attempt, 30)
                log.warning(
                    "server_error",
                    status=response.status_code,
                    attempt=attempt,
                    backoff=backoff,
                )
                last_error = APIError(response.status_code, response.text)
                time.sleep(backoff)
                continue

            if response.status_code != 200:
                raise APIError(response.status_code, response.text)

            return orjson.loads(response.content)

        raise last_error or APIError(0, "All retries exhausted")

    def close(self) -> None:
        self._client.close()
