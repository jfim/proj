# src/proj/cli.py
"""Command-line entry point for proj."""

from __future__ import annotations

from pathlib import Path

import click

from proj import __version__
from proj.engine import build_from_manifest_path, build_query
from proj.output import format_rows
from proj.paths import cache_dir as default_cache_dir
from proj.paths import config_path as default_config_path


@click.group()
@click.version_option(__version__, prog_name="proj")
@click.option(
    "--manifest",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to projects.yaml (defaults to ~/.config/proj/projects.yaml).",
)
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Cache directory (defaults to ~/.cache/proj).",
)
@click.pass_context
def main(ctx: click.Context, manifest: Path | None, cache_dir: Path | None) -> None:
    """Manage a flat directory of heterogeneous projects."""
    ctx.ensure_object(dict)
    ctx.obj["manifest"] = manifest or default_config_path()
    ctx.obj["cache_dir"] = cache_dir or default_cache_dir()


@main.command()
@click.argument("input")
@click.option("--where", help="SQL WHERE clause.")
@click.option("--order-by", help="SQL ORDER BY clause.")
@click.option("--group-by", help="SQL GROUP BY clause.")
@click.option("--limit", type=int, help="SQL LIMIT.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
)
@click.pass_context
def query(
    ctx: click.Context,
    input: str,
    where: str | None,
    order_by: str | None,
    group_by: str | None,
    limit: int | None,
    output_format: str,
) -> None:
    """Run a SQL query against the projects table."""
    manifest_path: Path = ctx.obj["manifest"]
    cdir: Path = ctx.obj["cache_dir"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")
    engine = build_from_manifest_path(manifest_path, cache_path=cdir / "cache.db")
    sql = build_query(input, where=where, order_by=order_by, group_by=group_by, limit=limit)
    try:
        cursor = engine.execute(sql)
    except Exception as e:
        raise click.ClickException(f"query failed: {e}") from e
    headers = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    format_rows(rows, headers, fmt=output_format)


if __name__ == "__main__":
    main()
