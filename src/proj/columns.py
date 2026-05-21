"""Column registry and specification."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proj.errors import UnknownColumnError
from proj.manifest import ColumnEntry

Evaluator = Callable[[str, Path], Any]
"""Signature: (rendered_command_or_marker, cwd) -> raw_value_to_coerce."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str  # text | integer | boolean | real
    applies_to: str | None  # SQL where-expression (cheap gate)
    applies_when: str | None  # shell command template (expensive gate)
    cache: bool  # whether to persist results across runs
    value_from_template: str | None  # shell command template; None for non-shell built-ins
    evaluator: Evaluator  # how to compute the raw value


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


_BOOL_TRUE = {"true", "1", "yes"}
_BOOL_FALSE = {"false", "0", "no", ""}


def coerce_to_type(raw: Any, ctype: str) -> Any:
    """Coerce a raw shell-output value to the declared column type. Returns None on failure."""
    if raw is None:
        return None
    s = raw.strip() if isinstance(raw, str) else raw

    if ctype == "text":
        return s if isinstance(s, str) else str(s)
    if ctype == "integer":
        try:
            return int(s)
        except (ValueError, TypeError):
            return None
    if ctype == "real":
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
    if ctype == "boolean":
        if isinstance(s, bool):
            return 1 if s else 0
        if isinstance(s, str):
            low = s.lower()
            if low in _BOOL_TRUE:
                return 1
            if low in _BOOL_FALSE:
                return 0
            return None
        return None
    return None


def make_shell_evaluator(timeout: float = 30.0) -> Evaluator:
    """Build a shell-based evaluator. The 'rendered' arg is the post-interpolation command."""

    def evaluator(rendered: str, cwd: Path) -> Any:
        try:
            result = subprocess.run(
                ["sh", "-c", rendered],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    return evaluator


def register_user_columns(reg: ColumnRegistry, entries: dict[str, ColumnEntry]) -> None:
    """Register user-defined columns from the manifest. Overrides built-ins of the same name."""
    shell_eval = make_shell_evaluator()
    for _name, entry in entries.items():
        reg.register(
            ColumnSpec(
                name=entry.name,
                type=entry.type,
                applies_to=entry.applies_to,
                applies_when=entry.applies_when,
                cache=entry.cache,
                value_from_template=entry.value_from,
                evaluator=shell_eval,
            )
        )
