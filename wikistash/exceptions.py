"""Custom exception hierarchy for wikistash."""


class WikiStashError(Exception):
    """Base exception for all wikistash errors."""


class EntityNotFoundError(WikiStashError):
    """Raised when an entity cannot be found in any tier."""

    def __init__(self, qid: str) -> None:
        self.qid = qid
        super().__init__(f"Entity not found: {qid}")


class APIError(WikiStashError):
    """Raised when the Wikidata API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"API error {status_code}: {message}")


class RateLimitError(APIError):
    """Raised when rate-limited by the API (429)."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429, f"Rate limited (retry after {retry_after}s)")


class ConfigError(WikiStashError):
    """Raised for invalid configuration."""


class DumpLoadError(WikiStashError):
    """Raised during dump loading failures."""


class SparqlParseError(WikiStashError):
    """Raised when a SPARQL query cannot be parsed."""
