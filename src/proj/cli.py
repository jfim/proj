"""Command-line entry point for proj."""

from __future__ import annotations

import click

from proj import __version__


@click.group()
@click.version_option(__version__, prog_name="proj")
def main() -> None:
    """Manage a flat directory of heterogeneous projects."""


@main.command("list")
@click.option("--tag", "tags", help="Comma-separated tags (ANDed).")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
)
def list_cmd(tags: str | None, output_format: str) -> None:
    """List projects, optionally filtered by tag."""
    raise NotImplementedError


@main.command()
@click.argument("command")
@click.option("--tag", "tags", help="Filter projects by tag.")
@click.option("--filter", "filter_expr", help="Filter by auto-detected property.")
@click.option("--only-matches", is_flag=True)
@click.option("--only-failures", is_flag=True)
@click.option("--summary", is_flag=True)
@click.option("--parallel", is_flag=True)
def run(
    command: str,
    tags: str | None,
    filter_expr: str | None,
    only_matches: bool,
    only_failures: bool,
    summary: bool,
    parallel: bool,
) -> None:
    """Run a shell command in each matching project directory."""
    raise NotImplementedError


@main.command()
@click.option("--tag", "tags", help="Filter projects by tag.")
@click.option("--filter", "filter_expr", help="Filter by auto-detected property.")
def status(tags: str | None, filter_expr: str | None) -> None:
    """Pretty-printed git status across matching projects."""
    raise NotImplementedError


@main.command()
@click.option("--tag", "tags", help="Limit which projects are audited.")
@click.option("--check", "check_name", help="Run a single named check.")
def audit(tags: str | None, check_name: str | None) -> None:
    """Run all defined checks and display a dashboard."""
    raise NotImplementedError


@main.command()
@click.option("--stale", help="Only projects not touched within duration (e.g. 6mo).")
@click.option("--min-size", help="Only projects above size threshold (e.g. 50mb).")
@click.option("--reclaimable", is_flag=True)
def dust(stale: str | None, min_size: str | None, reclaimable: bool) -> None:
    """Disk usage report, sorted by size descending."""
    raise NotImplementedError


@main.command()
@click.option("--tag", "tags", help="Filter projects by tag.")
@click.option("--dry-run", is_flag=True)
def clean(tags: str | None, dry_run: bool) -> None:
    """Run each project's clean target to free build artifacts."""
    raise NotImplementedError


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--restore", "restore_name", help="Decompress and restore an archived project.")
def archive(dry_run: bool, restore_name: str | None) -> None:
    """Move stale/unwanted projects to an archive directory."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
