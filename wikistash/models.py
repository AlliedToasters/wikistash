"""Pydantic models for Wikidata entities, claims, and values."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaimValue(BaseModel):
    """A parsed claim value, abstracting over Wikidata's snak types."""

    value_type: str
    raw_value: dict[str, Any] | str = Field(default_factory=dict)

    @property
    def entity_id(self) -> str | None:
        """Entity ID for wikibase-entityid type (e.g. 'Q5')."""
        if self.value_type == "wikibase-entityid" and isinstance(self.raw_value, dict):
            return self.raw_value.get("id")
        return None

    @property
    def time_value(self) -> str | None:
        """Time string for time type (e.g. '+1952-03-11T00:00:00Z')."""
        if self.value_type == "time" and isinstance(self.raw_value, dict):
            return self.raw_value.get("time")
        return None

    @property
    def amount(self) -> str | None:
        """Amount string for quantity type."""
        if self.value_type == "quantity" and isinstance(self.raw_value, dict):
            return self.raw_value.get("amount")
        return None

    @property
    def text(self) -> str | None:
        """Text value for string or monolingualtext type."""
        if self.value_type == "string":
            if isinstance(self.raw_value, str):
                return self.raw_value
            return str(self.raw_value.get("value", ""))
        if self.value_type == "monolingualtext" and isinstance(self.raw_value, dict):
            return self.raw_value.get("text")
        return None


class Claim(BaseModel):
    """A single claim (statement) on an entity."""

    property_id: str
    value: ClaimValue | None = None
    rank: str = "normal"
    qualifiers: dict[str, list[ClaimValue]] = Field(default_factory=dict)


class Entity(BaseModel):
    """A Wikidata entity (item or property)."""

    qid: str
    entity_type: str = "item"
    label: str | None = None
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    claims: dict[str, list[Claim]] = Field(default_factory=dict)
    datatype: str | None = None

    def __getitem__(self, property_id: str) -> list[Claim]:
        """Allow entity['P569'] access."""
        if property_id in self.claims:
            return self.claims[property_id]
        raise KeyError(f"No claims for property {property_id}")


class SearchResult(BaseModel):
    """A result from wbsearchentities."""

    qid: str
    label: str | None = None
    description: str | None = None


def _parse_snak(snak: dict[str, Any]) -> ClaimValue | None:
    """Parse a single Wikidata snak into a ClaimValue."""
    snaktype = snak.get("snaktype", "value")
    if snaktype != "value":
        return None
    datavalue = snak.get("datavalue")
    if not datavalue:
        return None
    return ClaimValue(
        value_type=datavalue.get("type", "unknown"),
        raw_value=datavalue.get("value", {}),
    )


def _parse_qualifiers(raw_qualifiers: dict[str, list[dict]]) -> dict[str, list[ClaimValue]]:
    """Parse qualifier snaks grouped by property ID."""
    result: dict[str, list[ClaimValue]] = {}
    for prop_id, snaks in raw_qualifiers.items():
        values = []
        for snak in snaks:
            parsed = _parse_snak(snak)
            if parsed is not None:
                values.append(parsed)
        if values:
            result[prop_id] = values
    return result


def parse_entity(raw: dict[str, Any], lang: str = "en") -> Entity:
    """Parse raw Wikidata API/dump JSON into an Entity model.

    This is the single parsing function used by both the API client
    and the dump loader.
    """
    qid = raw.get("id", "")
    entity_type = raw.get("type", "item")

    # Label
    labels = raw.get("labels", {})
    label = None
    if lang in labels:
        label = labels[lang].get("value") if isinstance(labels[lang], dict) else None

    # Description
    descriptions = raw.get("descriptions", {})
    description = None
    if lang in descriptions:
        description = (
            descriptions[lang].get("value")
            if isinstance(descriptions[lang], dict)
            else None
        )

    # Aliases
    aliases_data = raw.get("aliases", {})
    aliases: list[str] = []
    if lang in aliases_data:
        lang_aliases = aliases_data[lang]
        if isinstance(lang_aliases, list):
            aliases = [a.get("value", "") for a in lang_aliases if isinstance(a, dict)]

    # Claims
    claims: dict[str, list[Claim]] = {}
    raw_claims = raw.get("claims", {})
    for prop_id, statements in raw_claims.items():
        parsed_claims = []
        for stmt in statements:
            mainsnak = stmt.get("mainsnak", {})
            value = _parse_snak(mainsnak)
            qualifiers = _parse_qualifiers(stmt.get("qualifiers", {}))
            parsed_claims.append(
                Claim(
                    property_id=prop_id,
                    value=value,
                    rank=stmt.get("rank", "normal"),
                    qualifiers=qualifiers,
                )
            )
        if parsed_claims:
            claims[prop_id] = parsed_claims

    # Datatype (for property entities)
    datatype = raw.get("datatype")

    return Entity(
        qid=qid,
        entity_type=entity_type,
        label=label,
        description=description,
        aliases=aliases,
        claims=claims,
        datatype=datatype,
    )
