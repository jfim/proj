"""Format query result rows for output."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import IO, Any

from rich.console import Console
from rich.table import Table


def format_rows(
    rows: Sequence[Sequence[Any]],
    headers: Sequence[str],
    fmt: str = "table",
    file: IO[str] | None = None,
) -> None:
    file = file if file is not None else sys.stdout
    if fmt == "plain":
        _format_plain(rows, file)
    elif fmt == "json":
        _format_json(rows, headers, file)
    elif fmt == "table":
        _format_table(rows, headers, file)
    else:
        raise ValueError(f"unknown format: {fmt!r}")


def _format_plain(rows: Sequence[Sequence[Any]], file: IO[str]) -> None:
    for row in rows:
        file.write("\t".join("" if v is None else str(v) for v in row) + "\n")


def _format_json(
    rows: Sequence[Sequence[Any]],
    headers: Sequence[str],
    file: IO[str],
) -> None:
    data = [dict(zip(headers, row, strict=False)) for row in rows]
    json.dump(data, file, indent=2, default=str)
    file.write("\n")


def _format_table(
    rows: Sequence[Sequence[Any]],
    headers: Sequence[str],
    file: IO[str],
) -> None:
    console = Console(file=file, force_terminal=False)
    table = Table(show_header=True)
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*["" if v is None else str(v) for v in row])
    console.print(table)
