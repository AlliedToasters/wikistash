"""Tests for models.py — entity parsing and model behavior."""

from wikistash.models import parse_entity


class TestParseEntity:
    def test_basic_fields(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        assert entity.qid == "Q42"
        assert entity.entity_type == "item"
        assert entity.label == "Douglas Adams"
        assert entity.description == "English author and humourist"

    def test_aliases(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        assert "Douglas Noel Adams" in entity.aliases
        assert "Douglas N. Adams" in entity.aliases

    def test_claims_by_pid(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        claims = entity["P31"]
        assert len(claims) == 1
        assert claims[0].property_id == "P31"
        assert claims[0].value is not None
        assert claims[0].value.entity_id == "Q5"

    def test_time_claim(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        claims = entity["P569"]
        assert len(claims) == 1
        assert claims[0].value is not None
        assert claims[0].value.time_value == "+1952-03-11T00:00:00Z"

    def test_qualifiers(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        claim = entity["P569"][0]
        assert "P805" in claim.qualifiers
        assert claim.qualifiers["P805"][0].entity_id == "Q123"

    def test_missing_property_raises_key_error(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        import pytest

        with pytest.raises(KeyError):
            entity["P9999"]

    def test_different_language(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw, lang="de")
        assert entity.label == "Douglas Adams"
        assert entity.description is None  # no German description in fixture

    def test_missing_language(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw, lang="fr")
        assert entity.label is None
        assert entity.description is None
        assert entity.aliases == []

    def test_empty_entity(self):
        entity = parse_entity({"id": "Q999", "type": "item"})
        assert entity.qid == "Q999"
        assert entity.label is None
        assert entity.claims == {}

    def test_property_entity(self):
        raw = {
            "id": "P31",
            "type": "property",
            "datatype": "wikibase-item",
            "labels": {"en": {"language": "en", "value": "instance of"}},
            "descriptions": {},
            "aliases": {},
            "claims": {},
        }
        entity = parse_entity(raw)
        assert entity.qid == "P31"
        assert entity.entity_type == "property"
        assert entity.datatype == "wikibase-item"
        assert entity.label == "instance of"


class TestClaimValue:
    def test_entity_id(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        val = entity["P31"][0].value
        assert val is not None
        assert val.entity_id == "Q5"
        assert val.time_value is None
        assert val.amount is None
        assert val.text is None

    def test_time_value(self, sample_entity_raw):
        entity = parse_entity(sample_entity_raw)
        val = entity["P569"][0].value
        assert val is not None
        assert val.time_value == "+1952-03-11T00:00:00Z"
        assert val.entity_id is None
