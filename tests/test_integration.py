"""End-to-end integration test with real DuckDB and mocked API."""

import gzip
import json

import httpx
import pytest
import respx

from wikistash.dump_loader import DumpLoader
from wikistash.stash import Stash


def _make_dump(path, entities):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("[\n")
        for i, entity in enumerate(entities):
            line = json.dumps(entity)
            if i < len(entities) - 1:
                line += ","
            f.write(line + "\n")
        f.write("]\n")


class TestIntegration:
    def test_full_flow(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        db_path = tmp_path / "wikistash.duckdb"
        cache_path = tmp_path / "cache.sqlite"

        # 1. Load a dump with Q42 only
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw])
        loader = DumpLoader(db_path=db_path, languages=["en"])
        loader.load(dump_path)

        # 2. Create stash with local DB + mocked API
        with respx.mock:
            # Mock API to return Q1 when asked
            api_response = {"entities": {"Q1": sample_entity_raw_q1}}
            respx.get("https://www.wikidata.org/w/api.php").mock(
                return_value=httpx.Response(200, json=api_response)
            )

            with Stash(
                local_db_path=db_path,
                cache_db_path=cache_path,
                enable_live_fallback=True,
                max_qps=100.0,
            ) as stash:
                # 3. Query Q42 — should be a local hit (no API call)
                q42 = stash.get("Q42")
                assert q42.qid == "Q42"
                assert q42.label == "Douglas Adams"
                assert q42["P31"][0].value.entity_id == "Q5"

                # 4. Query Q1 — should fall back to API
                q1 = stash.get("Q1")
                assert q1.qid == "Q1"
                assert q1.label == "Universe"

        # 5. Query Q1 again with fresh stash — should be cached (or backfilled)
        with Stash(
            local_db_path=db_path,
            cache_db_path=cache_path,
            enable_live_fallback=False,  # no API — must come from local/cache
        ) as stash:
            q1_again = stash.get("Q1")
            assert q1_again.qid == "Q1"
            assert q1_again.label == "Universe"

    def test_batch_flow(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        db_path = tmp_path / "wikistash.duckdb"
        cache_path = tmp_path / "cache.sqlite"

        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw])
        loader = DumpLoader(db_path=db_path, languages=["en"])
        loader.load(dump_path)

        with respx.mock:
            api_response = {"entities": {"Q1": sample_entity_raw_q1}}
            respx.get("https://www.wikidata.org/w/api.php").mock(
                return_value=httpx.Response(200, json=api_response)
            )

            with Stash(
                local_db_path=db_path,
                cache_db_path=cache_path,
                enable_live_fallback=True,
                max_qps=100.0,
            ) as stash:
                # Batch: Q42 from local, Q1 from API
                result = stash.get(["Q42", "Q1"])
                assert "Q42" in result
                assert "Q1" in result
                assert result["Q42"].label == "Douglas Adams"
                assert result["Q1"].label == "Universe"

    def test_duckdb_escape_hatch(self, tmp_path, sample_entity_raw):
        db_path = tmp_path / "wikistash.duckdb"
        cache_path = tmp_path / "cache.sqlite"

        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw])
        loader = DumpLoader(db_path=db_path, languages=["en"])
        loader.load(dump_path)

        with Stash(
            local_db_path=db_path,
            cache_db_path=cache_path,
            enable_live_fallback=False,
        ) as stash:
            conn = stash.duckdb()
            rows = conn.execute(
                "SELECT value FROM labels WHERE qid = 'Q42' AND lang = 'en'"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "Douglas Adams"
