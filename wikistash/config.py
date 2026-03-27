"""Configuration for wikistash via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class WikiStashConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WIKISTASH_")

    # Local DB
    local_db_path: Path = Path("./wikistash.duckdb")

    # Entity cache
    cache_db_path: Path = Path("./wikistash_entity_cache.sqlite")
    cache_ttl_seconds: int = 7 * 24 * 3600  # 7 days
    cache_max_entries: int = 1_000_000

    # Live API
    wikidata_api_url: str = "https://www.wikidata.org/w/api.php"
    max_qps: float = 5.0
    request_timeout: float = 30.0
    max_retries: int = 3
    user_agent: str = "WikiStash/0.1 (https://github.com/wikistash/wikistash)"

    # Resolver
    enable_backfill: bool = True
    enable_live_fallback: bool = True

    # Language
    default_language: str = "en"
    dump_languages: list[str] = ["en"]
