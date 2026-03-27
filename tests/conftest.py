"""Shared test fixtures for wikistash."""

import pytest

from wikistash.config import WikiStashConfig


@pytest.fixture
def sample_entity_raw() -> dict:
    """Raw Wikidata JSON for Q42 (Douglas Adams), simplified but realistic."""
    return {
        "type": "item",
        "id": "Q42",
        "labels": {
            "en": {"language": "en", "value": "Douglas Adams"},
            "de": {"language": "de", "value": "Douglas Adams"},
        },
        "descriptions": {
            "en": {
                "language": "en",
                "value": "English author and humourist",
            },
        },
        "aliases": {
            "en": [
                {"language": "en", "value": "Douglas Noel Adams"},
                {"language": "en", "value": "Douglas N. Adams"},
            ],
        },
        "claims": {
            "P31": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P31",
                        "datavalue": {
                            "value": {
                                "entity-type": "item",
                                "numeric-id": 5,
                                "id": "Q5",
                            },
                            "type": "wikibase-entityid",
                        },
                    },
                    "type": "statement",
                    "rank": "normal",
                }
            ],
            "P569": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P569",
                        "datavalue": {
                            "value": {
                                "time": "+1952-03-11T00:00:00Z",
                                "timezone": 0,
                                "before": 0,
                                "after": 0,
                                "precision": 11,
                                "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
                            },
                            "type": "time",
                        },
                    },
                    "type": "statement",
                    "rank": "normal",
                    "qualifiers": {
                        "P805": [
                            {
                                "snaktype": "value",
                                "property": "P805",
                                "datavalue": {
                                    "value": {
                                        "entity-type": "item",
                                        "numeric-id": 123,
                                        "id": "Q123",
                                    },
                                    "type": "wikibase-entityid",
                                },
                            }
                        ]
                    },
                }
            ],
            "P21": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P21",
                        "datavalue": {
                            "value": {
                                "entity-type": "item",
                                "numeric-id": 6581097,
                                "id": "Q6581097",
                            },
                            "type": "wikibase-entityid",
                        },
                    },
                    "type": "statement",
                    "rank": "normal",
                }
            ],
        },
        "sitelinks": {
            "enwiki": {"site": "enwiki", "title": "Douglas Adams"},
            "dewiki": {"site": "dewiki", "title": "Douglas Adams"},
            "frwiki": {"site": "frwiki", "title": "Douglas Adams"},
            "eswiki": {"site": "eswiki", "title": "Douglas Adams"},
            "itwiki": {"site": "itwiki", "title": "Douglas Adams"},
            "jawiki": {"site": "jawiki", "title": "ダグラス・アダムズ"},
            "zhwiki": {"site": "zhwiki", "title": "道格拉斯·亚当斯"},
            "ruwiki": {"site": "ruwiki", "title": "Адамс, Дуглас"},
            "ptwiki": {"site": "ptwiki", "title": "Douglas Adams"},
            "plwiki": {"site": "plwiki", "title": "Douglas Adams"},
            "nlwiki": {"site": "nlwiki", "title": "Douglas Adams"},
            "svwiki": {"site": "svwiki", "title": "Douglas Adams"},
            "fiwiki": {"site": "fiwiki", "title": "Douglas Adams"},
            "nowiki": {"site": "nowiki", "title": "Douglas Adams"},
            "dawiki": {"site": "dawiki", "title": "Douglas Adams"},
            "kowiki": {"site": "kowiki", "title": "더글러스 애덤스"},
            "cswiki": {"site": "cswiki", "title": "Douglas Adams"},
            "huwiki": {"site": "huwiki", "title": "Douglas Adams"},
            "cawiki": {"site": "cawiki", "title": "Douglas Adams"},
            "ukwiki": {"site": "ukwiki", "title": "Дуглас Адамс"},
            "arwiki": {"site": "arwiki", "title": "دوغلاس آدمز"},
            "hewiki": {"site": "hewiki", "title": "דאגלס אדמס"},
            "trwiki": {"site": "trwiki", "title": "Douglas Adams"},
            "idwiki": {"site": "idwiki", "title": "Douglas Adams"},
            "rowiki": {"site": "rowiki", "title": "Douglas Adams"},
        },
    }


@pytest.fixture
def sample_entity_raw_q1() -> dict:
    """Raw Wikidata JSON for Q1 (Universe), minimal."""
    return {
        "type": "item",
        "id": "Q1",
        "labels": {
            "en": {"language": "en", "value": "Universe"},
        },
        "descriptions": {
            "en": {
                "language": "en",
                "value": "totality of space and all its contents",
            },
        },
        "aliases": {},
        "sitelinks": {
            "enwiki": {"site": "enwiki", "title": "Universe"},
            "dewiki": {"site": "dewiki", "title": "Universum"},
            "frwiki": {"site": "frwiki", "title": "Univers"},
        },
        "claims": {
            "P31": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P31",
                        "datavalue": {
                            "value": {
                                "entity-type": "item",
                                "numeric-id": 36906466,
                                "id": "Q36906466",
                            },
                            "type": "wikibase-entityid",
                        },
                    },
                    "type": "statement",
                    "rank": "normal",
                }
            ],
        },
    }


@pytest.fixture
def config(tmp_path) -> WikiStashConfig:
    """Test config with temp paths and live fallback disabled."""
    return WikiStashConfig(
        local_db_path=tmp_path / "test.duckdb",
        cache_db_path=tmp_path / "test_cache.sqlite",
        enable_live_fallback=False,
    )


def _make_entity(qid, label, description, claims_data, sitelink_count=1):
    """Helper to build a raw Wikidata entity dict for testing."""
    claims = {}
    for prop_id, values in claims_data.items():
        stmts = []
        for val in values:
            if isinstance(val, str) and val.startswith("Q"):
                datavalue = {
                    "value": {"entity-type": "item", "numeric-id": int(val[1:]), "id": val},
                    "type": "wikibase-entityid",
                }
            elif isinstance(val, str) and val.startswith("+"):
                datavalue = {
                    "value": {"time": val, "timezone": 0, "before": 0, "after": 0, "precision": 11,
                              "calendarmodel": "http://www.wikidata.org/entity/Q1985727"},
                    "type": "time",
                }
            else:
                datavalue = {"value": str(val), "type": "string"}
            stmts.append({
                "mainsnak": {"snaktype": "value", "property": prop_id, "datavalue": datavalue},
                "type": "statement", "rank": "normal",
            })
        claims[prop_id] = stmts

    sitelinks = {f"wiki{i}": {"site": f"wiki{i}", "title": label} for i in range(sitelink_count)}

    return {
        "type": "item", "id": qid,
        "labels": {"en": {"language": "en", "value": label}},
        "descriptions": {"en": {"language": "en", "value": description}},
        "aliases": {},
        "sitelinks": sitelinks,
        "claims": claims,
    }


@pytest.fixture
def sparql_entities():
    """Entities designed to test SPARQL query patterns."""
    return [
        # Events (P31=Q198 war, with P585 date)
        _make_entity("Q362", "World War II", "global war 1939-1945",
                      {"P31": ["Q198"], "P585": ["+1939-09-01T00:00:00Z"]},
                      sitelink_count=30),
        _make_entity("Q361", "World War I", "global war 1914-1918",
                      {"P31": ["Q198"], "P585": ["+1914-07-28T00:00:00Z"]},
                      sitelink_count=25),
        _make_entity("Q8680", "French Revolution", "revolution in France",
                      {"P31": ["Q10931"], "P585": ["+1789-07-14T00:00:00Z"]},
                      sitelink_count=22),
        # Low sitelinks event (should be filtered out at threshold 20)
        _make_entity("Q99901", "Minor Skirmish", "a small event",
                      {"P31": ["Q198"], "P585": ["+2020-01-01T00:00:00Z"]},
                      sitelink_count=3),

        # People (P106=occupation, P569=birth, P570=death optional)
        _make_entity("Q535", "Victor Hugo", "French writer",
                      {"P106": ["Q36180"], "P569": ["+1802-02-26T00:00:00Z"],
                       "P570": ["+1885-05-22T00:00:00Z"]},
                      sitelink_count=28),
        _make_entity("Q1339", "Johann Sebastian Bach", "German composer",
                      {"P106": ["Q36180"], "P569": ["+1685-03-31T00:00:00Z"],
                       "P570": ["+1750-07-28T00:00:00Z"]},
                      sitelink_count=30),
        # Living person (no P570)
        _make_entity("Q99902", "Living Writer", "contemporary author",
                      {"P106": ["Q36180"], "P569": ["+1980-06-15T00:00:00Z"]},
                      sitelink_count=22),
        # Below sitelinks threshold
        _make_entity("Q99903", "Unknown Writer", "obscure author",
                      {"P106": ["Q36180"], "P569": ["+1990-01-01T00:00:00Z"]},
                      sitelink_count=5),

        # Organism (P31=Q16521, P105=taxon rank, P171=parent taxon)
        _make_entity("Q140", "lion", "species of large cat",
                      {"P31": ["Q16521"], "P105": ["Q7432"], "P171": ["Q127960"]},
                      sitelink_count=10),
    ]
