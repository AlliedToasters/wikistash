"""CLI entry point for wikistash."""

from __future__ import annotations

import json

import click

from wikistash.dump_loader import DumpLoader
from wikistash.stash import Stash


@click.group()
def cli() -> None:
    """wikistash — Wikidata at your fingertips."""


@cli.command()
@click.argument("dump_path", type=click.Path(exists=True))
@click.option("--db-path", default="./wikistash.duckdb", help="Path for the DuckDB database.")
@click.option("--entities", default=None, help="Comma-separated QIDs to filter (e.g. Q42,Q1,Q5).")
@click.option("--languages", default="en", help="Comma-separated language codes to keep.")
@click.option("--batch-size", default=10_000, type=int, help="Batch insert size.")
def load(dump_path: str, db_path: str, entities: str | None, languages: str, batch_size: int) -> None:
    """Load a Wikidata dump into the local database."""
    lang_list = [l.strip() for l in languages.split(",")]
    filter_qids = None
    if entities:
        filter_qids = {q.strip() for q in entities.split(",")}

    loader = DumpLoader(db_path=db_path, languages=lang_list)
    loader.load(dump_path, filter_qids=filter_qids, batch_size=batch_size)
    click.echo("Done.")


@cli.command()
@click.argument("qid")
@click.option("--db-path", default="./wikistash.duckdb", help="Path to the DuckDB database.")
def get(qid: str, db_path: str) -> None:
    """Look up an entity by QID and print as JSON."""
    with Stash(local_db_path=db_path) as stash:
        entity = stash.get(qid)
        click.echo(json.dumps(entity.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    cli()
