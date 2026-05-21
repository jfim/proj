"""Format query result rows for output."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import IO, Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from proj.grouped import GroupedColumnConfig, Line, format_grouped_cell
from proj.marks import Mark


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


def format_grouped_rows(
    rows: Sequence[Sequence[Any]],
    headers: Sequence[str],
    user_headers: Sequence[str],
    grouped_configs: Sequence[GroupedColumnConfig],
    marks: dict[str, Mark],
    fmt: str = "table",
    file: IO[str] | None = None,
) -> None:
    """Render rows that include auto-projected grouped-column inputs.

    `headers` is the full set of columns returned by SQLite (user_headers +
    auto-projected pairs). `user_headers` is what the user listed in `columns:`.
    The output shows `user_headers + [g.name for g in grouped_configs]` —
    auto-projections are hidden, replaced by synthesized multi-line cells.
    """
    file = file if file is not None else sys.stdout
    out_headers = list(user_headers) + [g.name for g in grouped_configs]
    rendered = [_render_row(row, headers, user_headers, grouped_configs, marks) for row in rows]
    if fmt == "plain":
        _format_grouped_plain(rendered, file)
    elif fmt == "json":
        _format_grouped_json(rendered, out_headers, file)
    elif fmt == "table":
        _format_grouped_table(rendered, out_headers, grouped_configs, file)
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


# ---------- grouped-row rendering ----------


def _render_row(
    row: Sequence[Any],
    headers: Sequence[str],
    user_headers: Sequence[str],
    grouped_configs: Sequence[GroupedColumnConfig],
    marks: dict[str, Mark],
) -> dict[str, Any]:
    """Returns: {user_col_name: scalar, grouped_name: list[Line]}."""
    row_dict = dict(zip(headers, row, strict=False))
    rendered: dict[str, Any] = {h: row_dict.get(h) for h in user_headers}
    for cfg in grouped_configs:
        rendered[cfg.name] = format_grouped_cell(cfg, row_dict, marks)
    return rendered


def _format_grouped_plain(rendered: Sequence[dict[str, Any]], file: IO[str]) -> None:
    """Plain: each grouped cell becomes its count summary, tab-separated."""
    for row in rendered:
        fields = []
        for v in row.values():
            if isinstance(v, list):  # list[Line]
                fields.append(v[0].text if v else "")
            else:
                fields.append("" if v is None else str(v))
        file.write("\t".join(fields) + "\n")
        for v in row.values():
            if isinstance(v, list) and len(v) > 1:
                for line in v[1:]:
                    file.write(f"  {line.text}\n")


def _format_grouped_json(
    rendered: Sequence[dict[str, Any]],
    headers: Sequence[str],
    file: IO[str],
) -> None:
    out = []
    for row in rendered:
        item = {}
        for h, v in row.items():
            if isinstance(v, list):  # list[Line]
                item[h] = {
                    "summary": v[0].text if v else "",
                    "lines": [
                        {
                            "text": line.text,
                            "mark": {
                                "prefix": line.mark.prefix,
                                "suffix": line.mark.suffix,
                                "color": line.mark.color,
                            }
                            if line.mark
                            else None,
                        }
                        for line in v[1:]
                    ],
                }
            else:
                item[h] = v
        out.append(item)
    del headers  # included in row dicts directly
    json.dump(out, file, indent=2, default=str)
    file.write("\n")


def _line_to_text(line: Line) -> Text:
    mark = line.mark
    if mark is None:
        return Text(line.text)
    rendered = f"{mark.prefix}{line.text}{mark.suffix}"
    style = mark.color if mark.color else ""
    return Text(rendered, style=style) if style else Text(rendered)


def _grouped_cell_to_text(lines: list[Line]) -> Text:
    if not lines:
        return Text("")
    out = _line_to_text(lines[0])
    for line in lines[1:]:
        out.append("\n")
        out.append_text(_line_to_text(line))
    return out


def _format_grouped_table(
    rendered: Sequence[dict[str, Any]],
    headers: Sequence[str],
    grouped_configs: Sequence[GroupedColumnConfig],
    file: IO[str],
) -> None:
    grouped_names = {g.name for g in grouped_configs}
    console = Console(file=file, force_terminal=False)
    table = Table(show_header=True)
    for h in headers:
        table.add_column(h)
    for row in rendered:
        cells = []
        for h in headers:
            v = row.get(h)
            if h in grouped_names and isinstance(v, list):
                cells.append(_grouped_cell_to_text(v))
            else:
                cells.append("" if v is None else str(v))
        table.add_row(*cells)
    console.print(table)
