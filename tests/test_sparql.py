"""End-to-end SPARQL tests against real DuckDB."""

import pytest

from wikistash.local_db import LocalDB
from wikistash.sparql import execute_sparql, execute_sparql_json


@pytest.fixture
def db_with_data(tmp_path, sparql_entities):
    """LocalDB loaded with SPARQL test entities."""
    db = LocalDB(tmp_path / "sparql_test.duckdb")
    db.put_batch(sparql_entities, languages=["en"])
    yield db
    db.close()


class TestEventQueries:
    def test_events_by_type_with_date(self, db_with_data):
        """Pattern 1: events by type, filtered by sitelinks."""
        query = """
        SELECT DISTINCT ?item ?itemLabel ?itemDescription ?date ?eventType ?eventTypeLabel
        WHERE {
          VALUES ?eventType { wd:Q10931 wd:Q198 }
          ?item wdt:P31 ?eventType .
          ?item wdt:P585 ?date .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        LIMIT 2000 OFFSET 0
        """
        results = execute_sparql(db_with_data.get_connection(), query)

        # Should get WW2, WW1, French Revolution (all >= 20 sitelinks)
        # Should NOT get Minor Skirmish (only 3 sitelinks)
        qids = [r["item"] for r in results]
        assert "Q362" in qids  # WW2
        assert "Q361" in qids  # WW1
        assert "Q8680" in qids  # French Revolution
        assert "Q99901" not in qids  # Minor Skirmish (below threshold)

        # Check labels resolved
        ww2 = next(r for r in results if r["item"] == "Q362")
        assert ww2["itemLabel"] == "World War II"
        assert ww2["itemDescription"] == "global war 1939-1945"
        assert "+1939" in ww2["date"]

    def test_events_offset(self, db_with_data):
        """Pagination with OFFSET."""
        query = """
        SELECT ?item WHERE {
          VALUES ?eventType { wd:Q10931 wd:Q198 }
          ?item wdt:P31 ?eventType .
          ?item wdt:P585 ?date .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
        }
        LIMIT 1 OFFSET 0
        """
        results = execute_sparql(db_with_data.get_connection(), query)
        assert len(results) == 1

        query2 = """
        SELECT ?item WHERE {
          VALUES ?eventType { wd:Q10931 wd:Q198 }
          ?item wdt:P31 ?eventType .
          ?item wdt:P585 ?date .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
        }
        LIMIT 1 OFFSET 1
        """
        results2 = execute_sparql(db_with_data.get_connection(), query2)
        assert len(results2) == 1
        assert results[0]["item"] != results2[0]["item"]


class TestPeopleQueries:
    def test_people_by_occupation(self, db_with_data):
        """Pattern 2: people by occupation with birth/death dates."""
        query = """
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
        """
        results = execute_sparql(db_with_data.get_connection(), query)

        qids = [r["item"] for r in results]
        assert "Q535" in qids  # Victor Hugo (28 sitelinks)
        assert "Q1339" in qids  # Bach (30 sitelinks)
        assert "Q99902" in qids  # Living Writer (22 sitelinks)
        assert "Q99903" not in qids  # Unknown Writer (5 sitelinks, below 20)

        # Check Victor Hugo has death date
        hugo = next(r for r in results if r["item"] == "Q535")
        assert hugo["itemLabel"] == "Victor Hugo"
        assert "+1802" in hugo["birthDate"]
        assert "+1885" in hugo["deathDate"]

        # Living Writer should have NULL death date
        living = next(r for r in results if r["item"] == "Q99902")
        assert living["deathDate"] is None


class TestOrganismQueries:
    def test_organisms_by_rank(self, db_with_data):
        """Pattern 3: organisms with taxon rank and parent taxon."""
        query = """
        SELECT ?item ?itemLabel ?rank ?parentTaxon
        WHERE {
          ?item wdt:P31 wd:Q16521 .
          ?item wdt:P105 ?rank .
          ?item wdt:P171 ?parentTaxon .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 5)
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        LIMIT 1000
        """
        results = execute_sparql(db_with_data.get_connection(), query)

        assert len(results) >= 1
        lion = next(r for r in results if r["item"] == "Q140")
        assert lion["itemLabel"] == "lion"
        assert lion["rank"] == "Q7432"
        assert lion["parentTaxon"] == "Q127960"


class TestEdgeCases:
    def test_no_results(self, db_with_data):
        query = """
        SELECT ?item WHERE {
          ?item wdt:P31 wd:Q99999999 .
        }
        """
        results = execute_sparql(db_with_data.get_connection(), query)
        assert results == []

    def test_schema_about_skipped(self, db_with_data):
        """schema:about triples should be skipped, ?article should be NULL."""
        query = """
        SELECT ?item ?article WHERE {
          ?item wdt:P31 wd:Q198 .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          OPTIONAL {
            ?article schema:about ?item .
            ?article schema:isPartOf <https://en.wikipedia.org/> .
          }
        }
        """
        results = execute_sparql(db_with_data.get_connection(), query)
        assert len(results) >= 1
        for r in results:
            assert r["article"] is None

    def test_distinct(self, db_with_data):
        query = """
        SELECT DISTINCT ?item WHERE {
          ?item wdt:P31 wd:Q198 .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
        }
        """
        results = execute_sparql(db_with_data.get_connection(), query)
        qids = [r["item"] for r in results]
        assert len(qids) == len(set(qids))


class TestSparqlJson:
    """Tests for SPARQL JSON Results format adapter."""

    def test_json_format_structure(self, db_with_data):
        query = """
        SELECT ?item ?itemLabel WHERE {
          ?item wdt:P31 wd:Q198 .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        """
        result = execute_sparql_json(db_with_data.get_connection(), query)
        assert "results" in result
        assert "bindings" in result["results"]
        bindings = result["results"]["bindings"]
        assert len(bindings) >= 1

    def test_json_entity_uris(self, db_with_data):
        """Entity QIDs should be wrapped as full Wikidata URIs."""
        query = """
        SELECT ?item WHERE {
          ?item wdt:P31 wd:Q198 .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
        }
        """
        result = execute_sparql_json(db_with_data.get_connection(), query)
        bindings = result["results"]["bindings"]
        for b in bindings:
            assert b["item"]["value"].startswith("http://www.wikidata.org/entity/Q")
            assert b["item"]["type"] == "uri"

    def test_json_labels_are_literals(self, db_with_data):
        """Labels should be literal values, not URIs."""
        query = """
        SELECT ?item ?itemLabel WHERE {
          ?item wdt:P31 wd:Q198 .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        """
        result = execute_sparql_json(db_with_data.get_connection(), query)
        bindings = result["results"]["bindings"]
        ww2 = next(b for b in bindings
                   if b["item"]["value"] == "http://www.wikidata.org/entity/Q362")
        assert ww2["itemLabel"]["type"] == "literal"
        assert ww2["itemLabel"]["value"] == "World War II"

    def test_json_null_omitted(self, db_with_data):
        """NULL values should be omitted from bindings (per SPARQL spec)."""
        query = """
        SELECT ?item ?deathDate WHERE {
          ?item wdt:P106 wd:Q36180 ;
                wdt:P569 ?birthDate .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          OPTIONAL { ?item wdt:P570 ?deathDate . }
        }
        """
        result = execute_sparql_json(db_with_data.get_connection(), query)
        bindings = result["results"]["bindings"]
        # Q99902 (Living Writer) has no death date
        living = next(b for b in bindings
                      if b["item"]["value"] == "http://www.wikidata.org/entity/Q99902")
        assert "deathDate" not in living

    def test_json_consumer_compatible(self, db_with_data):
        """Verify the consumer app's exact parsing logic works on our output."""
        query = """
        SELECT ?item ?itemLabel ?itemDescription ?date ?eventType ?eventTypeLabel
        WHERE {
          VALUES ?eventType { wd:Q10931 wd:Q198 }
          ?item wdt:P31 ?eventType .
          ?item wdt:P585 ?date .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= 20)
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
        }
        LIMIT 2000
        """
        data = execute_sparql_json(db_with_data.get_connection(), query)
        # Replicate the consumer app's exact parsing logic
        bindings = data.get("results", {}).get("bindings", [])
        rows = []
        for b in bindings:
            row = {}
            for key, val in b.items():
                row[key] = val.get("value", "")
            rows.append(row)

        assert len(rows) >= 3
        ww2 = next(r for r in rows if "Q362" in r["item"])
        assert ww2["itemLabel"] == "World War II"
        assert ww2["itemDescription"] == "global war 1939-1945"
        assert "+1939" in ww2["date"]
