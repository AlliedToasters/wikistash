"""Tests for sparql_compiler.py — IR to DuckDB SQL."""

from wikistash.sparql_compiler import compile_sparql
from wikistash.sparql_parser import (
    Filter,
    LabelService,
    SparqlQuery,
    TriplePattern,
    ValuesClause,
)


class TestBasicCompilation:
    def test_simple_type_match(self):
        """?item wdt:P31 wd:Q5 -> claims WHERE property='P31' AND value.id='Q5'"""
        q = SparqlQuery(
            select_vars=["item"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
            ],
        )
        sql, params = compile_sparql(q)
        assert "FROM claims c0" in sql
        assert "P31" in params
        assert "Q5" in params
        assert "json_extract_string" in sql

    def test_variable_object_projection(self):
        """?item wdt:P569 ?date -> join claims, extract time value."""
        q = SparqlQuery(
            select_vars=["item", "date"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
                TriplePattern(subject="item", predicate="wdt:P569", object="date"),
            ],
        )
        sql, params = compile_sparql(q)
        assert "JOIN claims c1" in sql
        assert "c1.qid = c0.qid" in sql
        assert "$.value.time" in sql  # P569 is a time property


class TestValues:
    def test_values_in_clause(self):
        q = SparqlQuery(
            select_vars=["item"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="eventType"),
            ],
            values_clauses=[
                ValuesClause(variable="eventType", values=["wd:Q10931", "wd:Q198"]),
            ],
        )
        sql, params = compile_sparql(q)
        assert "IN" in sql
        assert "Q10931" in params
        assert "Q198" in params


class TestOptional:
    def test_optional_left_join(self):
        q = SparqlQuery(
            select_vars=["item", "deathDate"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P569", object="birthDate"),
                TriplePattern(
                    subject="item",
                    predicate="wdt:P570",
                    object="deathDate",
                    is_optional=True,
                ),
            ],
        )
        sql, params = compile_sparql(q)
        assert "LEFT JOIN claims" in sql
        assert "P570" in params


class TestSitelinks:
    def test_sitelinks_join_with_filter(self):
        q = SparqlQuery(
            select_vars=["item"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
                TriplePattern(
                    subject="item", predicate="wikibase:sitelinks", object="sitelinks"
                ),
            ],
            filters=[Filter(variable="sitelinks", operator=">=", value=20)],
        )
        sql, params = compile_sparql(q)
        assert "JOIN sitelinks sl0" in sql
        assert "sl0.count >=" in sql
        assert 20 in params


class TestLabels:
    def test_label_join(self):
        q = SparqlQuery(
            select_vars=["item", "itemLabel"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
            ],
            label_service=LabelService(language="en"),
        )
        sql, params = compile_sparql(q)
        assert "LEFT JOIN labels lbl_item" in sql
        assert "lbl_item.lang = ?" in sql
        assert "en" in params
        assert "lbl_item.value AS itemLabel" in sql

    def test_description_join(self):
        q = SparqlQuery(
            select_vars=["item", "itemDescription"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
            ],
            label_service=LabelService(language="en"),
        )
        sql, params = compile_sparql(q)
        assert "LEFT JOIN descriptions desc_item" in sql
        assert "desc_item.value AS itemDescription" in sql

    def test_variable_label(self):
        """Labels for non-subject variables (e.g. ?eventTypeLabel)."""
        q = SparqlQuery(
            select_vars=["item", "eventType", "eventTypeLabel"],
            triple_patterns=[
                TriplePattern(
                    subject="item", predicate="wdt:P31", object="eventType"
                ),
            ],
            label_service=LabelService(language="en"),
        )
        sql, params = compile_sparql(q)
        assert "lbl_eventType" in sql


class TestDistinctLimitOffset:
    def test_distinct(self):
        q = SparqlQuery(
            select_vars=["item"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
            ],
            distinct=True,
        )
        sql, _ = compile_sparql(q)
        assert "SELECT DISTINCT" in sql

    def test_limit_offset(self):
        q = SparqlQuery(
            select_vars=["item"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
            ],
            limit=1000,
            offset=500,
        )
        sql, _ = compile_sparql(q)
        assert "LIMIT 1000" in sql
        assert "OFFSET 500" in sql


class TestUnknownVariables:
    def test_unknown_var_becomes_null(self):
        """Variables not bound by any pattern (e.g. ?article) get NULL."""
        q = SparqlQuery(
            select_vars=["item", "article"],
            triple_patterns=[
                TriplePattern(subject="item", predicate="wdt:P31", object="wd:Q5"),
            ],
        )
        sql, _ = compile_sparql(q)
        assert "NULL AS article" in sql
