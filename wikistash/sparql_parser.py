"""SPARQL parser — translates SPARQL text into an intermediate representation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wikistash.exceptions import SparqlParseError


@dataclass
class TriplePattern:
    subject: str
    predicate: str
    object: str
    is_optional: bool = False


@dataclass
class Filter:
    variable: str
    operator: str
    value: int | float | str


@dataclass
class ValuesClause:
    variable: str
    values: list[str]


@dataclass
class LabelService:
    language: str = "en"


@dataclass
class SparqlQuery:
    select_vars: list[str] = field(default_factory=list)
    triple_patterns: list[TriplePattern] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    values_clauses: list[ValuesClause] = field(default_factory=list)
    label_service: LabelService | None = None
    limit: int | None = None
    offset: int | None = None
    distinct: bool = False


def parse_sparql(query: str) -> SparqlQuery:
    """Parse a SPARQL SELECT query into an intermediate representation."""
    result = SparqlQuery()

    # Strip comments
    lines = []
    for line in query.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)

    # Extract LIMIT and OFFSET from tail
    limit_match = re.search(r"\bLIMIT\s+(\d+)", text, re.IGNORECASE)
    if limit_match:
        result.limit = int(limit_match.group(1))

    offset_match = re.search(r"\bOFFSET\s+(\d+)", text, re.IGNORECASE)
    if offset_match:
        result.offset = int(offset_match.group(1))

    # Parse SELECT (DISTINCT)?
    select_match = re.search(
        r"\bSELECT\s+(DISTINCT\s+)?(.*?)\s*WHERE\s*\{",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not select_match:
        raise SparqlParseError("Could not find SELECT ... WHERE { in query")

    if select_match.group(1):
        result.distinct = True

    vars_text = select_match.group(2).strip()
    result.select_vars = [v.lstrip("?") for v in re.findall(r"\?\w+", vars_text)]

    # Extract WHERE body
    where_body = _extract_where_body(text)

    # Extract VALUES clauses
    where_body = _parse_values(where_body, result)

    # Extract SERVICE wikibase:label
    where_body = _parse_label_service(where_body, result)

    # Extract OPTIONAL blocks
    where_body = _parse_optionals(where_body, result)

    # Extract FILTERs
    where_body = _parse_filters(where_body, result)

    # Skip schema: triples (not in our schema)
    where_body = re.sub(
        r"\?\w+\s+schema:\w+\s+[^\s.;]+\s*[.;]?\s*", "", where_body
    )

    # Parse remaining triple patterns
    _parse_triples(where_body, result, is_optional=False)

    return result


def _extract_where_body(text: str) -> str:
    """Extract the content between WHERE { and the matching }."""
    match = re.search(r"\bWHERE\s*\{", text, re.IGNORECASE)
    if not match:
        raise SparqlParseError("Could not find WHERE clause")

    start = match.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1

    if depth != 0:
        raise SparqlParseError("Unbalanced braces in WHERE clause")

    return text[start : i - 1]


def _parse_values(body: str, result: SparqlQuery) -> str:
    """Extract VALUES clauses and return body with them removed."""
    pattern = re.compile(
        r"\bVALUES\s+\?(\w+)\s*\{([^}]+)\}", re.IGNORECASE
    )
    for match in pattern.finditer(body):
        variable = match.group(1)
        values_text = match.group(2).strip()
        values = re.findall(r"wd:([QP]\d+)", values_text)
        values = [f"wd:{v}" for v in values]
        result.values_clauses.append(ValuesClause(variable=variable, values=values))
    return pattern.sub("", body)


def _parse_label_service(body: str, result: SparqlQuery) -> str:
    """Extract SERVICE wikibase:label and return body with it removed."""
    pattern = re.compile(
        r"\bSERVICE\s+wikibase:label\s*\{[^}]*\}", re.IGNORECASE
    )
    match = pattern.search(body)
    if match:
        lang_match = re.search(
            r'wikibase:language\s+"([^"]+)"', match.group(0)
        )
        lang = lang_match.group(1).split(",")[0].strip() if lang_match else "en"
        result.label_service = LabelService(language=lang)
    return pattern.sub("", body)


def _parse_optionals(body: str, result: SparqlQuery) -> str:
    """Extract OPTIONAL { ... } blocks and return body with them removed."""
    cleaned = body
    pattern = re.compile(r"\bOPTIONAL\s*\{", re.IGNORECASE)

    while True:
        match = pattern.search(cleaned)
        if not match:
            break

        start = match.end()
        depth = 1
        i = start
        while i < len(cleaned) and depth > 0:
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
            i += 1

        optional_body = cleaned[start : i - 1]

        # Skip schema: triples inside OPTIONAL
        optional_body = re.sub(
            r"\?\w+\s+schema:\w+\s+[^\s.;]+\s*[.;]?\s*", "", optional_body
        )

        _parse_triples(optional_body, result, is_optional=True)
        cleaned = cleaned[: match.start()] + cleaned[i:]

    return cleaned


def _parse_filters(body: str, result: SparqlQuery) -> str:
    """Extract FILTER expressions and return body with them removed."""
    pattern = re.compile(
        r"\bFILTER\s*\(\s*\?(\w+)\s*(>=|<=|>|<|=|!=)\s*(\d+(?:\.\d+)?)\s*\)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(body):
        variable = match.group(1)
        operator = match.group(2)
        value_str = match.group(3)
        value: int | float = float(value_str) if "." in value_str else int(value_str)
        result.filters.append(Filter(variable=variable, operator=operator, value=value))
    return pattern.sub("", body)


def _parse_triples(body: str, result: SparqlQuery, is_optional: bool) -> None:
    """Parse triple patterns from a block of text, handling semicolons."""
    # Normalize whitespace
    text = re.sub(r"\s+", " ", body.strip())
    if not text:
        return

    # Split on periods (statement terminators), keeping semicolons within
    statements = re.split(r"\.\s*", text)

    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue

        # Split on semicolons for shared-subject patterns
        parts = re.split(r"\s*;\s*", stmt)
        current_subject = None

        for part in parts:
            part = part.strip()
            if not part:
                continue

            tokens = part.split()
            if len(tokens) >= 3 and tokens[0].startswith("?"):
                # Full triple: ?subject predicate object
                current_subject = tokens[0].lstrip("?")
                predicate = tokens[1]
                obj = tokens[2]
            elif len(tokens) >= 2 and current_subject:
                # Semicolon continuation: predicate object
                predicate = tokens[0]
                obj = tokens[1]
            else:
                continue

            # Only handle predicates we understand
            if not (
                predicate.startswith("wdt:")
                or predicate == "wikibase:sitelinks"
            ):
                continue

            obj_clean = obj.rstrip(".,;")
            result.triple_patterns.append(
                TriplePattern(
                    subject=current_subject,
                    predicate=predicate,
                    object=obj_clean.lstrip("?") if obj_clean.startswith("?") else obj_clean,
                    is_optional=is_optional,
                )
            )
