# wikistash — Hybrid Wikidata Cache Library

## Project overview

wikistash is a Python library that provides a unified, cache-friendly interface to Wikidata. It solves the fundamental problem that query-level caching is the wrong abstraction for Wikidata: two queries returning 95% overlapping entities get cached as separate blobs, and any query tweak invalidates the entire cache while duplicating most entries.

wikistash decomposes Wikidata access into **entity-level atomic operations** and routes them through a two-tier backend: a local filtered dump (primary, fast, no rate limits) with transparent fallback to the live Wikidata API (secondary, rate-limited, entity-cached with backfill).

## North-star UX

The guiding principle: **wikistash should feel like Wikidata is a local dictionary.** No rate limits, no network errors, no cache misses — just ask for an entity and get it back instantly. The network should be invisible.

### Developer experience goals

1. **Zero-config quick start.** A developer should go from `pip install wikistash` to querying entities in under 5 minutes, without downloading a dump. Live API mode with entity caching should work out of the box — the dump is an optimization you add later, not a prerequisite.

2. **One import, one object.** The entire public API is `from wikistash import Stash`. No need to understand resolvers, caches, or backends. `Stash` is the only class most users ever touch.

3. **Sync and async with the same API.** `stash.get("Q42")` works in a script. `await stash.get("Q42")` works in an async context. No separate client classes.

4. **Dictionary-like entity access.** Entities behave like attribute bags, not JSON blobs:
   ```python
   stash = Stash()
   entity = stash.get("Q42")
   entity.label                    # "Douglas Adams" (default lang from config)
   entity.description              # "English author and humourist"
   entity["P569"]                  # date of birth claims
   entity.claims["date of birth"]  # same, resolved by label
   ```

5. **Property labels are first-class.** Nobody remembers that P569 is "date of birth". wikistash resolves property labels transparently (backed by the same cache), so `entity.claims["date of birth"]` and `entity["P569"]` are equivalent. The property label index is built during dump load or lazily cached from the API.

6. **Batch by default.** `stash.get(["Q42", "Q1", "Q5"])` returns a dict. Under the hood it splits local hits from API batch requests. Users never think about batching strategy.

7. **Transparent sourcing with opt-in observability.** By default, users don't know or care where data came from. But `stash.get("Q42", provenance=True)` returns metadata: source (local/cache/api), latency, freshness. And `stash.stats()` gives aggregate hit rates across tiers — useful for deciding when to invest in a dump load.

8. **Dump loading is a CLI one-liner.** `wikistash load --entities Q5,Q515,Q6256 --languages en,es` downloads the latest dump, filters it, and builds the local DB. Progress bar, ETA, resumable. No YAML config file required for common cases (but supported for complex filters).

9. **Graceful degradation.** If the local DB doesn't exist, fall back to API. If the API is rate-limited, serve from stale cache with a warning. If everything is down, raise a clear exception with diagnostics. Never silently return wrong data.

10. **Escape hatch to raw power.** `stash.duckdb()` returns the underlying DuckDB connection for users who need SQL. This is where SPARQL-style relational queries go — not through a half-baked query language, but through real SQL against a columnar store they already know.

## Architecture

```
Application code
       │
       ▼
┌─────────────────────┐
│      Stash        │  ← Unified query interface (the only public API)
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│   EntityResolver    │  ← Routes: local first, API fallback, backfill on miss
└─────┬───────────┬───┘
      │           │
      ▼           ▼
┌──────────┐ ┌───────────────┐
│ LocalDB  │ │ LiveAPIClient │
│ (DuckDB) │ │ + EntityCache │
└──────────┘ └───────────────┘
      ▲           │
      └───────────┘
        backfill
```

### Components

1. **Stash** — Public facade. Exposes `get(qid)`, `get(qids)` (batch), `search(text)`, and attribute-style claim access on returned entities. Supports both sync and async. Returns typed dataclasses. This is the only thing application code imports.

2. **EntityResolver** — Routing logic. For each entity/property request:
   - Check `LocalDB` first
   - On miss, check `EntityCache` (in-memory/SQLite for API results)
   - On miss, call `LiveAPIClient`, store result in `EntityCache`, and backfill to `LocalDB`
   - Batch requests are split: local hits resolved immediately, remaining QIDs batched to API (respecting 50-entity-per-request limit)

3. **LocalDB** — DuckDB database built from a filtered Wikidata JSON dump. Schema:
   - `entities(qid TEXT PRIMARY KEY, data JSON, dump_date DATE)`
   - `claims(qid TEXT, property TEXT, value JSON, rank TEXT, qualifiers JSON)` with composite index on `(qid, property)`
   - `labels(qid TEXT, lang TEXT, value TEXT)` with composite index on `(qid, lang)`
   - `aliases(qid TEXT, lang TEXT, values JSON)`
   - `descriptions(qid TEXT, lang TEXT, value TEXT)`

4. **LiveAPIClient** — Thin wrapper around the Wikibase `wbgetentities` API (NOT SPARQL). Handles:
   - Rate limiting (respect `Retry-After`, exponential backoff, configurable max QPS)
   - Request batching (up to 50 QIDs per request)
   - Timeout and retry logic
   - User-Agent header (required by Wikimedia policy)

5. **EntityCache** — SQLite-backed LRU cache keyed on `(qid, property)` pairs. TTL-based expiry (default 7 days, configurable). This caches API results so repeated fallback queries don't re-hit the API.

6. **DumpLoader** — CLI tool and importable module for building/refreshing the LocalDB from a Wikidata JSON dump. Features:
   - Stream-processes the compressed dump (never loads full file into memory)
   - Configurable entity filter: by QID list, by `instance_of` (P31) values, by property presence, or by custom predicate function
   - Progress reporting (the dump is ~100M entities)
   - Incremental mode: only insert entities newer than current `dump_date`
   - CLI: `wikistash load --dump-path ./latest-all.json.gz --filter-config ./filter.yaml`

## Technical decisions

- **Python 3.10+**, type-annotated throughout, `py.typed` marker
- **DuckDB** for local store (not SQLite) — columnar format is better for analytical queries across many entities, native JSON and parquet support, and it handles concurrent reads well
- **No SPARQL anywhere** — all access is via entity ID lookups. SPARQL is the source of the rate limit and caching problems. The whole point is to avoid it.
- **`httpx`** for async HTTP with connection pooling and retry
- **`pydantic`** for config validation and entity models
- **`click`** for CLI
- **`pytest`** + `pytest-asyncio` for tests
- **Structured logging** via `structlog` — log every cache hit/miss/backfill with QID, latency, source

## Project structure

```
wikistash/
├── __init__.py          # Public API re-exports
├── stash.py             # Stash facade (public API)
├── resolver.py          # EntityResolver routing logic
├── local_db.py          # DuckDB local store
├── live_api.py          # Wikidata API client
├── entity_cache.py      # SQLite LRU entity cache
├── dump_loader.py       # Dump ingestion pipeline
├── models.py            # Pydantic models for entities, claims, etc.
├── config.py            # Configuration (pydantic-settings)
├── exceptions.py        # Custom exception hierarchy
├── cli.py               # Click CLI entry point
├── py.typed
tests/
├── conftest.py          # Shared fixtures, mock API responses
├── test_stash.py
├── test_resolver.py
├── test_local_db.py
├── test_live_api.py
├── test_entity_cache.py
├── test_dump_loader.py
├── test_integration.py  # End-to-end with small fixture dump
fixtures/
├── sample_dump.json.gz  # ~100 entities for testing
├── filter_config.yaml   # Example filter configuration
pyproject.toml
README.md
CLAUDE.md                # This file
```

## Configuration

Via environment variables, `.env` file, or constructor kwargs (pydantic-settings):

```python
class WikiStashConfig(BaseSettings):
    # Local DB
    local_db_path: Path = Path("./wikistash.duckdb")

    # Entity cache
    cache_db_path: Path = Path("./wikistash_entity_cache.sqlite")
    cache_ttl_seconds: int = 7 * 24 * 3600  # 7 days
    cache_max_entries: int = 1_000_000

    # Live API
    wikidata_api_url: str = "https://www.wikidata.org/w/api.php"
    max_qps: float = 5.0  # Requests per second
    request_timeout: float = 30.0
    max_retries: int = 3
    user_agent: str = "WikiStash/0.1 (https://github.com/you/wikistash)"

    # Resolver
    enable_backfill: bool = True
    enable_live_fallback: bool = True

    # Dump loader
    dump_languages: list[str] = ["en"]  # Which language labels to keep
```

## Usage example

```python
from wikistash import Stash

# Zero-config quick start (API-only, entity-cached)
stash = Stash()

# With local dump (the fast path)
stash = Stash(local_db_path="./wikidata.duckdb")

# Full hybrid with custom UA
stash = Stash(
    local_db_path="./wikidata.duckdb",
    enable_live_fallback=True,
    user_agent="MyApp/1.0 (me@example.com)",
)

# Single entity — dictionary-like access
entity = stash.get("Q42")          # Douglas Adams
entity.label                        # "Douglas Adams"
entity.description                  # "English author and humourist"
entity["P569"]                      # date of birth claims (by PID)
entity.claims["date of birth"]      # same thing (by property label)

# Batch — returns dict[str, Entity]
entities = stash.get(["Q42", "Q1", "Q5"])

# Async works with the same object
entity = await stash.get("Q42")

# Search (always live API, result entities are cached)
results = stash.search("Douglas Adams", lang="en")

# Provenance when you need it
entity = stash.get("Q42", provenance=True)
entity.provenance.source             # "local" | "cache" | "api"
entity.provenance.latency_ms         # 0.3

# Aggregate stats
stash.stats()                        # {local_hits: 4821, cache_hits: 37, api_hits: 2, ...}

# Escape hatch — raw DuckDB connection
conn = stash.duckdb()
conn.sql("SELECT qid FROM claims WHERE property = 'P31' AND value = 'Q5'")
```

## Key implementation details

### EntityResolver routing (resolver.py)

```
resolve(qid, property=None):
    1. result = local_db.get(qid, property)
    2. if result: return result  # local hit, no network
    3. result = entity_cache.get(qid, property)
    4. if result and not result.expired: return result  # cached API hit
    5. if not config.enable_live_fallback: raise EntityNotFound(qid)
    6. api_result = await live_api.get_entity(qid)
    7. entity_cache.put(qid, api_result)
    8. if config.enable_backfill: local_db.backfill(qid, api_result)
    9. return extract(api_result, property)
```

### DumpLoader streaming (dump_loader.py)

The Wikidata JSON dump is a ~90GB gzipped file containing one JSON object per line (after stripping the array wrapper). The loader must:
- Stream with `gzip.open()`, never `json.load()` the whole file
- Parse each line with `orjson` for speed
- Apply the filter predicate before any DB writes
- Batch INSERT into DuckDB (10,000 rows per batch for throughput)
- Report progress every N entities (configurable)
- Handle the dump format quirk: first line is `[\n`, last line is `]\n`, every other line is a JSON object optionally followed by a comma

### Rate limiter (live_api.py)

Token bucket algorithm. Track last request timestamps in a deque. Before each request:
- If deque has >= `max_qps` entries and oldest is < 1 second ago, sleep until it's 1 second old
- On 429 response, respect `Retry-After` header, minimum 5 second backoff
- On 5xx, exponential backoff starting at 1 second

### Backfill (resolver.py → local_db.py)

When the live API returns an entity not in LocalDB:
- Write it to LocalDB with `dump_date = today` and a `source = 'backfill'` marker
- On next dump refresh, backfilled entries with `dump_date < new_dump_date` get overwritten by the canonical dump data
- This means the local store grows organically to cover edge cases

## Build order

Implement in this order, each step testable independently:

1. **models.py + exceptions.py** — Data classes and error types. No dependencies.
2. **config.py** — Pydantic settings. No dependencies.
3. **local_db.py** — DuckDB store with `get`, `put`, `backfill`, `stats` methods. Test with in-memory DuckDB.
4. **entity_cache.py** — SQLite LRU cache. Test with `:memory:` SQLite.
5. **live_api.py** — httpx client with rate limiting. Test with `respx` mocks.
6. **resolver.py** — Routing logic. Test with mocked LocalDB and LiveAPIClient.
7. **stash.py** — Thin facade with sync/async dual API. Test via resolver mocks.
8. **dump_loader.py** — Streaming ingestion. Test with small fixture dump.
9. **cli.py** — Click commands wrapping the above.
10. **test_integration.py** — End-to-end with fixture data.

## Testing strategy

- Unit tests mock the layer below (resolver mocks DB/API, client mocks resolver)
- Integration test uses a real DuckDB (in-memory) + fixture dump + `respx` for API mocking
- No real network calls in CI — all API interactions mocked
- `fixtures/sample_dump.json.gz` contains ~100 curated entities (Q42, Q1, Q5, etc.) in real Wikidata JSON format
- Target: 90%+ coverage

## Filter configuration (filter.yaml)

```yaml
# Keep entities that match ANY of these conditions
filters:
  # By instance_of (P31) — keep all humans, cities, countries
  instance_of:
    - Q5        # human
    - Q515      # city
    - Q6256     # country

  # By specific QID list
  qids:
    - Q42       # Douglas Adams
    - Q1        # Universe

  # By property presence — keep anything with a chemical formula
  has_property:
    - P274      # chemical formula

  # Keep all properties (P-items) and their metadata
  keep_properties: true

# Which languages to retain for labels/descriptions/aliases
languages:
  - en
  - es
  - de
```

## Non-goals (out of scope)

- **No SPARQL support.** The entire point is to avoid SPARQL. Complex relational queries should be done directly against DuckDB with SQL.
- **No write-back to Wikidata.** This is read-only.
- **No real-time streaming updates.** Monthly dump refresh + live API fallback is sufficient.
- **No embedded SPARQL endpoint** (no QLever/qEndpoint). Just a DuckDB file with a Python API.

## Relevant Wikidata API details

- Entity endpoint: `GET /w/api.php?action=wbgetentities&ids=Q42&format=json`
- Batch: up to 50 IDs comma-separated: `&ids=Q42|Q1|Q5`
- Search: `GET /w/api.php?action=wbsearchentities&search=Douglas+Adams&language=en&format=json`
- JSON dump URL: `https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz` (~90GB)
- Filtered dumps via wdumper: `https://wdumps.toolforge.org/`
- User-Agent policy: MUST include contact info. Requests without proper UA may be blocked.
- Rate limits: No official published limit, but >5 req/s from a single IP risks 429s. Be conservative.