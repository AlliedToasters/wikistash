"""Stash — the public facade. The only class most users ever touch."""

from __future__ import annotations

from typing import Any

import duckdb

from wikistash.config import WikiStashConfig
from wikistash.entity_cache import EntityCache
from wikistash.exceptions import WikiStashError
from wikistash.live_api import LiveAPIClient
from wikistash.local_db import LocalDB
from wikistash.models import Entity, SearchResult
from wikistash.resolver import EntityResolver


class Stash:
    """Unified interface to Wikidata with local cache and API fallback.

    Usage::

        stash = Stash()
        entity = stash.get("Q42")
        entity.label  # "Douglas Adams"
    """

    def __init__(self, **kwargs: Any) -> None:
        self._config = WikiStashConfig(**kwargs)

        # Local DB — only create if the file already exists
        self._local_db: LocalDB | None = None
        if self._config.local_db_path.exists():
            self._local_db = LocalDB(self._config.local_db_path)

        # Entity cache — always create
        self._entity_cache = EntityCache(
            self._config.cache_db_path,
            ttl_seconds=self._config.cache_ttl_seconds,
            max_entries=self._config.cache_max_entries,
        )

        # Live API client — only if fallback enabled
        self._live_api: LiveAPIClient | None = None
        if self._config.enable_live_fallback:
            self._live_api = LiveAPIClient(self._config)

        # Resolver
        self._resolver = EntityResolver(
            config=self._config,
            local_db=self._local_db,
            entity_cache=self._entity_cache,
            live_api=self._live_api,
        )

    def get(self, qid_or_qids: str | list[str]) -> Entity | dict[str, Entity]:
        """Get one or many entities.

        Single QID returns an Entity, list returns dict[str, Entity].
        """
        if isinstance(qid_or_qids, str):
            return self._resolver.get(qid_or_qids)
        return self._resolver.get_batch(qid_or_qids)

    def search(
        self, query: str, lang: str | None = None, limit: int = 10
    ) -> list[SearchResult]:
        """Search for entities (always via live API)."""
        if self._live_api is None:
            raise WikiStashError("Search requires live API access (enable_live_fallback=True)")
        return self._live_api.search(
            query, lang=lang or self._config.default_language, limit=limit
        )

    def sparql(self, query: str) -> list[dict[str, Any]]:
        """Execute a SPARQL query against the local store.

        Returns a list of row dicts with SPARQL variable names as keys.
        """
        if self._local_db is None:
            raise WikiStashError("SPARQL requires a local database. Load a dump first.")
        from wikistash.sparql import execute_sparql

        return execute_sparql(self._local_db.get_connection(), query)

    def sparql_json(self, query: str) -> dict[str, Any]:
        """Execute a SPARQL query and return standard SPARQL JSON Results format.

        Returns ``{"results": {"bindings": [...]}}`` — the same shape as
        the Wikidata Query Service, so consumer apps can swap in wikistash
        with no parsing changes.
        """
        if self._local_db is None:
            raise WikiStashError("SPARQL requires a local database. Load a dump first.")
        from wikistash.sparql import execute_sparql_json

        return execute_sparql_json(self._local_db.get_connection(), query)

    def duckdb(self) -> duckdb.DuckDBPyConnection:
        """Return the raw DuckDB connection for SQL queries."""
        if self._local_db is None:
            raise WikiStashError("No local database available. Load a dump first.")
        return self._local_db.get_connection()

    def close(self) -> None:
        """Close all connections."""
        if self._local_db is not None:
            self._local_db.close()
        self._entity_cache.close()
        if self._live_api is not None:
            self._live_api.close()

    def __enter__(self) -> Stash:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
