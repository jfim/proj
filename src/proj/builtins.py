"""Built-in column evaluators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from proj.columns import ColumnRegistry, ColumnSpec

# Marker file → language column name. Multi-marker languages use a tuple.
_LANG_MARKERS: dict[str, tuple[str, ...]] = {
    "lang_rust":    ("Cargo.toml",),
    "lang_python":  ("pyproject.toml", "setup.py", "requirements.txt"),
    "lang_elixir":  ("mix.exs",),
    "lang_scala":   ("build.sbt",),
    "lang_r":       ("DESCRIPTION",),
    "lang_js":      ("package.json",),
    "lang_ts":      ("tsconfig.json",),
    "lang_go":      ("go.mod",),
    "lang_java":    ("pom.xml", "build.gradle"),
    "lang_kotlin":  ("build.gradle.kts",),
}

_FILE_PRESENCE = {
    "has_makefile":  "Makefile",
    "has_justfile":  "justfile",
    "has_readme":    "README.md",
    "has_license":   "LICENSE",
}


def eval_last_modified(_template: str, cwd: Path) -> Any:
    """Maximum mtime among files in the project directory (one level deep), as Unix timestamp."""
    if not cwd.exists():
        return None
    try:
        mtimes = [int(p.stat().st_mtime) for p in cwd.iterdir() if p.is_file()]
    except OSError:
        return None
    return max(mtimes) if mtimes else int(cwd.stat().st_mtime)


def eval_lang_check(markers_csv: str, cwd: Path) -> str:
    """Return "true" if any marker file exists in cwd, else "false". markers_csv is comma-separated."""
    markers = [m.strip() for m in markers_csv.split(",") if m.strip()]
    return "true" if any((cwd / m).exists() for m in markers) else "false"


def eval_file_exists(filename: str, cwd: Path) -> str:
    return "true" if (cwd / filename).exists() else "false"


def eval_git(_template: str, cwd: Path) -> str:
    return "true" if (cwd / ".git").exists() else "false"


def register_cheap_builtins(reg: ColumnRegistry) -> None:
    """Register the cheap built-in columns (no shell-out)."""
    reg.register(ColumnSpec(
        name="last_modified", type="integer",
        applies_to=None, applies_when=None, cache=False,
        value_from_template="", evaluator=eval_last_modified,
    ))
    reg.register(ColumnSpec(
        name="git", type="boolean",
        applies_to=None, applies_when=None, cache=False,
        value_from_template="", evaluator=eval_git,
    ))
    for col_name, marker in _FILE_PRESENCE.items():
        reg.register(ColumnSpec(
            name=col_name, type="boolean",
            applies_to=None, applies_when=None, cache=False,
            value_from_template=marker, evaluator=eval_file_exists,
        ))
    for col_name, markers in _LANG_MARKERS.items():
        reg.register(ColumnSpec(
            name=col_name, type="boolean",
            applies_to=None, applies_when=None, cache=False,
            value_from_template=",".join(markers), evaluator=eval_lang_check,
        ))
