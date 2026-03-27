"""DumpLoader — stream-process Wikidata JSON dumps into LocalDB."""

from __future__ import annotations

import gzip
from datetime import date
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
        batch_size: int = 10_000,
        progress_interval: int = 100_000,
    ) -> None:
        """Load a Wikidata JSON dump into the local DB.

        Args:
            dump_path: Path to .json.gz or .json dump file.
            filter_qids: If set, only load these QIDs.
            batch_size: Rows per batch insert.
            progress_interval: Log progress every N entities scanned.
        """
        db = LocalDB(self._db_path)
        try:
            batch: list[dict] = []
            loaded = 0
            scanned = 0

            for raw in self._iter_entities(dump_path):
                scanned += 1
                if scanned % progress_interval == 0:
                    log.info(
                        "dump_progress",
                        scanned=scanned,
                        loaded=loaded,
                    )

                if not self._filter_entity(raw, filter_qids):
                    continue

                batch.append(raw)
                if len(batch) >= batch_size:
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
                db.put_batch(
                    batch,
                    dump_date=date.today(),
                    source="dump",
                    languages=self._languages,
                )
                loaded += len(batch)

            log.info("dump_complete", scanned=scanned, loaded=loaded)
        finally:
            db.close()

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
        self, raw: dict, filter_qids: set[str] | None
    ) -> bool:
        """Return True if this entity should be loaded."""
        if filter_qids is None:
            return True
        return raw.get("id", "") in filter_qids
