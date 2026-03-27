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

    def test_load_instance_of(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        """--instance-of filters by P31 claim values."""
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw, sample_entity_raw_q1])
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path, languages=["en"])
        # Q42 has P31=Q5 (human), Q1 has P31=Q36906466
        loader.load(dump_path, instance_of={"Q5"}, batch_size=10)

        db = LocalDB(db_path)
        assert db.get("Q42") is not None  # P31=Q5, matches
        assert db.get("Q1") is None  # P31=Q36906466, doesn't match
        db.close()

    def test_load_has_property(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        """--has-property filters by presence of a property."""
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw, sample_entity_raw_q1])
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path, languages=["en"])
        # Q42 has P569 (birth date), Q1 does not
        loader.load(dump_path, has_property={"P569"}, batch_size=10)

        db = LocalDB(db_path)
        assert db.get("Q42") is not None  # has P569
        assert db.get("Q1") is None  # no P569
        db.close()

    def test_load_combined_filters_or(self, tmp_path, sample_entity_raw, sample_entity_raw_q1):
        """Multiple filters combine with OR — match any to pass."""
        dump_path = tmp_path / "dump.json.gz"
        _make_dump(dump_path, [sample_entity_raw, sample_entity_raw_q1])
        db_path = tmp_path / "test.duckdb"

        loader = DumpLoader(db_path=db_path, languages=["en"])
        # Q42 matches instance_of=Q5, Q1 matches filter_qids
        loader.load(dump_path, filter_qids={"Q1"}, instance_of={"Q5"}, batch_size=10)

        db = LocalDB(db_path)
        assert db.get("Q42") is not None  # via instance_of
        assert db.get("Q1") is not None  # via filter_qids
        db.close()
