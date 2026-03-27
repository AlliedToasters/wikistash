"""Tests for dump_loader.py — streaming dump ingestion."""

import gzip
import json

import pytest

from wikistash.dump_loader import DumpLoader
from wikistash.local_db import LocalDB


def _make_dump(path, entities):
    """Create a gzipped Wikidata-format dump file."""
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("[\n")
        for i, entity in enumerate(entities):
            line = json.dumps(entity)
            if i < len(entities) - 1:
                line += ","
            f.write(line + "\n")
        f.write("]\n")


class TestDumpLoader:
    def test_load_basic(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw, sample_entity_raw_q1])
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path, languages=["en"])
        loader.load(dump_path, batch_size=10)

        db = LocalDB(db_path)
        assert db.get("Q42") is not None
        assert db.get("Q42").label == "Douglas Adams"
        assert db.get("Q1") is not None
        assert db.get("Q1").label == "Universe"
        db.close()

    def test_load_with_filter(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw, sample_entity_raw_q1])
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path, languages=["en"])
        loader.load(dump_path, filter_qids={"Q42"}, batch_size=10)

        db = LocalDB(db_path)
        assert db.get("Q42") is not None
        assert db.get("Q1") is None  # filtered out
        db.close()

    def test_load_plain_json(self, tmp_path, sample_entity_raw):
        """Test loading a plain (non-gzipped) JSON dump."""
        dump_path = tmp_path / "dump.json"
        with open(dump_path, "w") as f:
            f.write("[\n")
            f.write(json.dumps(sample_entity_raw) + "\n")
            f.write("]\n")
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path, languages=["en"])
        loader.load(dump_path)

        db = LocalDB(db_path)
        assert db.get("Q42") is not None
        db.close()

    def test_load_empty_dump(self, tmp_path):
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [])
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path)
        loader.load(dump_path)

        db = LocalDB(db_path)
        assert db.get("Q42") is None
        db.close()
