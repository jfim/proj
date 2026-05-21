"""Built-in column evaluators."""

from __future__ import annotations

import contextlib
import json
import subprocess
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


def _run(cmd: list[str], cwd: Path, check_returncode: bool = False) -> tuple[int, str]:
    """Run a subprocess; return (returncode, stdout-stripped). Never raises."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return 1, ""
    if check_returncode and result.returncode != 0:
        return result.returncode, ""
    return result.returncode, result.stdout.strip()


def eval_size(_template: str, cwd: Path) -> int | None:
    """Total bytes in cwd, recursive. Returns None on failure."""
    if not cwd.exists():
        return None
    total = 0
    try:
        for p in cwd.rglob("*"):
            if p.is_file():
                with contextlib.suppress(OSError):
                    total += p.stat().st_size
    except OSError:
        return None
    return total


def eval_git_dirty(_template: str, cwd: Path) -> str:
    rc, out = _run(["git", "status", "--porcelain"], cwd)
    if rc != 0:
        return "false"
    return "true" if out else "false"


def eval_git_branch(_template: str, cwd: Path) -> str | None:
    rc, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return out if rc == 0 else None


def eval_git_ahead(_template: str, cwd: Path) -> int:
    rc, out = _run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd)
    if rc != 0 or not out:
        return 0
    try:
        return int(out)
    except ValueError:
        return 0


def eval_git_behind(_template: str, cwd: Path) -> int:
    rc, out = _run(["git", "rev-list", "--count", "HEAD..@{u}"], cwd)
    if rc != 0 or not out:
        return 0
    try:
        return int(out)
    except ValueError:
        return 0


def eval_git_last_commit(_template: str, cwd: Path) -> int | None:
    rc, out = _run(["git", "log", "-1", "--format=%ct"], cwd)
    if rc != 0 or not out:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def eval_clean_target(_template: str, cwd: Path) -> str | None:
    """Auto-detect the project's clean command. Order: justfile, Makefile, Cargo, npm, gradle."""
    if (cwd / "justfile").exists() and "clean" in (cwd / "justfile").read_text():
        return "just clean"
    if (cwd / "Makefile").exists() and "clean" in (cwd / "Makefile").read_text():
        return "make clean"
    if (cwd / "Cargo.toml").exists():
        return "cargo clean"
    pkg = cwd / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            if "clean" in (data.get("scripts") or {}):
                return "npm run clean"
        except (json.JSONDecodeError, OSError):
            pass
    if (cwd / "build.gradle").exists() or (cwd / "build.gradle.kts").exists():
        return "./gradlew clean"
    return None


def register_expensive_builtins(reg: ColumnRegistry) -> None:
    reg.register(ColumnSpec(
        name="size", type="integer", applies_to=None, applies_when=None,
        cache=True, value_from_template="", evaluator=eval_size,
    ))
    reg.register(ColumnSpec(
        name="dirty", type="boolean", applies_to="git", applies_when=None,
        cache=False, value_from_template="", evaluator=eval_git_dirty,
    ))
    reg.register(ColumnSpec(
        name="branch", type="text", applies_to="git", applies_when=None,
        cache=False, value_from_template="", evaluator=eval_git_branch,
    ))
    reg.register(ColumnSpec(
        name="ahead", type="integer", applies_to="git", applies_when=None,
        cache=False, value_from_template="", evaluator=eval_git_ahead,
    ))
    reg.register(ColumnSpec(
        name="behind", type="integer", applies_to="git", applies_when=None,
        cache=False, value_from_template="", evaluator=eval_git_behind,
    ))
    reg.register(ColumnSpec(
        name="last_commit", type="integer", applies_to="git", applies_when=None,
        cache=True, value_from_template="", evaluator=eval_git_last_commit,
    ))
    reg.register(ColumnSpec(
        name="clean_target", type="text", applies_to=None, applies_when=None,
        cache=True, value_from_template="", evaluator=eval_clean_target,
    ))
