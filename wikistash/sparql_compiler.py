"""SPARQL compiler — translates IR to DuckDB SQL."""

from __future__ import annotations

from typing import Any

from wikistash.sparql_parser import SparqlQuery

# Well-known property types for value extraction
ENTITY_ID_PROPERTIES = {
    "P31", "P21", "P27", "P50", "P105", "P106", "P131", "P170", "P171",
    "P279", "P361", "P495", "P17", "P36", "P150", "P30", "P138", "P61",
    "P57", "P86",
}
TIME_PROPERTIES = {"P569", "P570", "P571", "P576", "P577", "P580", "P582", "P585"}
QUANTITY_PROPERTIES = {"P1082", "P2044", "P2046", "P2047", "P2048", "P2067"}
MONOLINGUAL_TEXT_PROPERTIES = {"P1843", "P1448", "P1476", "P1705"}


def _property_id(predicate: str) -> str:
    return predicate.split(":")[1]


def _entity_id(obj: str) -> str:
    return obj.split(":")[1] if obj.startswith("wd:") else obj


def _is_variable(obj: str) -> bool:
    return not obj.startswith("wd:")


def _value_extract_expr(alias: str, prop_id: str) -> str:
    if prop_id in ENTITY_ID_PROPERTIES:
        return f"json_extract_string({alias}.value, '$.value.id')"
    elif prop_id in TIME_PROPERTIES:
        return f"json_extract_string({alias}.value, '$.value.time')"
    elif prop_id in QUANTITY_PROPERTIES:
        return f"json_extract_string({alias}.value, '$.value.amount')"
    elif prop_id in MONOLINGUAL_TEXT_PROPERTIES:
        return f"json_extract_string({alias}.value, '$.value.text')"
    else:
        return (
            f"COALESCE("
            f"json_extract_string({alias}.value, '$.value.id'), "
            f"json_extract_string({alias}.value, '$.value.time'), "
            f"json_extract_string({alias}.value, '$.value.amount'), "
            f"json_extract_string({alias}.value, '$.value.text'), "
            f"CAST({alias}.value AS TEXT))"
        )


def compile_sparql(query: SparqlQuery) -> tuple[str, list[Any]]:
    """Compile a parsed SPARQL query to DuckDB SQL.

    Returns (sql_string, parameters).
    Params are ordered to match the positional ? placeholders in the SQL:
    JOINs first, then WHERE.
    """
    var_map: dict[str, str] = {}
    from_clause: str = ""
    # Each join is (sql_fragment, params_list)
    joins: list[tuple[str, list[Any]]] = []
    where_conditions: list[str] = []
    where_params: list[Any] = []
    claim_counter = 0
    sitelink_counter = 0

    # Build maps
    lang_filter_map: dict[str, str] = {}
    for lf in query.lang_filters:
        lang_filter_map[lf.variable] = lf.language

    values_map: dict[str, list[str]] = {}
    for vc in query.values_clauses:
        values_map[vc.variable] = [_entity_id(v) for v in vc.values]

    filter_map: dict[str, list] = {}
    for f in query.filters:
        filter_map.setdefault(f.variable, []).append(f)

    required_triples = [tp for tp in query.triple_patterns if not tp.is_optional]
    optional_triples = [tp for tp in query.triple_patterns if tp.is_optional]

    # Process required triple patterns
    for tp in required_triples:
        if tp.predicate == "wikibase:sitelinks":
            alias = f"sl{sitelink_counter}"
            sitelink_counter += 1
            qid_expr = var_map.get(tp.subject, "c0.qid")
            join_sql = f"JOIN sitelinks {alias} ON {alias}.qid = {qid_expr}"
            join_params: list[Any] = []
            for flt in filter_map.get(tp.object, []):
                join_sql += f" AND {alias}.count {flt.operator} ?"
                join_params.append(flt.value)
            joins.append((join_sql, join_params))
            var_map[tp.object] = f"{alias}.count"
            continue

        prop_id = _property_id(tp.predicate)
        alias = f"c{claim_counter}"
        claim_counter += 1

        if claim_counter == 1:
            # First claim -> FROM clause, conditions go to WHERE
            from_clause = f"FROM claims {alias}"
            where_conditions.append(f"{alias}.property = ?")
            where_params.append(prop_id)

            if not _is_variable(tp.object):
                where_conditions.append(
                    f"json_extract_string({alias}.value, '$.value.id') = ?"
                )
                where_params.append(_entity_id(tp.object))
            elif tp.object in values_map:
                ids = values_map[tp.object]
                placeholders = ", ".join(["?"] * len(ids))
                where_conditions.append(
                    f"json_extract_string({alias}.value, '$.value.id') IN ({placeholders})"
                )
                where_params.extend(ids)
        else:
            # Subsequent claims -> JOIN
            join_sql = f"JOIN claims {alias} ON {alias}.qid = c0.qid AND {alias}.property = ?"
            join_params = [prop_id]

            if not _is_variable(tp.object):
                join_sql += f" AND json_extract_string({alias}.value, '$.value.id') = ?"
                join_params.append(_entity_id(tp.object))
            elif tp.object in values_map:
                ids = values_map[tp.object]
                placeholders = ", ".join(["?"] * len(ids))
                join_sql += f" AND json_extract_string({alias}.value, '$.value.id') IN ({placeholders})"
                join_params.extend(ids)

            if tp.object in lang_filter_map:
                join_sql += f" AND json_extract_string({alias}.value, '$.value.language') = ?"
                join_params.append(lang_filter_map[tp.object])

            joins.append((join_sql, join_params))

        if tp.subject not in var_map:
            var_map[tp.subject] = f"{alias}.qid"

        if _is_variable(tp.object):
            var_map[tp.object] = _value_extract_expr(alias, prop_id)

    # Process optional triple patterns
    for tp in optional_triples:
        if tp.predicate == "wikibase:sitelinks":
            alias = f"sl{sitelink_counter}"
            sitelink_counter += 1
            qid_expr = var_map.get(tp.subject, "c0.qid")
            joins.append((f"LEFT JOIN sitelinks {alias} ON {alias}.qid = {qid_expr}", []))
            var_map[tp.object] = f"{alias}.count"
            continue

        prop_id = _property_id(tp.predicate)
        alias = f"c{claim_counter}"
        claim_counter += 1

        join_sql = f"LEFT JOIN claims {alias} ON {alias}.qid = c0.qid AND {alias}.property = ?"
        join_params = [prop_id]

        if not _is_variable(tp.object):
            join_sql += f" AND json_extract_string({alias}.value, '$.value.id') = ?"
            join_params.append(_entity_id(tp.object))

        if tp.object in lang_filter_map:
            join_sql += f" AND json_extract_string({alias}.value, '$.value.language') = ?"
            join_params.append(lang_filter_map[tp.object])

        joins.append((join_sql, join_params))

        if _is_variable(tp.object):
            var_map[tp.object] = _value_extract_expr(alias, prop_id)

    # Handle label service
    lang = query.label_service.language if query.label_service else "en"

    for var in query.select_vars:
        if var.endswith("Label"):
            base_var = var[: -len("Label")]
            if base_var in var_map:
                qid_expr = var_map[base_var]
                lbl_alias = f"lbl_{base_var}"
                joins.append((
                    f"LEFT JOIN labels {lbl_alias} ON {lbl_alias}.qid = {qid_expr} "
                    f"AND {lbl_alias}.lang = ?",
                    [lang],
                ))
                var_map[var] = f"{lbl_alias}.value"
        elif var.endswith("Description"):
            base_var = var[: -len("Description")]
            if base_var in var_map:
                qid_expr = var_map[base_var]
                desc_alias = f"desc_{base_var}"
                joins.append((
                    f"LEFT JOIN descriptions {desc_alias} ON {desc_alias}.qid = {qid_expr} "
                    f"AND {desc_alias}.lang = ?",
                    [lang],
                ))
                var_map[var] = f"{desc_alias}.value"

    # Build SELECT list
    select_exprs = []
    for var in query.select_vars:
        if var in var_map:
            select_exprs.append(f"{var_map[var]} AS {var}")
        else:
            select_exprs.append(f"NULL AS {var}")

    distinct = "DISTINCT " if query.distinct else ""
    select_clause = f"SELECT {distinct}{', '.join(select_exprs)}"

    # Assemble SQL — params must follow positional order: JOINs then WHERE
    sql_parts = [select_clause, from_clause]
    all_params: list[Any] = []

    for join_sql, join_params in joins:
        sql_parts.append(join_sql)
        all_params.extend(join_params)

    if where_conditions:
        sql_parts.append("WHERE " + " AND ".join(where_conditions))
        all_params.extend(where_params)

    if query.limit is not None:
        sql_parts.append(f"LIMIT {query.limit}")
    if query.offset is not None:
        sql_parts.append(f"OFFSET {query.offset}")

    sql = "\n".join(sql_parts)
    return sql, all_params
