"""Tests for sparql_parser.py — SPARQL text to IR."""

import pytest

from wikistash.exceptions import SparqlParseError
from wikistash.sparql_parser import parse_sparql


class TestSelectParsing:
    def test_basic_select(self):
        q = "SELECT ?item ?label WHERE { ?item wdt:P31 wd:Q5 . } LIMIT 10"
        parsed = parse_sparql(q)
        assert parsed.select_vars == ["item", "label"]
        assert parsed.limit == 10
        assert not parsed.distinct

    def test_select_distinct(self):
        q = "SELECT DISTINCT ?item WHERE { ?item wdt:P31 wd:Q5 . }"
        parsed = parse_sparql(q)
        assert parsed.distinct is True
        assert parsed.select_vars == ["item"]

    def test_limit_offset(self):
        q = "SELECT ?item WHERE { ?item wdt:P31 wd:Q5 . } LIMIT 1000 OFFSET 500"
        parsed = parse_sparql(q)
        assert parsed.limit == 1000
        assert parsed.offset == 500

    def test_no_limit(self):
        q = "SELECT ?item WHERE { ?item wdt:P31 wd:Q5 . }"
        parsed = parse_sparql(q)
        assert parsed.limit is None
        assert parsed.offset is None


class TestTriplePatterns:
    def test_basic_triple(self):
        q = "SELECT ?item WHERE { ?item wdt:P31 wd:Q5 . }"
        parsed = parse_sparql(q)
        assert len(parsed.triple_patterns) == 1
        tp = parsed.triple_patterns[0]
        assert tp.subject == "item"
        assert tp.predicate == "wdt:P31"
        assert tp.object == "wd:Q5"
        assert tp.is_optional is False

    def test_variable_object(self):
        q = "SELECT ?item ?date WHERE { ?item wdt:P569 ?date . }"
        parsed = parse_sparql(q)
        tp = parsed.triple_patterns[0]
        assert tp.object == "date"

    def test_semicolon_expansion(self):
        q = """SELECT ?item ?birthDate WHERE {
            ?item wdt:P106 wd:Q36180 ;
                  wdt:P569 ?birthDate .
        }"""
        parsed = parse_sparql(q)
        assert len(parsed.triple_patterns) == 2
        assert parsed.triple_patterns[0].predicate == "wdt:P106"
        assert parsed.triple_patterns[0].object == "wd:Q36180"
        assert parsed.triple_patterns[1].predicate == "wdt:P569"
        assert parsed.triple_patterns[1].object == "birthDate"
        # Both share subject
        assert parsed.triple_patterns[0].subject == "item"
        assert parsed.triple_patterns[1].subject == "item"

    def test_sitelinks_triple(self):
        q = "SELECT ?item WHERE { ?item wikibase:sitelinks ?sitelinks . }"
        parsed = parse_sparql(q)
        tp = parsed.triple_patterns[0]
        assert tp.predicate == "wikibase:sitelinks"
        assert tp.object == "sitelinks"


class TestValuesClause:
    def test_single_values(self):
        q = """SELECT ?item WHERE {
            VALUES ?eventType { wd:Q10931 wd:Q131569 wd:Q198 }
            ?item wdt:P31 ?eventType .
        }"""
        parsed = parse_sparql(q)
        assert len(parsed.values_clauses) == 1
        vc = parsed.values_clauses[0]
        assert vc.variable == "eventType"
        assert vc.values == ["wd:Q10931", "wd:Q131569", "wd:Q198"]


class TestOptional:
    def test_optional_triple(self):
        q = """SELECT ?item ?deathDate WHERE {
            ?item wdt:P569 ?birthDate .
            OPTIONAL { ?item wdt:P570 ?deathDate . }
        }"""
        parsed = parse_sparql(q)
        required = [tp for tp in parsed.triple_patterns if not tp.is_optional]
        optional = [tp for tp in parsed.triple_patterns if tp.is_optional]
        assert len(required) == 1
        assert len(optional) == 1
        assert optional[0].predicate == "wdt:P570"

    def test_optional_with_schema(self):
        """schema: triples inside OPTIONAL should be skipped."""
        q = """SELECT ?item ?article WHERE {
            ?item wdt:P31 wd:Q5 .
            OPTIONAL {
                ?article schema:about ?item .
                ?article schema:isPartOf <https://en.wikipedia.org/> .
            }
        }"""
        parsed = parse_sparql(q)
        # schema triples should be ignored
        optional = [tp for tp in parsed.triple_patterns if tp.is_optional]
        assert len(optional) == 0


class TestFilter:
    def test_basic_filter(self):
        q = """SELECT ?item WHERE {
            ?item wikibase:sitelinks ?sitelinks .
            FILTER(?sitelinks >= 20)
        }"""
        parsed = parse_sparql(q)
        assert len(parsed.filters) == 1
        f = parsed.filters[0]
        assert f.variable == "sitelinks"
        assert f.operator == ">="
        assert f.value == 20


class TestLabelService:
    def test_label_service(self):
        q = """SELECT ?item ?itemLabel WHERE {
            ?item wdt:P31 wd:Q5 .
            SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }"""
        parsed = parse_sparql(q)
        assert parsed.label_service is not None
        assert parsed.label_service.language == "en"

    def test_no_label_service(self):
        q = "SELECT ?item WHERE { ?item wdt:P31 wd:Q5 . }"
        parsed = parse_sparql(q)
        assert parsed.label_service is None


class TestComments:
    def test_hash_comments_stripped(self):
        q = """# This is a comment
        SELECT ?item WHERE {
            ?item wdt:P31 wd:Q5 .  # inline won't break since it's after the triple
        }"""
        parsed = parse_sparql(q)
        assert len(parsed.triple_patterns) >= 1

    def test_dash_comments_stripped(self):
        q = """-- e.g. writer, physicist
        SELECT ?item WHERE {
            ?item wdt:P106 wd:Q36180 .
        }"""
        parsed = parse_sparql(q)
        assert len(parsed.triple_patterns) == 1


class TestFullPatterns:
    def test_pattern1_events(self):
        q = """SELECT DISTINCT ?item ?itemLabel ?itemDescription ?date ?eventType ?eventTypeLabel ?article
        WHERE {
          VALUES ?eventType {
            wd:Q10931  wd:Q131569  wd:Q198  wd:Q3024240  wd:Q39546
          }
          ?item wdt:P31 ?eventType .
          ?item wdt:P585 ?date .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          OPTIONAL {
            ?article schema:about ?item .
            ?article schema:isPartOf <https://en.wikipedia.org/> .
          }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        LIMIT 2000 OFFSET 0"""
        parsed = parse_sparql(q)
        assert parsed.distinct is True
        assert "item" in parsed.select_vars
        assert "itemLabel" in parsed.select_vars
        assert "date" in parsed.select_vars
        assert parsed.limit == 2000
        assert parsed.offset == 0
        assert len(parsed.values_clauses) == 1
        assert parsed.values_clauses[0].variable == "eventType"
        assert len(parsed.values_clauses[0].values) == 5
        assert parsed.label_service is not None
        assert len(parsed.filters) == 1
        assert parsed.filters[0].variable == "sitelinks"
        # Should have: P31 ?eventType, P585 ?date, sitelinks
        required = [tp for tp in parsed.triple_patterns if not tp.is_optional]
        predicates = [tp.predicate for tp in required]
        assert "wdt:P31" in predicates
        assert "wdt:P585" in predicates
        assert "wikibase:sitelinks" in predicates

    def test_pattern2_people(self):
        q = """SELECT ?item ?itemLabel ?birthDate ?deathDate
        WHERE {
          ?item wdt:P106 wd:Q36180 ;
                wdt:P569 ?birthDate .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          OPTIONAL { ?item wdt:P570 ?deathDate . }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        LIMIT 1000 OFFSET 0"""
        parsed = parse_sparql(q)
        assert parsed.limit == 1000
        required = [tp for tp in parsed.triple_patterns if not tp.is_optional]
        optional = [tp for tp in parsed.triple_patterns if tp.is_optional]
        req_preds = [tp.predicate for tp in required]
        assert "wdt:P106" in req_preds
        assert "wdt:P569" in req_preds
        assert "wikibase:sitelinks" in req_preds
        assert len(optional) == 1
        assert optional[0].predicate == "wdt:P570"


class TestErrors:
    def test_missing_where(self):
        with pytest.raises(SparqlParseError):
            parse_sparql("SELECT ?item { ?item wdt:P31 wd:Q5 . }")

    def test_missing_select(self):
        with pytest.raises(SparqlParseError):
            parse_sparql("WHERE { ?item wdt:P31 wd:Q5 . }")
