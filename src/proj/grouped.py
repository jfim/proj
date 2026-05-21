"""Grouped-column SELECT augmentation and post-fetch formatter."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from proj.engine import _ref
from proj.marks import Mark

_COMPARISON_RE = re.compile(r"^\s*([\w-]+)\s*(=|!=|<=|>=|<|>)\s*([\w-]+)\s*$")
_BARE_RE = re.compile(r"^[\w-]+$")
_VALID_MODES = {"applicable", "all"}


@dataclass(frozen=True)
class ColumnRef:
    name: str

    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class ComparisonExpr:
    left: str
    op: str
    right: str

    def label(self) -> str:
        return f"{self.left} {self.op} {self.right}"


InputColumn = ColumnRef | ComparisonExpr


@dataclass(frozen=True)
class GroupedColumnConfig:
    name: str
    mode: str  # "applicable" | "all"
    inputs: tuple[InputColumn, ...]
    on_pass: str  # "hide" or mark name
    on_fail: str
    on_error: str
    on_na: str


def parse_input_column(expr: str) -> InputColumn:
    """Parse a `grouped_columns.<g>.columns` entry: bare name or `<a> OP <b>`."""
    m = _COMPARISON_RE.match(expr)
    if m:
        return ComparisonExpr(m.group(1), m.group(2), m.group(3))
    if not _BARE_RE.match(expr.strip()):
        raise ValueError(
            f"grouped_columns.columns entry not a valid column or comparison: {expr!r}"
        )
    return ColumnRef(expr.strip())


def parse_grouped_columns(raw: dict[str, Any] | None) -> list[GroupedColumnConfig]:
    """Parse the `grouped_columns:` mapping on a query-type command."""
    if not raw:
        return []
    out: list[GroupedColumnConfig] = []
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"grouped_columns.{name}: must be a mapping")
        mode = body.get("mode", "applicable")
        if mode not in _VALID_MODES:
            raise ValueError(
                f"grouped_columns.{name}: mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"
            )
        cols = body.get("columns")
        if not isinstance(cols, list) or not cols:
            raise ValueError(f"grouped_columns.{name}: 'columns' must be a non-empty list")
        inputs = tuple(parse_input_column(str(c)) for c in cols)
        out.append(
            GroupedColumnConfig(
                name=name,
                mode=mode,
                inputs=inputs,
                on_pass=str(body.get("on_pass", "mark-good")),
                on_fail=str(body.get("on_fail", "mark-bad")),
                on_error=str(body.get("on_error", "mark-warn")),
                on_na=str(body.get("on_na", "mark-ignored")),
            )
        )
    return out


def _value_expr_for(inp: InputColumn) -> str:
    """SQL expression for the input column's value, aliased to its label."""
    label = inp.label()
    if isinstance(inp, ColumnRef):
        return f"{_ref(inp.name)} AS {_ref(label)}"
    return f"({_ref(inp.left)} {inp.op} {_ref(inp.right)}) AS {_ref(label)}"


def _applies_expr_for(inp: InputColumn) -> str:
    """SQL expression for the input column's _applies partner."""
    label = inp.label() + "_applies"
    if isinstance(inp, ColumnRef):
        return f"{_ref(inp.name + '_applies')} AS {_ref(label)}"
    a_app = _ref(inp.left + "_applies")
    b_app = _ref(inp.right + "_applies")
    return f"({a_app} AND {b_app}) AS {_ref(label)}"


def build_grouped_selects(
    configs: Iterable[GroupedColumnConfig],
) -> list[str]:
    """Return SELECT-fragment list for all unique input columns + their _applies partners."""
    seen: set[str] = set()
    out: list[str] = []
    for cfg in configs:
        for inp in cfg.inputs:
            key = inp.label()
            if key in seen:
                continue
            seen.add(key)
            out.append(_value_expr_for(inp))
            out.append(_applies_expr_for(inp))
    return out


# ---------- per-row formatter ----------


@dataclass(frozen=True)
class Line:
    """One line in a grouped cell: text + optional mark."""

    text: str
    mark: Mark | None  # None means no styling (e.g., the count summary)


def _state(applies: Any, value: Any) -> str:
    """Resolve the (applies, value) pair into a state name."""
    if not applies:
        return "na"
    if value is None:
        return "error"
    return "pass" if value else "fail"


def _resolve_mark_key(cfg: GroupedColumnConfig, state: str) -> str:
    return {
        "pass": cfg.on_pass,
        "fail": cfg.on_fail,
        "error": cfg.on_error,
        "na": cfg.on_na,
    }[state]


def format_grouped_cell(
    cfg: GroupedColumnConfig,
    row: dict[str, Any],
    marks: dict[str, Mark],
) -> list[Line]:
    """Render the multi-line cell for one row's grouped column."""
    passed = 0
    applicable = 0
    detail: list[Line] = []
    for inp in cfg.inputs:
        label = inp.label()
        value = row.get(label)
        applies = row.get(label + "_applies", 0)
        state = _state(applies, value)
        if state != "na":
            applicable += 1
        if state == "pass":
            passed += 1
        mark_key = _resolve_mark_key(cfg, state)
        if mark_key == "hide":
            continue
        mark = marks.get(mark_key, Mark())
        detail.append(Line(text=label, mark=mark))

    denom = applicable if cfg.mode == "applicable" else len(cfg.inputs)
    summary = Line(text=f"{passed}/{denom}", mark=None)
    return [summary, *detail]
