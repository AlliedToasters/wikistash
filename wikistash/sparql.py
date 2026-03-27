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
