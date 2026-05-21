"""Column registry and specification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proj.errors import UnknownColumnError

Evaluator = Callable[[str, Path], Any]
"""Signature: (rendered_command_or_marker, cwd) -> raw_value_to_coerce."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str                                 # text | integer | boolean | real
    applies_to: str | None                    # SQL where-expression (cheap gate)
    applies_when: str | None                  # shell command template (expensive gate)
    cache: bool                               # whether to persist results across runs
    value_from_template: str | None           # shell command template; None for non-shell built-ins
    evaluator: Evaluator                      # how to compute the raw value


class ColumnRegistry:
    def __init__(self) -> None:
        self._cols: dict[str, ColumnSpec] = {}

    def register(self, spec: ColumnSpec) -> None:
        """Register or override a column. Later registrations win (user > built-in)."""
        self._cols[spec.name] = spec

    def get(self, name: str) -> ColumnSpec:
        try:
            return self._cols[name]
        except KeyError:
            raise UnknownColumnError(name) from None

    def has(self, name: str) -> bool:
        return name in self._cols

    def names(self) -> list[str]:
        return list(self._cols.keys())

    def __iter__(self):
        return iter(self._cols.values())
