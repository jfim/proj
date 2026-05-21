"""Built-in column evaluators.

Most built-in columns now live in ``defaults.yaml`` as ordinary shell
``value-from`` entries (the simple ones) or as ``proj-col <name>`` invocations
backed by :mod:`proj.column_helpers` (the two with awkward portability or
branching logic). The single exception is ``last_modified``: it's materialized
eagerly into the projects table at engine-build time, so it stays here and
bypasses the column-registry evaluator path entirely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from proj.columns import ColumnRegistry, ColumnSpec


def eval_last_modified(_template: str, cwd: Path) -> Any:
    """Maximum mtime among files in the project directory (one level deep), as Unix timestamp."""
    if not cwd.exists():
        return None
    try:
        mtimes = [int(p.stat().st_mtime) for p in cwd.iterdir() if p.is_file()]
    except OSError:
        return None
    return max(mtimes) if mtimes else int(cwd.stat().st_mtime)


def register_builtins(reg: ColumnRegistry) -> None:
    """Register Python-evaluated built-in columns. Currently only ``last_modified``."""
    reg.register(
        ColumnSpec(
            name="last_modified",
            type="integer",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="",
            evaluator=eval_last_modified,
        )
    )
