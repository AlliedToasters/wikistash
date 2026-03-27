# wikistash

## Development environment

- **Python venv**: `.venv/` in project root, created with `uv venv`. Activate with `source .venv/bin/activate`.
- **Package manager**: `uv` (available at `~/.local/bin/uv`). Use `uv pip install` instead of `pip install`.
- **Install**: `source .venv/bin/activate && uv pip install -e ".[dev]"`
- **Run tests**: `source .venv/bin/activate && pytest`

## What this project is

wikistash is a local Wikidata query engine. It replaces the remote Wikidata SPARQL endpoint with a local DuckDB-backed store so that an existing SPARQL consumer app can run its queries without hitting rate limits, 502s, or 429s.

The core loop is: download the Wikidata JSON dump, stream-filter it into DuckDB, then run queries against the local store. The live Wikidata entity API (`wbgetentities`) serves as a fallback for entities not in the dump.

## What problem it solves

The Wikidata Query Service (SPARQL endpoint) is rate-limited and unreliable under load. Applications that run batches of SPARQL queries — e.g. pulling all humans by occupation, all historical events by type, all organisms by taxonomic rank — regularly hit 429s and 502/504 errors. Query-level caching helps but breaks when any parameter changes (like a sitelinks threshold bump).

wikistash solves this by making Wikidata local. Instead of asking a remote SPARQL endpoint, queries run against a local DuckDB that was populated from the dump. No rate limits, no network errors, sub-second query times.

## Target query patterns

The consumer app runs structured SPARQL queries that follow common patterns. wikistash needs to support these either via SPARQL-to-SQL translation or a query API that covers the same ground.

### Pattern 1: Entities by type with date properties
```sparql
SELECT ?item ?itemLabel ?date
WHERE {
  VALUES ?eventType { wd:Q10931 wd:Q131569 wd:Q198 }
  ?item wdt:P31 ?eventType .
  ?item wdt:P585 ?date .
  ?item wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= 20)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 2000 OFFSET 0
```

### Pattern 2: People by occupation with birth/death dates
```sparql
SELECT ?item ?itemLabel ?birthDate ?deathDate
WHERE {
  ?item wdt:P106 wd:Q36180 ;
        wdt:P569 ?birthDate .
  ?item wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= 20)
  OPTIONAL { ?item wdt:P570 ?deathDate . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 1000 OFFSET 0
```
Runs once per occupation QID (writer, physicist, mathematician, politician, etc.)

### Pattern 3: Organisms by taxonomic rank
Queries entities with P31=Q16521, filtered by taxonomic rank (P105), with parent_taxon (P171) for lineage. Runs per rank (species, genus, family, order, class, phylum, kingdom). Uses sitelinks >= 5.

### Common features across all queries
- Paginated with LIMIT/OFFSET (1000 or 2000 per page)
- `wikibase:sitelinks` threshold as a notability filter
- `SERVICE wikibase:label` for English labels
- `OPTIONAL` for nullable properties
- `VALUES` for type lists
- Results consumed as tabular data (currently cached as parquet)

## Architecture

```
Consumer app (existing SPARQL queries)
       │
       ▼
┌─────────────────────┐
│   Query interface   │  ← SPARQL-to-SQL translation or equivalent query API
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│   LocalDB (DuckDB)  │  ← Claims, labels, sitelinks in columnar tables
└─────────────────────┘
       ▲
       │
┌─────────────────────┐
│    DumpLoader       │  ← Streams .json.gz dump into DuckDB
└─────────────────────┘

For entity-level access (single lookups, not bulk queries):

┌─────────────────────┐
│       Stash         │  ← Entity-level get/search facade
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│   EntityResolver    │  ← local DB → entity cache → live API fallback
└─────┬───────────┬───┘
      │           │
      ▼           ▼
┌──────────┐ ┌───────────────┐
│ LocalDB  │ │ LiveAPIClient │
│ (DuckDB) │ │ + EntityCache │
└──────────┘ └───────────────┘
```

## DuckDB schema

```sql
-- Raw entity JSON for entity-level access
entities(qid TEXT PRIMARY KEY, data JSON, dump_date DATE, source TEXT)

-- Decomposed for relational queries
claims(qid TEXT, property TEXT, value JSON, rank TEXT, qualifiers JSON)
  -- index on (qid, property) and (property, value) for type lookups

labels(qid TEXT, lang TEXT, value TEXT)
  -- index on (qid, lang)

descriptions(qid TEXT, lang TEXT, value TEXT)

aliases(qid TEXT, lang TEXT, values JSON)

-- Needed for notability filtering
sitelinks(qid TEXT, count INTEGER)
  -- index on (qid)
```

The `sitelinks` table is critical — almost every query in the consumer app filters by sitelink count as a notability threshold.

## What exists today (first pass, complete)

Entity-level access works end-to-end:
- `Stash` facade with `get()` (single + batch), `search()`, `duckdb()` escape hatch
- `EntityResolver` tier routing: local DB → SQLite entity cache → live Wikidata API
- `LocalDB` with DuckDB (put/get/batch, decomposed tables)
- `EntityCache` with SQLite LRU + TTL
- `LiveAPIClient` with rate limiting, retries, 429/5xx handling
- `DumpLoader` for streaming .json.gz ingestion with QID filtering
- `cli.py` with `wikistash load` and `wikistash get` commands
- 58 tests passing across all layers + integration

Live API smoke-tested successfully against real Wikidata.

## What's missing (next steps)

1. **Sitelinks table** — the dump loader doesn't extract sitelink counts yet. Every target query uses sitelinks for filtering.
2. **SPARQL-to-SQL translation** (or equivalent query API) — the consumer app sends SPARQL; wikistash needs to answer it. The query patterns are structured enough that a subset translator covering `VALUES`, `OPTIONAL`, `FILTER`, `SERVICE wikibase:label`, `LIMIT/OFFSET`, and basic triple patterns against `wdt:` properties should suffice.
3. **Dump filtering by P31/property** — currently only QID-list filtering. Need `instance_of` and `has_property` filters for practical dump loads.
4. **Dump download** — `wikistash load --download latest` to fetch the dump automatically with resume support.
5. **Index tuning** — `(property, value)` index on claims for fast type lookups (`P31 = Q5`).

## Technical stack

- **Python 3.10+**, type-annotated, `py.typed`
- **DuckDB** — columnar store, native JSON support, fast analytical queries
- **httpx** — HTTP client for Wikidata API
- **pydantic** / **pydantic-settings** — models and config
- **orjson** — fast JSON parsing for dump streaming
- **click** — CLI
- **structlog** — structured logging
- **pytest** + **respx** — testing with mocked HTTP

## Dump details

See `DUMPS.md` for download sources and practical notes.

- Canonical: `https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz` (~142GB)
- Use gzip, not bz2 (bz2 is smaller but much slower to decompress during streaming)
- Wikimedia rate-limits downloads to ~4-5 MB/s per IP
- `wget -c` for resume support
- Stream-filter during decompression — never need 142GB on disk, just the filtered DuckDB

## Wikidata API reference

- Entity lookup: `GET /w/api.php?action=wbgetentities&ids=Q42&format=json`
- Batch: up to 50 IDs pipe-separated: `&ids=Q42|Q1|Q5`
- Search: `GET /w/api.php?action=wbsearchentities&search=Douglas+Adams&language=en&format=json`
- User-Agent policy: MUST include contact info or requests may be blocked
- Rate limits: >5 req/s from a single IP risks 429s

## Non-goals

- **Write-back to Wikidata.** Read-only.
- **Real-time streaming updates.** Periodic dump refresh + API fallback is sufficient.
- **Full SPARQL spec.** Only the subset used by the consumer app needs to work.
