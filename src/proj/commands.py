"""Command definitions parsed from defaults.yaml + user manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from proj.grouped import GroupedColumnConfig, parse_grouped_columns

HARDCODED_PRIMITIVES = frozenset({"query", "run", "adopt", "forget", "new", "defaults", "init"})


@dataclass(frozen=True)
class QueryCommand:
    name: str
    columns: list[str]
    where: str | None = None
    order_by: str | None = None
    limit: int | None = None
    grouped_columns: list[GroupedColumnConfig] = field(default_factory=list)


@dataclass(frozen=True)
class RunCommand:
    name: str
    cmds: list[str]
    where: str | None = None


Command = QueryCommand | RunCommand


def parse_commands(raw: dict[str, Any] | None) -> dict[str, Command]:
    """Parse a `commands:` mapping into typed Command objects."""
    if not raw:
        return {}
    out: dict[str, Command] = {}
    for name, body in raw.items():
        if name in HARDCODED_PRIMITIVES:
            raise ValueError(f"command {name!r} is a hardcoded primitive and cannot be redefined")
        if not isinstance(body, dict) or "type" not in body:
            raise ValueError(f"command {name!r}: missing 'type'")
        t = body["type"]
        if t == "query":
            cols = body.get("columns")
            if not isinstance(cols, list) or not cols:
                raise ValueError(f"command {name!r}: query needs non-empty 'columns'")
            out[name] = QueryCommand(
                name=name,
                columns=list(cols),
                where=body.get("where"),
                order_by=body.get("order_by"),
                limit=body.get("limit"),
                grouped_columns=parse_grouped_columns(body.get("grouped_columns")),
            )
        elif t == "run":
            cmd = body.get("cmd")
            if cmd is None:
                raise ValueError(f"command {name!r}: run needs 'cmd'")
            cmds = [cmd] if isinstance(cmd, str) else list(cmd)
            if not cmds:
                raise ValueError(f"command {name!r}: 'cmd' must not be empty")
            out[name] = RunCommand(name=name, cmds=cmds, where=body.get("where"))
        else:
            raise ValueError(f"command {name!r}: unknown type {t!r}")
    return out


def merge_commands(
    defaults: dict[str, Command],
    user: dict[str, Command],
) -> dict[str, Command]:
    """Entry-by-entry override: user wins."""
    merged = dict(defaults)
    merged.update(user)
    return merged
