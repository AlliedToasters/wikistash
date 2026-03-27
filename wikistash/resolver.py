"""EntityResolver — routes entity requests through the tier hierarchy."""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog

from wikistash.config import WikiStashConfig
from wikistash.entity_cache import EntityCache
from wikistash.exceptions import EntityNotFoundError
from wikistash.live_api import LiveAPIClient
from wikistash.local_db import LocalDB
from wikistash.models import Entity, parse_entity

log = structlog.get_logger()


class EntityResolver:
    def __init__(
        self,
        config: WikiStashConfig,
        local_db: LocalDB | None,
        entity_cache: EntityCache,
        live_api: LiveAPIClient | None,
    ) -> None:
        self._config = config
        self._local_db = local_db
        self._entity_cache = entity_cache
        self._live_api = live_api

    def get(self, qid: str) -> Entity:
        """Resolve a single entity through the tier hierarchy."""
        lang = self._config.default_language

        # 1. Local DB
        if self._local_db is not None:
            entity = self._local_db.get(qid, lang=lang)
            if entity is not None:
                log.debug("local_hit", qid=qid)
                return entity

        # 2. Entity cache
        entity = self._entity_cache.get(qid, lang=lang)
        if entity is not None:
            log.debug("cache_hit", qid=qid)
            return entity

        # 3. Live API fallback
        if self._live_api is None:
            raise EntityNotFoundError(qid)

        raw = self._live_api.get_entity(qid)
        log.debug("api_hit", qid=qid)

        # Cache the result
        self._entity_cache.put(qid, raw)

        # Backfill to local DB
        self._backfill(qid, raw)

        return parse_entity(raw, lang=lang)

    def get_batch(self, qids: list[str]) -> dict[str, Entity]:
        """Resolve multiple entities. Splits local hits from API batch."""
        lang = self._config.default_language
        result: dict[str, Entity] = {}
        remaining = list(qids)

        # 1. Local DB batch
        if self._local_db is not None and remaining:
            local_hits = self._local_db.get_batch(remaining, lang=lang)
            result.update(local_hits)
            remaining = [q for q in remaining if q not in local_hits]

        # 2. Entity cache (one by one, since cache is simple)
        still_remaining = []
        for qid in remaining:
            entity = self._entity_cache.get(qid, lang=lang)
            if entity is not None:
                result[qid] = entity
            else:
                still_remaining.append(qid)
        remaining = still_remaining

        # 3. Live API fallback for remaining
        if remaining and self._live_api is not None:
            api_results = self._live_api.get_entities(remaining)
            for qid, raw in api_results.items():
                self._entity_cache.put(qid, raw)
                self._backfill(qid, raw)
                result[qid] = parse_entity(raw, lang=lang)

        return result

    def _backfill(self, qid: str, raw_data: dict[str, Any]) -> None:
        """Write an API result back to LocalDB if backfill is enabled."""
        if self._config.enable_backfill and self._local_db is not None:
            self._local_db.put(
                raw_data,
                dump_date=date.today(),
                source="backfill",
                languages=self._config.dump_languages,
            )
            log.debug("backfill", qid=qid)
