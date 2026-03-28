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
@click.option("--instance-of", "instance_of", default=None,
              help="Comma-separated P31 type QIDs to keep (e.g. Q5,Q198,Q16521).")
@click.option("--has-property", "has_property", default=None,
              help="Comma-separated property IDs — keep entities that have any of these (e.g. P31,P569).")
@click.option("--languages", default="en", help="Comma-separated language codes to keep.")
@click.option("--batch-size", default=10_000, type=int, help="Batch insert size.")
@click.option("--fast", is_flag=True, default=False,
              help="Skip raw JSON storage, use bulk inserts. Much faster but stash.get() won't work.")
@click.option("--hash-dump", "hash_dump", is_flag=True, default=False,
              help="SHA-256 the full dump file for a strong content-based snapshot hash (~30s extra).")
def load(dump_path: str, db_path: str, entities: str | None, instance_of: str | None,
         has_property: str | None, languages: str, batch_size: int, fast: bool,
         hash_dump: bool) -> None:
    """Load a Wikidata dump into the local database."""
    lang_list = [l.strip() for l in languages.split(",")]
    filter_qids = {q.strip() for q in entities.split(",")} if entities else None
    iof_set = {q.strip() for q in instance_of.split(",")} if instance_of else None
    hp_set = {p.strip() for p in has_property.split(",")} if has_property else None

    loader = DumpLoader(db_path=db_path, languages=lang_list)
    loader.load(dump_path, filter_qids=filter_qids, instance_of=iof_set,
                has_property=hp_set, batch_size=batch_size, fast=fast, hash_dump=hash_dump)
    click.echo("Done.")


@cli.command()
@click.option("--db-path", default="./wikistash.duckdb", help="Path to the DuckDB database.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output full metadata as JSON.")
def snapshot(db_path: str, as_json: bool) -> None:
    """Print the snapshot hash (and optionally full load metadata) for the local database."""
    with Stash(local_db_path=db_path) as stash:
        if as_json:
            info = stash.snapshot_info()
            if not info:
                raise click.ClickException("No snapshot metadata found. Was this DB loaded with a recent version?")
            click.echo(json.dumps(info, indent=2))
        else:
            h = stash.snapshot_hash()
            if h is None:
                raise click.ClickException("No snapshot hash found. Was this DB loaded with a recent version?")
            click.echo(h)


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
