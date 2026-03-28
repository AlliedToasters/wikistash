"""DumpLoader — stream-process Wikidata JSON dumps into LocalDB."""

from __future__ import annotations

import gzip
import hashlib
import os
from datetime import date, timezone, datetime
from pathlib import Path
from typing import Iterator

import orjson
import structlog

from wikistash.local_db import LocalDB

log = structlog.get_logger()


class DumpLoader:
    def __init__(
        self,
        db_path: Path | str,
        languages: list[str] | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._languages = languages or ["en"]

    def load(
        self,
        dump_path: Path | str,
        filter_qids: set[str] | None = None,
        instance_of: set[str] | None = None,
        has_property: set[str] | None = None,
        batch_size: int = 10_000,
        progress_interval: int = 100_000,
        fast: bool = False,
        hash_dump: bool = False,
    ) -> None:
        """Load a Wikidata JSON dump into the local DB.

        Args:
            dump_path: Path to .json.gz or .json dump file.
            filter_qids: If set, only load these QIDs.
            instance_of: If set, only load entities whose P31 (instance of)
                includes at least one of these QIDs (e.g. {"Q5", "Q198"}).
            has_property: If set, only load entities that have at least one
                claim for any of these properties (e.g. {"P31", "P569"}).
            batch_size: Rows per batch insert.
            progress_interval: Log progress every N entities scanned.
            fast: If True, skip raw entity JSON storage and use bulk inserts.
                Much faster but stash.get() won't work — SPARQL queries only.
            hash_dump: If True, SHA-256 the dump file for a strong content-based
                snapshot hash. Adds ~30s for a 142GB file. Default False uses
                file size + mtime for a fast, weaker fingerprint.
        """
        has_filter = (filter_qids is not None or instance_of is not None
                      or has_property is not None)
        db = LocalDB(self._db_path)
        if fast:
            log.info("dropping_indices_for_bulk_load")
            db.drop_indices()
        try:
            batch: list[dict] = []
            label_batch: list[dict] = []
            loaded = 0
            labels_saved = 0
            scanned = 0

            for raw in self._iter_entities(dump_path):
                scanned += 1
                if scanned % progress_interval == 0:
                    log.info(
                        "dump_progress",
                        scanned=scanned,
                        loaded=loaded,
                        labels_saved=labels_saved,
                    )

                if not self._filter_entity(raw, filter_qids, instance_of, has_property):
                    # Even non-matching entities get their labels saved
                    if has_filter and fast:
                        label_batch.append(raw)
                        if len(label_batch) >= batch_size:
                            db.put_labels_only(label_batch, languages=self._languages)
                            labels_saved += len(label_batch)
                            label_batch = []
                    continue

                batch.append(raw)
                if len(batch) >= batch_size:
                    if fast:
                        db.put_batch_fast(batch, languages=self._languages)
                    else:
                        db.put_batch(
                            batch,
                            dump_date=date.today(),
                            source="dump",
                            languages=self._languages,
                        )
                    loaded += len(batch)
                    batch = []

            # Flush remaining
            if batch:
                if fast:
                    db.put_batch_fast(batch, languages=self._languages)
                else:
                    db.put_batch(
                        batch,
                        dump_date=date.today(),
                        source="dump",
                        languages=self._languages,
                    )
                loaded += len(batch)

            if label_batch:
                db.put_labels_only(label_batch, languages=self._languages)
                labels_saved += len(label_batch)

            if fast:
                log.info("creating_indices")
                db.create_indices()
                log.info("indices_created")

            log.info("dump_complete", scanned=scanned, loaded=loaded,
                     labels_saved=labels_saved)

            # Store snapshot metadata for reproducibility
            dump_path = Path(dump_path)
            dump_fingerprint = self._dump_fingerprint(dump_path, full_hash=hash_dump)
            snapshot_hash = self._compute_snapshot_hash(
                dump_fingerprint=dump_fingerprint,
                filter_qids=filter_qids,
                instance_of=instance_of,
                has_property=has_property,
            )
            db.set_metadata("snapshot_hash", snapshot_hash)
            db.set_metadata("dump_path", str(dump_path.resolve()))
            db.set_metadata("dump_fingerprint", dump_fingerprint)
            db.set_metadata("load_date", date.today().isoformat())
            db.set_metadata("entity_count", str(loaded))
            db.set_metadata("hash_dump", "true" if hash_dump else "false")
            filters: dict = {}
            if filter_qids is not None:
                filters["filter_qids"] = sorted(filter_qids)
            if instance_of is not None:
                filters["instance_of"] = sorted(instance_of)
            if has_property is not None:
                filters["has_property"] = sorted(has_property)
            db.set_metadata("filters", orjson.dumps(filters).decode())
            log.info("snapshot_hash_stored", snapshot_hash=snapshot_hash)
        finally:
            db.close()

    def _dump_fingerprint(self, dump_path: Path, full_hash: bool) -> str:
        """Return a fingerprint string for the dump file.

        With full_hash=True: SHA-256 of the file contents (strong, slow).
        With full_hash=False: SHA-256 of "path|size|mtime" (fast, weaker).
        """
        if full_hash:
            log.info("hashing_dump_file", path=str(dump_path))
            h = hashlib.sha256()
            with open(dump_path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
        else:
            stat = os.stat(dump_path)
            parts = f"{dump_path.name}|{stat.st_size}|{stat.st_mtime}"
            return hashlib.sha256(parts.encode()).hexdigest()

    def _compute_snapshot_hash(
        self,
        dump_fingerprint: str,
        filter_qids: set[str] | None,
        instance_of: set[str] | None,
        has_property: set[str] | None,
    ) -> str:
        """Stable hash of dump fingerprint + sorted filters."""
        h = hashlib.sha256()
        h.update(dump_fingerprint.encode())
        h.update(b"|filter_qids=")
        h.update(",".join(sorted(filter_qids or [])).encode())
        h.update(b"|instance_of=")
        h.update(",".join(sorted(instance_of or [])).encode())
        h.update(b"|has_property=")
        h.update(",".join(sorted(has_property or [])).encode())
        return h.hexdigest()

    def _iter_entities(self, dump_path: Path | str) -> Iterator[dict]:
        """Stream entities from the dump, handling the array-wrapper format."""
        dump_path = Path(dump_path)
        if dump_path.suffix == ".gz" or str(dump_path).endswith(".json.gz"):
            opener = gzip.open(dump_path, "rb")
        else:
            opener = open(dump_path, "rb")

        with opener as f:
            for line in f:
                line = line.strip()
                if not line or line in (b"[", b"]"):
                    continue
                # Strip trailing comma
                if line.endswith(b","):
                    line = line[:-1]
                if not line:
                    continue
                try:
                    yield orjson.loads(line)
                except orjson.JSONDecodeError:
                    log.warning("skip_invalid_json", line_preview=line[:100])
                    continue

    def _filter_entity(
        self,
        raw: dict,
        filter_qids: set[str] | None,
        instance_of: set[str] | None = None,
        has_property: set[str] | None = None,
    ) -> bool:
        """Return True if this entity should be loaded.

        Filters are combined with OR — an entity passes if it matches
        any active filter. Property entities (P-items) always pass
        when instance_of or has_property is active, since they're
        needed for label resolution.
        """
        # No filters → load everything
        if filter_qids is None and instance_of is None and has_property is None:
            return True

        entity_id = raw.get("id", "")

        # Explicit QID list
        if filter_qids is not None and entity_id in filter_qids:
            return True

        # Always keep property entities when doing type/property filtering
        if (instance_of is not None or has_property is not None) and entity_id.startswith("P"):
            return True

        claims = raw.get("claims", {})

        # Instance-of filter: check P31 claim values
        if instance_of is not None:
            for stmt in claims.get("P31", []):
                try:
                    qid = stmt["mainsnak"]["datavalue"]["value"]["id"]
                    if qid in instance_of:
                        return True
                except (KeyError, TypeError):
                    continue

        # Has-property filter: check if any target property exists
        if has_property is not None:
            for prop in has_property:
                if prop in claims:
                    return True

        return False
