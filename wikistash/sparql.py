"""SPARQL execution — parse, compile, execute, format."""

from __future__ import annotations

from typing import Any

import duckdb
import structlog

from wikistash.sparql_compiler import compile_sparql
from wikistash.sparql_parser import parse_sparql

log = structlog.get_logger()


def execute_sparql(
    conn: duckdb.DuckDBPyConnection,
    query: str,
) -> list[dict[str, Any]]:
    """Parse a SPARQL query, compile to SQL, execute against DuckDB, return results.

    Returns a list of row dicts with SPARQL variable names as keys.
    """
    parsed = parse_sparql(query)
    sql, params = compile_sparql(parsed)
    log.debug("sparql_compiled", sql=sql, params=params)

    result = conn.execute(sql, params)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()

    return [dict(zip(columns, row)) for row in rows]


_WD_ENTITY_URI = "http://www.wikidata.org/entity/"


def _to_binding_value(key: str, value: Any) -> dict[str, str] | None:
    """Convert a flat result value to a SPARQL JSON binding value.

    Returns None for NULL values (omitted from bindings per spec).
    """
    if value is None:
        return None
    s = str(value)
    # Entity QIDs → URI binding
    if key not in ("itemLabel", "itemDescription") and _looks_like_qid(s):
        return {"type": "uri", "value": f"{_WD_ENTITY_URI}{s}"}
    return {"type": "literal", "value": s}


def _looks_like_qid(s: str) -> bool:
    """Check if a string looks like a Wikidata QID (Q followed by digits)."""
    return len(s) >= 2 and s[0] == "Q" and s[1:].isdigit()


def execute_sparql_json(
    conn: duckdb.DuckDBPyConnection,
    query: str,
) -> dict[str, Any]:
    """Execute SPARQL and return results in standard SPARQL JSON Results format.

    Returns the ``{"results": {"bindings": [...]}}`` structure that
    the Wikidata Query Service returns, so consumer apps can use
    wikistash as a drop-in replacement with no parsing changes.
    """
    rows = execute_sparql(conn, query)
    bindings: list[dict[str, dict[str, str]]] = []
    for row in rows:
        binding: dict[str, dict[str, str]] = {}
        for key, value in row.items():
            bv = _to_binding_value(key, value)
            if bv is not None:
                binding[key] = bv
        bindings.append(binding)
    return {"results": {"bindings": bindings}}
