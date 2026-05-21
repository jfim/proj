# proj v1 — Query Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation of `proj`: manifest loading, the SQLite-backed column engine with paired `_applies` columns, on-disk cache, dispatch functions, variable interpolation, the built-in column set, and the `proj query` primitive. After this plan lands, a user can install `proj`, drop a manifest at `~/.config/proj/projects.yaml`, and run `proj query 'name, size, dirty' --where 'mine and lang_rust'` against their workspace.

**Architecture:** Two registered SQLite scalar functions (`get_column_value`, `get_column_applies`) dispatch from a `:memory:` table whose schema is built per-invocation from the merged manifest. Each non-tag column synthesizes a paired `<name>_applies` virtual column. Tag columns are non-virtual INTEGERs INSERTed eagerly. On-disk cache lives at `~/.cache/proj/` and is keyed by `(project_name, column_name, hash(post-interpolation-command))`.

**Tech Stack:** Python 3.10+, click, pyyaml, rich (table output), pytest. SQLite via stdlib `sqlite3`. No new dependencies beyond what's in pyproject.toml.

**Out of scope for this plan** (deferred to follow-up plans):
- Commands-as-config + `defaults.yaml` (`proj ls`, `proj status`, `proj clean`, `proj audit`, `proj archive` as user-overridable commands)
- Grouped columns, marks, comparison expressions in grouped columns
- Mutating primitives: `proj adopt`, `proj forget`, `proj new`, the `run` primitive, templates
- Unknown-subdirectory detection (`unknown` column will be a constant 0 for now; full impl in a later plan)
- Auto-scope based on cwd
- `--parallel`, `--summary`, `--dry-run`
- `proj defaults` command

---

## File Structure

```
src/proj/
  __init__.py            # __version__ (existing)
  cli.py                 # click root group + `query` command (replace existing stub)
  manifest.py            # YAML loading, validation, identifier normalization
  projects.py            # Project + ProjectRegistry: name, path, vars, tags
  columns.py             # ColumnSpec + ColumnRegistry (built-in + user-defined)
  builtins.py            # Built-in column evaluators (size, lang_*, git stuff, etc.)
  cache.py               # On-disk cache (sqlite-backed, mtime+hash keyed)
  dispatch.py            # get_column_value, get_column_applies
  interpolation.py       # {{var}} substitution
  engine.py              # SQLite schema construction + query execution
  sql_funcs.py           # gb()/mb()/kb()/ago() registered scalar functions
  paths.py               # Path resolution (workspace root, project paths)
  output.py              # Table/JSON/plain formatters
  errors.py              # Domain exceptions

tests/
  __init__.py            # (existing)
  conftest.py            # Shared fixtures: tmp_workspace, sample_manifest
  test_cli.py            # (existing — will expand)
  test_manifest.py
  test_projects.py
  test_columns.py
  test_builtins.py
  test_cache.py
  test_dispatch.py
  test_interpolation.py
  test_engine.py
  test_sql_funcs.py
  test_paths.py
  test_output.py
  test_query_integration.py   # end-to-end: manifest + workspace fixtures → proj query
```

---

## Task 1: Path resolution helpers

**Files:**
- Create: `src/proj/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_paths.py
from pathlib import Path

import pytest

from proj.paths import config_path, cache_dir, resolve_project_path


def test_config_path_is_under_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "proj" / "projects.yaml"


def test_config_path_falls_back_to_home_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_path() == tmp_path / ".config" / "proj" / "projects.yaml"


def test_cache_dir_under_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache_dir() == tmp_path / "proj"


def test_resolve_project_path_default_is_workspace_slash_name(tmp_path):
    assert resolve_project_path("foo", None, tmp_path) == tmp_path / "foo"


def test_resolve_project_path_relative_is_under_workspace(tmp_path):
    assert resolve_project_path("foo", "other-dir", tmp_path) == tmp_path / "other-dir"


def test_resolve_project_path_tilde_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_project_path("foo", "~/elsewhere", tmp_path)
    assert result == tmp_path / "elsewhere"


def test_resolve_project_path_absolute_stays_absolute(tmp_path):
    abs_path = "/opt/projects/foo"
    assert resolve_project_path("foo", abs_path, tmp_path) == Path(abs_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_paths.py -v`
Expected: ImportError or ModuleNotFoundError on `proj.paths`.

- [ ] **Step 3: Implement paths.py**

```python
# src/proj/paths.py
"""Path resolution for config, cache, and project directories."""

from __future__ import annotations

import os
from pathlib import Path


def config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "proj" / "projects.yaml"


def cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "proj"


def resolve_project_path(name: str, declared: str | None, workspace_root: Path) -> Path:
    """Resolve a project's directory.

    - declared is None → workspace_root / name
    - declared is absolute → as-is
    - declared starts with ~ → expanded against $HOME
    - otherwise → workspace_root / declared (relative)
    """
    if declared is None:
        return workspace_root / name
    if declared.startswith("~"):
        return Path(declared).expanduser()
    p = Path(declared)
    if p.is_absolute():
        return p
    return workspace_root / declared
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_paths.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/paths.py tests/test_paths.py
git commit -m "feat: path resolution for config, cache, and project dirs"
```

---

## Task 2: Domain errors

**Files:**
- Create: `src/proj/errors.py`

- [ ] **Step 1: Write the module** (no tests needed — these are just exception classes)

```python
# src/proj/errors.py
"""Domain-specific exceptions for proj."""


class ProjError(Exception):
    """Base class for all proj errors."""


class ManifestError(ProjError):
    """Raised when the manifest is malformed or invalid."""


class UnknownColumnError(ProjError):
    """Raised when a column referenced in config or a query is not registered."""


class UnknownProjectError(ProjError):
    """Raised when a project name is not in the registry."""


class ReservedNameError(ManifestError):
    """Raised when the manifest uses a reserved name (e.g., column ending in _applies)."""
```

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "from proj.errors import ProjError, ManifestError; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/proj/errors.py
git commit -m "feat: domain exception hierarchy"
```

---

## Task 3: Manifest loader

**Files:**
- Create: `src/proj/manifest.py`
- Test: `tests/test_manifest.py`

The manifest loader reads `projects.yaml`, validates structural correctness, normalizes identifiers (colons to underscores in tags), and returns a typed dataclass-tree. It does NOT resolve project paths or build registries yet — those are downstream concerns.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_manifest.py
from pathlib import Path

import pytest
import yaml

from proj.errors import ManifestError, ReservedNameError
from proj.manifest import (
    Manifest,
    ProjectEntry,
    ColumnEntry,
    load_manifest,
    normalize_identifier,
)


def write(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "projects.yaml"
    p.write_text(yaml.safe_dump(content))
    return p


def test_normalize_identifier_colon_to_underscore():
    assert normalize_identifier("lang:elixir") == "lang_elixir"
    assert normalize_identifier("plain") == "plain"
    assert normalize_identifier("has-readme") == "has-readme"   # hyphens preserved


def test_loads_minimal_manifest(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {"foo": {"tags": ["mine"]}},
    })
    m = load_manifest(p)
    assert m.workspace_root == Path(str(tmp_path)).resolve()
    assert "foo" in m.projects
    assert m.projects["foo"].tags == ["mine"]


def test_normalizes_tags_with_colons(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {"foo": {"tags": ["lang:rust", "mine"]}},
    })
    m = load_manifest(p)
    assert m.projects["foo"].tags == ["lang_rust", "mine"]


def test_project_vars_captured(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {
            "foo": {"tags": ["mine"], "host": "server1.tld", "deploy-path": "/var/foo"},
        },
    })
    m = load_manifest(p)
    assert m.projects["foo"].vars == {"host": "server1.tld", "deploy-path": "/var/foo"}
    assert m.projects["foo"].path_override is None


def test_project_path_override_captured(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {"foo": {"tags": [], "path": "elsewhere"}},
    })
    m = load_manifest(p)
    assert m.projects["foo"].path_override == "elsewhere"


def test_column_definition_required_type(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {},
        "columns": {
            "has_readme": {
                "value-from": "test -f README.md && echo true || echo false",
                "type": "boolean",
            }
        },
    })
    m = load_manifest(p)
    col = m.columns["has_readme"]
    assert col.value_from == "test -f README.md && echo true || echo false"
    assert col.type == "boolean"
    assert col.applies_to is None
    assert col.applies_when is None
    assert col.cache is False


def test_column_missing_type_errors(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {},
        "columns": {"has_readme": {"value-from": "test -f README.md"}},
    })
    with pytest.raises(ManifestError, match="type"):
        load_manifest(p)


def test_column_with_applies_to_and_when(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {},
        "columns": {
            "otp_version": {
                "applies-to": "lang_elixir",
                "applies-when": "test -f .tool-versions",
                "value-from": "grep otp .tool-versions",
                "type": "text",
                "cache": True,
            }
        },
    })
    m = load_manifest(p)
    col = m.columns["otp_version"]
    assert col.applies_to == "lang_elixir"
    assert col.applies_when == "test -f .tool-versions"
    assert col.cache is True


def test_reserved_applies_suffix_rejected(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {},
        "columns": {"foo_applies": {"value-from": "echo 1", "type": "boolean"}},
    })
    with pytest.raises(ReservedNameError):
        load_manifest(p)


def test_missing_workspace_root_errors(tmp_path):
    p = write(tmp_path, {"projects": {}})
    with pytest.raises(ManifestError, match="workspace.root"):
        load_manifest(p)


def test_unknown_column_type_errors(tmp_path):
    p = write(tmp_path, {
        "workspace": {"root": str(tmp_path)},
        "projects": {},
        "columns": {"foo": {"value-from": "x", "type": "bogus"}},
    })
    with pytest.raises(ManifestError, match="type"):
        load_manifest(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement manifest.py**

```python
# src/proj/manifest.py
"""YAML manifest loading and structural validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from proj.errors import ManifestError, ReservedNameError

VALID_COLUMN_TYPES = {"text", "integer", "boolean", "real"}
RESERVED_PROJECT_KEYS = {"tags", "path"}


@dataclass(frozen=True)
class ProjectEntry:
    name: str
    tags: list[str]
    path_override: str | None
    vars: dict[str, str]


@dataclass(frozen=True)
class ColumnEntry:
    name: str
    type: str
    value_from: str | None        # None for built-in stand-ins; user columns always have this
    applies_to: str | None
    applies_when: str | None
    cache: bool


@dataclass(frozen=True)
class Manifest:
    workspace_root: Path
    projects: dict[str, ProjectEntry]
    columns: dict[str, ColumnEntry]
    settings: dict[str, Any]


def normalize_identifier(s: str) -> str:
    """Normalize a tag/column identifier: colons → underscores. Hyphens are preserved."""
    return s.replace(":", "_")


def _parse_project(name: str, raw: dict[str, Any]) -> ProjectEntry:
    if not isinstance(raw, dict):
        raise ManifestError(f"project {name!r}: entry must be a mapping")
    tags = raw.get("tags", []) or []
    if not isinstance(tags, list):
        raise ManifestError(f"project {name!r}: tags must be a list")
    tags = [normalize_identifier(str(t)) for t in tags]
    path_override = raw.get("path")
    if path_override is not None and not isinstance(path_override, str):
        raise ManifestError(f"project {name!r}: path must be a string")
    vars_ = {k: str(v) for k, v in raw.items() if k not in RESERVED_PROJECT_KEYS}
    return ProjectEntry(name=name, tags=tags, path_override=path_override, vars=vars_)


def _parse_column(name: str, raw: dict[str, Any]) -> ColumnEntry:
    if name.endswith("_applies"):
        raise ReservedNameError(
            f"column {name!r}: names ending in _applies are reserved"
        )
    if not isinstance(raw, dict):
        raise ManifestError(f"column {name!r}: entry must be a mapping")
    if "type" not in raw:
        raise ManifestError(f"column {name!r}: 'type' is required")
    col_type = raw["type"]
    if col_type not in VALID_COLUMN_TYPES:
        raise ManifestError(
            f"column {name!r}: type {col_type!r} not in {sorted(VALID_COLUMN_TYPES)}"
        )
    return ColumnEntry(
        name=name,
        type=col_type,
        value_from=raw.get("value-from"),
        applies_to=raw.get("applies-to"),
        applies_when=raw.get("applies-when"),
        cache=bool(raw.get("cache", False)),
    )


def load_manifest(path: Path) -> Manifest:
    """Read and validate a manifest YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be a mapping")

    ws = data.get("workspace")
    if not isinstance(ws, dict) or "root" not in ws:
        raise ManifestError("workspace.root is required")
    workspace_root = Path(str(ws["root"])).expanduser().resolve()

    projects: dict[str, ProjectEntry] = {}
    for pname, praw in (data.get("projects") or {}).items():
        projects[pname] = _parse_project(pname, praw)

    columns: dict[str, ColumnEntry] = {}
    for cname, craw in (data.get("columns") or {}).items():
        columns[cname] = _parse_column(cname, craw)

    settings = dict(data.get("settings") or {})
    return Manifest(
        workspace_root=workspace_root,
        projects=projects,
        columns=columns,
        settings=settings,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/manifest.py tests/test_manifest.py
git commit -m "feat: manifest loader with structural validation and identifier normalization"
```

---

## Task 4: Project registry

**Files:**
- Create: `src/proj/projects.py`
- Test: `tests/test_projects.py`

The project registry takes a parsed manifest and resolves each project to an absolute path, surfacing the lookup the dispatch functions need (project name → vars + path).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projects.py
from pathlib import Path

import pytest

from proj.errors import UnknownProjectError
from proj.manifest import Manifest, ProjectEntry
from proj.projects import Project, ProjectRegistry


def make_manifest(tmp_path: Path, projects: dict[str, ProjectEntry]) -> Manifest:
    return Manifest(
        workspace_root=tmp_path,
        projects=projects,
        columns={},
        settings={},
    )


def test_default_path_is_workspace_slash_name(tmp_path):
    m = make_manifest(
        tmp_path,
        {"foo": ProjectEntry(name="foo", tags=["mine"], path_override=None, vars={})},
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.get("foo").path == tmp_path / "foo"
    assert reg.get("foo").name == "foo"


def test_path_override_relative(tmp_path):
    m = make_manifest(
        tmp_path,
        {"foo": ProjectEntry(name="foo", tags=[], path_override="other", vars={})},
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.get("foo").path == tmp_path / "other"


def test_vars_preserved(tmp_path):
    m = make_manifest(
        tmp_path,
        {
            "foo": ProjectEntry(
                name="foo", tags=[], path_override=None,
                vars={"host": "server1.tld"},
            )
        },
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.get("foo").vars == {"host": "server1.tld"}


def test_unknown_project_raises(tmp_path):
    reg = ProjectRegistry.from_manifest(make_manifest(tmp_path, {}))
    with pytest.raises(UnknownProjectError):
        reg.get("nonexistent")


def test_names_returns_all(tmp_path):
    m = make_manifest(
        tmp_path,
        {
            "a": ProjectEntry(name="a", tags=[], path_override=None, vars={}),
            "b": ProjectEntry(name="b", tags=[], path_override=None, vars={}),
        },
    )
    reg = ProjectRegistry.from_manifest(m)
    assert sorted(reg.names()) == ["a", "b"]


def test_all_tags_collects_unique_normalized(tmp_path):
    m = make_manifest(
        tmp_path,
        {
            "a": ProjectEntry(name="a", tags=["oss", "mine"], path_override=None, vars={}),
            "b": ProjectEntry(name="b", tags=["oss", "rust"], path_override=None, vars={}),
        },
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.all_tags() == {"mine", "oss", "rust"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_projects.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement projects.py**

```python
# src/proj/projects.py
"""Project registry: resolve manifest project entries to runtime Project objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proj.errors import UnknownProjectError
from proj.manifest import Manifest, ProjectEntry
from proj.paths import resolve_project_path


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    tags: list[str]
    vars: dict[str, str]


class ProjectRegistry:
    def __init__(self, projects: dict[str, Project], workspace_root: Path) -> None:
        self._projects = projects
        self.workspace_root = workspace_root

    @classmethod
    def from_manifest(cls, manifest: Manifest) -> "ProjectRegistry":
        projects: dict[str, Project] = {}
        for name, entry in manifest.projects.items():
            path = resolve_project_path(name, entry.path_override, manifest.workspace_root)
            projects[name] = Project(name=name, path=path, tags=list(entry.tags), vars=dict(entry.vars))
        return cls(projects, manifest.workspace_root)

    def get(self, name: str) -> Project:
        try:
            return self._projects[name]
        except KeyError:
            raise UnknownProjectError(name)

    def names(self) -> list[str]:
        return list(self._projects.keys())

    def all_tags(self) -> set[str]:
        tags: set[str] = set()
        for p in self._projects.values():
            tags.update(p.tags)
        return tags

    def __iter__(self):
        return iter(self._projects.values())

    def __len__(self) -> int:
        return len(self._projects)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_projects.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/projects.py tests/test_projects.py
git commit -m "feat: project registry resolves manifest entries to runtime Project objects"
```

---

## Task 5: Variable interpolation

**Files:**
- Create: `src/proj/interpolation.py`
- Test: `tests/test_interpolation.py`

Mustache-style `{{key}}` substitution. Auto-injected variables (`name`, `path`, `workspace_root`, `archive_dir`) combine with per-project vars; project vars shadow auto-injected ones.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_interpolation.py
import pytest

from proj.interpolation import interpolate


def test_simple_substitution():
    assert interpolate("hello {{name}}", {"name": "world"}) == "hello world"


def test_multiple_substitutions():
    assert interpolate("{{a}} and {{b}}", {"a": "x", "b": "y"}) == "x and y"


def test_repeated_substitution():
    assert interpolate("{{name}}-{{name}}", {"name": "z"}) == "z-z"


def test_hyphenated_key():
    assert interpolate("path: {{deploy-path}}", {"deploy-path": "/var/foo"}) == "path: /var/foo"


def test_missing_var_leaves_literal():
    # We choose: missing variables produce a clear error rather than silent passthrough.
    with pytest.raises(KeyError, match="missing"):
        interpolate("hello {{nope}}", {"name": "x"})


def test_no_substitution_when_no_braces():
    assert interpolate("plain string", {"x": "y"}) == "plain string"


def test_adjacent_substitutions():
    assert interpolate("{{a}}{{b}}", {"a": "1", "b": "2"}) == "12"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_interpolation.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement interpolation.py**

```python
# src/proj/interpolation.py
"""Mustache-style {{var}} substitution for shell command strings."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"\{\{([\w-]+)\}\}")


def interpolate(template: str, vars: dict[str, str]) -> str:
    """Substitute {{key}} occurrences in template with vars[key].

    Raises KeyError if a referenced variable is missing.
    """
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in vars:
            raise KeyError(f"missing variable: {{{{ {key} }}}}")
        return vars[key]

    return _PATTERN.sub(replace, template)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_interpolation.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/interpolation.py tests/test_interpolation.py
git commit -m "feat: {{var}} substitution helper"
```

---

## Task 6: Column registry and ColumnSpec

**Files:**
- Create: `src/proj/columns.py`
- Test: `tests/test_columns.py`

A `ColumnSpec` describes one column: type, optional `applies-to`/`applies-when`, the evaluator function. Built-in columns register their own evaluators; user-defined columns build evaluators that shell out via interpolation.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_columns.py
import pytest

from proj.columns import ColumnSpec, ColumnRegistry
from proj.errors import UnknownColumnError


def dummy_eval(rendered: str, cwd) -> str:
    return "ok"


def test_register_and_lookup():
    reg = ColumnRegistry()
    spec = ColumnSpec(
        name="foo",
        type="text",
        applies_to=None,
        applies_when=None,
        cache=False,
        value_from_template="echo foo",
        evaluator=dummy_eval,
    )
    reg.register(spec)
    assert reg.get("foo") is spec


def test_lookup_unknown_raises():
    reg = ColumnRegistry()
    with pytest.raises(UnknownColumnError):
        reg.get("nope")


def test_has_returns_bool():
    reg = ColumnRegistry()
    assert not reg.has("foo")
    reg.register(ColumnSpec(
        name="foo", type="text", applies_to=None, applies_when=None,
        cache=False, value_from_template="x", evaluator=dummy_eval,
    ))
    assert reg.has("foo")


def test_user_columns_can_override_builtins():
    reg = ColumnRegistry()
    builtin = ColumnSpec(
        name="size", type="integer", applies_to=None, applies_when=None,
        cache=True, value_from_template=None, evaluator=dummy_eval,
    )
    reg.register(builtin)
    override = ColumnSpec(
        name="size", type="integer", applies_to=None, applies_when=None,
        cache=True, value_from_template="echo 42", evaluator=dummy_eval,
    )
    reg.register(override)
    assert reg.get("size").value_from_template == "echo 42"


def test_names_returns_registered():
    reg = ColumnRegistry()
    for n in ("a", "b", "c"):
        reg.register(ColumnSpec(
            name=n, type="text", applies_to=None, applies_when=None,
            cache=False, value_from_template="x", evaluator=dummy_eval,
        ))
    assert sorted(reg.names()) == ["a", "b", "c"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_columns.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement columns.py**

```python
# src/proj/columns.py
"""Column registry and specification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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
            raise UnknownColumnError(name)

    def has(self, name: str) -> bool:
        return name in self._cols

    def names(self) -> list[str]:
        return list(self._cols.keys())

    def __iter__(self):
        return iter(self._cols.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_columns.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/columns.py tests/test_columns.py
git commit -m "feat: column registry and ColumnSpec"
```

---

## Task 7: On-disk cache layer

**Files:**
- Create: `src/proj/cache.py`
- Test: `tests/test_cache.py`

A small persistent KV store. SQLite-backed file at `<cache_dir>/cache.db`. Key: `(project_name, column_name, cache_key)`; value: JSON-encoded scalar. Cache key is the SHA256 of the post-interpolation command string (and project's directory mtime if we want to invalidate on dir changes — for now we use just the command hash; mtime support can be added later in the dispatch function as needed).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cache.py
from pathlib import Path

import pytest

from proj.cache import Cache


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


def test_store_and_lookup_text(cache):
    cache.store("foo", "size", "k1", 12345)
    assert cache.lookup("foo", "size", "k1") == 12345


def test_lookup_miss_returns_none(cache):
    assert cache.lookup("foo", "size", "k1") is None


def test_different_keys_isolated(cache):
    cache.store("foo", "size", "k1", 1)
    cache.store("foo", "size", "k2", 2)
    assert cache.lookup("foo", "size", "k1") == 1
    assert cache.lookup("foo", "size", "k2") == 2


def test_store_overwrites_same_key(cache):
    cache.store("foo", "size", "k1", 1)
    cache.store("foo", "size", "k1", 2)
    assert cache.lookup("foo", "size", "k1") == 2


def test_store_none_value_is_lookup_miss(cache):
    cache.store("foo", "size", "k1", None)
    assert cache.lookup("foo", "size", "k1") is None


def test_preserves_types(cache):
    cache.store("p", "c", "k", 42)
    cache.store("p", "c2", "k", "hello")
    cache.store("p", "c3", "k", True)
    cache.store("p", "c4", "k", 3.14)
    assert cache.lookup("p", "c", "k") == 42
    assert cache.lookup("p", "c2", "k") == "hello"
    assert cache.lookup("p", "c3", "k") is True
    assert cache.lookup("p", "c4", "k") == 3.14


def test_persists_across_instances(tmp_path):
    db = tmp_path / "cache.db"
    c1 = Cache(db)
    c1.store("foo", "size", "k", 99)
    c2 = Cache(db)
    assert c2.lookup("foo", "size", "k") == 99


def test_command_hash_is_stable():
    assert Cache.command_hash("echo hi") == Cache.command_hash("echo hi")
    assert Cache.command_hash("a") != Cache.command_hash("b")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cache.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement cache.py**

```python
# src/proj/cache.py
"""On-disk cache for expensive column values."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                project TEXT NOT NULL,
                column TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (project, column, key)
            )
            """
        )
        self._conn.commit()

    def lookup(self, project: str, column: str, key: str) -> Any:
        row = self._conn.execute(
            "SELECT value FROM entries WHERE project=? AND column=? AND key=?",
            (project, column, key),
        ).fetchone()
        if row is None:
            return None
        decoded = json.loads(row[0])
        return None if decoded is None else decoded

    def store(self, project: str, column: str, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        self._conn.execute(
            "INSERT OR REPLACE INTO entries (project, column, key, value) VALUES (?, ?, ?, ?)",
            (project, column, key, encoded),
        )
        self._conn.commit()

    @staticmethod
    def command_hash(command: str) -> str:
        return hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cache.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/cache.py tests/test_cache.py
git commit -m "feat: on-disk SQLite cache for column values"
```

---

## Task 8: Type coercion helper

**Files:**
- Create: extend `src/proj/columns.py` with a `coerce_to_type` function
- Test: extend `tests/test_columns.py`

- [ ] **Step 1: Add tests to test_columns.py**

```python
# Append to tests/test_columns.py

from proj.columns import coerce_to_type


@pytest.mark.parametrize(
    "raw,ctype,expected",
    [
        ("42", "integer", 42),
        ("  17 ", "integer", 17),
        ("3.14", "real", 3.14),
        ("hello", "text", "hello"),
        ("  hi ", "text", "hi"),
        ("true", "boolean", 1),
        ("True", "boolean", 1),
        ("yes", "boolean", 1),
        ("1", "boolean", 1),
        ("false", "boolean", 0),
        ("0", "boolean", 0),
        ("no", "boolean", 0),
        ("", "boolean", 0),
        ("nonsense", "boolean", None),
        ("notanint", "integer", None),
        ("notafloat", "real", None),
    ],
)
def test_coerce_to_type(raw, ctype, expected):
    assert coerce_to_type(raw, ctype) == expected


def test_coerce_none_input_returns_none():
    assert coerce_to_type(None, "text") is None
    assert coerce_to_type(None, "integer") is None
    assert coerce_to_type(None, "boolean") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_columns.py::test_coerce_to_type -v`
Expected: ImportError on `coerce_to_type`.

- [ ] **Step 3: Add coerce_to_type to columns.py**

```python
# Append to src/proj/columns.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_columns.py -v`
Expected: all previous tests + 18 new coercion tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/columns.py tests/test_columns.py
git commit -m "feat: coerce_to_type for column value normalization"
```

---

## Task 9: Built-in column evaluators (cheap)

**Files:**
- Create: `src/proj/builtins.py`
- Test: `tests/test_builtins.py`

This task implements the **cheap** built-ins that don't need shell-out: `name`, `path`, `last_modified`, language detection (`lang_rust`, `lang_python`, etc.), filesystem presence (`has_makefile`, `has_justfile`, `has_readme`, `has_license`), and `git` (directory existence check).

Defer `size`, `dirty`, `branch`, `ahead`, `behind`, `last_commit`, `clean_target` to Task 10 (they need subprocess calls).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_builtins.py
from pathlib import Path

import pytest

from proj.builtins import register_cheap_builtins, eval_last_modified, eval_lang_check, eval_file_exists, eval_git
from proj.columns import ColumnRegistry


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_register_cheap_adds_expected_columns():
    reg = ColumnRegistry()
    register_cheap_builtins(reg)
    expected = {
        "last_modified",
        "git",
        "has_makefile", "has_justfile", "has_readme", "has_license",
        "lang_rust", "lang_python", "lang_elixir", "lang_scala", "lang_r",
        "lang_js", "lang_ts", "lang_go", "lang_java", "lang_kotlin",
    }
    assert expected.issubset(set(reg.names()))


def test_last_modified_returns_max_mtime(tmp_path):
    f1 = tmp_path / "a.txt"
    f1.write_text("x")
    import os, time
    os.utime(f1, (1700000000, 1700000000))
    f2 = tmp_path / "b.txt"
    f2.write_text("y")
    os.utime(f2, (1800000000, 1800000000))
    assert eval_last_modified("", tmp_path) == 1800000000


def test_last_modified_missing_dir_returns_none(tmp_path):
    assert eval_last_modified("", tmp_path / "does-not-exist") is None


def test_lang_check_detects_file(tmp_path):
    # Marker "Cargo.toml" exists
    (tmp_path / "Cargo.toml").write_text("")
    assert eval_lang_check("Cargo.toml", tmp_path) == "true"


def test_lang_check_missing_file(tmp_path):
    assert eval_lang_check("Cargo.toml", tmp_path) == "false"


def test_lang_python_detects_any_marker(tmp_path):
    # Python is detected via any of pyproject.toml / setup.py / requirements.txt
    reg = ColumnRegistry()
    register_cheap_builtins(reg)
    spec = reg.get("lang_python")
    (tmp_path / "requirements.txt").write_text("")
    assert spec.evaluator(spec.value_from_template, tmp_path) == "true"


def test_git_present(tmp_path):
    (tmp_path / ".git").mkdir()
    assert eval_git("", tmp_path) == "true"


def test_git_absent(tmp_path):
    assert eval_git("", tmp_path) == "false"


def test_has_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("")
    assert eval_file_exists("Makefile", tmp_path) == "true"
    assert eval_file_exists("NopeFile", tmp_path) == "false"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_builtins.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement builtins.py (cheap-only for now)**

```python
# src/proj/builtins.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_builtins.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/builtins.py tests/test_builtins.py
git commit -m "feat: cheap built-in column evaluators (lang detection, file presence, git, last_modified)"
```

---

## Task 10: Built-in column evaluators (expensive)

**Files:**
- Modify: `src/proj/builtins.py` to add `size`, `dirty`, `branch`, `ahead`, `behind`, `last_commit`, `clean_target`
- Test: extend `tests/test_builtins.py`

These use subprocess. They are cached (`cache=True`) by default.

- [ ] **Step 1: Add failing tests**

```python
# Append to tests/test_builtins.py
import subprocess

from proj.builtins import (
    eval_size, eval_git_dirty, eval_git_branch,
    eval_git_ahead, eval_git_behind, eval_git_last_commit,
    eval_clean_target, register_expensive_builtins,
)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "file").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_size_returns_int(tmp_path):
    (tmp_path / "f.bin").write_bytes(b"a" * 1024)
    result = eval_size("", tmp_path)
    assert isinstance(result, int)
    assert result > 0


def test_size_missing_dir_returns_none(tmp_path):
    assert eval_size("", tmp_path / "missing") is None


def test_dirty_returns_false_on_clean_repo(tmp_path):
    _git_init(tmp_path)
    assert eval_git_dirty("", tmp_path) == "false"


def test_dirty_returns_true_when_modified(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "file").write_text("changed")
    assert eval_git_dirty("", tmp_path) == "true"


def test_branch_returns_current(tmp_path):
    _git_init(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=tmp_path, check=True)
    assert eval_git_branch("", tmp_path) == "feature"


def test_ahead_and_behind_zero_on_no_upstream(tmp_path):
    _git_init(tmp_path)
    assert eval_git_ahead("", tmp_path) == 0
    assert eval_git_behind("", tmp_path) == 0


def test_last_commit_returns_timestamp(tmp_path):
    _git_init(tmp_path)
    ts = eval_git_last_commit("", tmp_path)
    assert isinstance(ts, int)
    assert ts > 0


def test_clean_target_for_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("clean:\n\trm -rf build\n")
    assert eval_clean_target("", tmp_path) == "make clean"


def test_clean_target_for_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("")
    assert eval_clean_target("", tmp_path) == "cargo clean"


def test_clean_target_for_justfile(tmp_path):
    (tmp_path / "justfile").write_text("clean:\n  echo cleaning\n")
    assert eval_clean_target("", tmp_path) == "just clean"


def test_clean_target_for_npm(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"clean":"rm -rf dist"}}')
    assert eval_clean_target("", tmp_path) == "npm run clean"


def test_clean_target_none(tmp_path):
    assert eval_clean_target("", tmp_path) is None


def test_register_expensive_adds_columns():
    reg = ColumnRegistry()
    register_expensive_builtins(reg)
    expected = {"size", "dirty", "branch", "ahead", "behind", "last_commit", "clean_target"}
    assert expected.issubset(set(reg.names()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_builtins.py -k "expensive or size or dirty or branch or ahead or behind or last_commit or clean_target" -v`
Expected: ImportError on the new functions.

- [ ] **Step 3: Extend builtins.py**

```python
# Append to src/proj/builtins.py
import json
import subprocess


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
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_builtins.py -v`
Expected: all built-in tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/builtins.py tests/test_builtins.py
git commit -m "feat: expensive built-in column evaluators (git stuff, size, clean_target)"
```

---

## Task 11: User-defined column evaluator factory

**Files:**
- Modify: `src/proj/columns.py` to add a factory function for user-defined columns
- Test: extend `tests/test_columns.py`

User-defined columns have a `value-from` shell template. The evaluator runs `sh -c "<rendered>"` in the project's cwd and returns stdout (stripped).

- [ ] **Step 1: Add failing tests**

```python
# Append to tests/test_columns.py
import subprocess


def test_shell_evaluator_captures_stdout(tmp_path):
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator()
    out = ev("echo hello", tmp_path)
    assert out == "hello"


def test_shell_evaluator_returns_none_on_nonzero(tmp_path):
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator()
    out = ev("false", tmp_path)
    assert out is None


def test_shell_evaluator_uses_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("data")
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator()
    out = ev("cat marker.txt", tmp_path)
    assert out == "data"


def test_shell_evaluator_timeout_returns_none(tmp_path):
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator(timeout=0.1)
    out = ev("sleep 1", tmp_path)
    assert out is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_columns.py::test_shell_evaluator_captures_stdout -v`
Expected: ImportError on `make_shell_evaluator`.

- [ ] **Step 3: Implement the factory**

```python
# Append to src/proj/columns.py
import subprocess


def make_shell_evaluator(timeout: float = 30.0) -> Evaluator:
    """Build a shell-based evaluator. The 'rendered' arg is the post-interpolation command."""
    def evaluator(rendered: str, cwd: Path) -> Any:
        try:
            result = subprocess.run(
                ["sh", "-c", rendered],
                cwd=cwd, capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    return evaluator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_columns.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/columns.py tests/test_columns.py
git commit -m "feat: shell-based evaluator factory for user-defined columns"
```

---

## Task 12: Wire manifest columns into registry

**Files:**
- Modify: `src/proj/columns.py` to add `register_user_columns`
- Test: extend `tests/test_columns.py`

- [ ] **Step 1: Add failing test**

```python
# Append to tests/test_columns.py
from proj.manifest import ColumnEntry


def test_register_user_columns_creates_specs():
    from proj.columns import register_user_columns

    entries = {
        "has_lic": ColumnEntry(
            name="has_lic", type="boolean",
            value_from="test -f LICENSE && echo true || echo false",
            applies_to="oss", applies_when=None, cache=False,
        ),
    }
    reg = ColumnRegistry()
    register_user_columns(reg, entries)
    spec = reg.get("has_lic")
    assert spec.applies_to == "oss"
    assert spec.value_from_template.startswith("test -f LICENSE")
    assert spec.type == "boolean"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_columns.py::test_register_user_columns_creates_specs -v`
Expected: ImportError on `register_user_columns`.

- [ ] **Step 3: Implement**

```python
# Append to src/proj/columns.py
from proj.manifest import ColumnEntry


def register_user_columns(reg: ColumnRegistry, entries: dict[str, ColumnEntry]) -> None:
    """Register user-defined columns from the manifest. Overrides built-ins of the same name."""
    shell_eval = make_shell_evaluator()
    for name, entry in entries.items():
        reg.register(ColumnSpec(
            name=entry.name,
            type=entry.type,
            applies_to=entry.applies_to,
            applies_when=entry.applies_when,
            cache=entry.cache,
            value_from_template=entry.value_from,
            evaluator=shell_eval,
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_columns.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/columns.py tests/test_columns.py
git commit -m "feat: wire manifest column entries into the registry"
```

---

## Task 13: Dispatch functions

**Files:**
- Create: `src/proj/dispatch.py`
- Test: `tests/test_dispatch.py`

Combines: column lookup + applies-when gating (shell) + variable interpolation + evaluator + type coercion + caching.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dispatch.py
from pathlib import Path

import pytest

from proj.cache import Cache
from proj.columns import ColumnRegistry, ColumnSpec, make_shell_evaluator
from proj.dispatch import Dispatcher
from proj.projects import Project, ProjectRegistry


@pytest.fixture
def project(tmp_path) -> Project:
    return Project(name="foo", path=tmp_path, tags=["mine"], vars={"host": "h1.tld"})


@pytest.fixture
def projects(project) -> ProjectRegistry:
    return ProjectRegistry({project.name: project}, project.path.parent)


@pytest.fixture
def cache(tmp_path) -> Cache:
    return Cache(tmp_path / "cache.db")


def test_get_value_uncached_column(projects, cache):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="foo", type="text",
        applies_to=None, applies_when=None, cache=False,
        value_from_template="echo bar", evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "foo") == "bar"


def test_get_value_caches_when_cache_true(projects, cache, tmp_path):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="counter", type="integer",
        applies_to=None, applies_when=None, cache=True,
        value_from_template="echo 1 > {{path}}/n && wc -l < {{path}}/n",
        evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    v1 = d.get_value("foo", "counter")
    v2 = d.get_value("foo", "counter")
    assert v1 == v2  # second call hits cache


def test_applies_when_false_returns_none(projects, cache):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="needs_lock", type="text",
        applies_to=None, applies_when="test -f impossible-marker",
        cache=False, value_from_template="echo present",
        evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "needs_lock") is None


def test_applies_when_true_runs_value_from(projects, cache, tmp_path):
    (tmp_path / "marker").write_text("")
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="x", type="text",
        applies_to=None, applies_when="test -f marker",
        cache=False, value_from_template="echo present",
        evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "x") == "present"


def test_interpolation_of_project_vars(projects, cache):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="hostname", type="text",
        applies_to=None, applies_when=None, cache=False,
        value_from_template="echo {{host}}",
        evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "hostname") == "h1.tld"


def test_get_applies_returns_1_with_no_applies_when(projects, cache):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="x", type="text",
        applies_to=None, applies_when=None, cache=False,
        value_from_template="echo ok", evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_applies("foo", "x") == 1


def test_get_applies_returns_0_when_shell_fails(projects, cache):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="x", type="text",
        applies_to=None, applies_when="false", cache=False,
        value_from_template="echo ok", evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_applies("foo", "x") == 0


def test_get_applies_caches(projects, cache, tmp_path):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="x", type="text",
        applies_to=None, applies_when="true", cache=False,
        value_from_template="echo ok", evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    a1 = d.get_applies("foo", "x")
    a2 = d.get_applies("foo", "x")
    assert a1 == a2 == 1


def test_type_coercion_applied(projects, cache):
    reg = ColumnRegistry()
    reg.register(ColumnSpec(
        name="n", type="integer",
        applies_to=None, applies_when=None, cache=False,
        value_from_template="echo 42",
        evaluator=make_shell_evaluator(),
    ))
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "n") == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dispatch.py -v`
Expected: ImportError on `proj.dispatch.Dispatcher`.

- [ ] **Step 3: Implement dispatch.py**

```python
# src/proj/dispatch.py
"""Dispatch functions: resolve column values and applicability per project."""

from __future__ import annotations

import logging
from typing import Any

from proj.cache import Cache
from proj.columns import ColumnRegistry, coerce_to_type, make_shell_evaluator
from proj.errors import UnknownColumnError, UnknownProjectError
from proj.interpolation import interpolate
from proj.projects import Project, ProjectRegistry

log = logging.getLogger(__name__)

_APPLIES_SHELL = make_shell_evaluator()


class Dispatcher:
    def __init__(self, columns: ColumnRegistry, projects: ProjectRegistry, cache: Cache) -> None:
        self.columns = columns
        self.projects = projects
        self.cache = cache

    def _project_vars(self, p: Project) -> dict[str, str]:
        return {
            **p.vars,
            "name": p.name,
            "path": str(p.path),
            "workspace_root": str(self.projects.workspace_root),
        }

    def get_applies(self, project_name: str, column_name: str) -> int:
        try:
            project = self.projects.get(project_name)
            spec = self.columns.get(column_name)
        except (UnknownProjectError, UnknownColumnError):
            return 0
        if spec.applies_when is None:
            return 1
        rendered = interpolate(spec.applies_when, self._project_vars(project))
        key = Cache.command_hash(rendered)
        cached = self.cache.lookup(project_name, f"{column_name}__applies", key)
        if cached is not None:
            return int(cached)
        result = _APPLIES_SHELL(rendered, project.path)
        applies = 1 if result is not None else 0
        self.cache.store(project_name, f"{column_name}__applies", key, applies)
        return applies

    def get_value(self, project_name: str, column_name: str) -> Any:
        try:
            project = self.projects.get(project_name)
            spec = self.columns.get(column_name)
        except (UnknownProjectError, UnknownColumnError):
            return None

        if self.get_applies(project_name, column_name) == 0:
            return None

        rendered = interpolate(spec.value_from_template or "", self._project_vars(project))
        key = Cache.command_hash(rendered) if spec.value_from_template else f"static:{column_name}"

        if spec.cache:
            cached = self.cache.lookup(project_name, column_name, key)
            if cached is not None:
                return cached

        try:
            raw = spec.evaluator(rendered, project.path)
        except Exception as e:
            log.warning("column %s on %s failed: %s", column_name, project_name, e)
            return None

        value = coerce_to_type(raw, spec.type)
        if spec.cache and value is not None:
            self.cache.store(project_name, column_name, key, value)
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dispatch.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/dispatch.py tests/test_dispatch.py
git commit -m "feat: dispatch functions with applies-when gating, interpolation, and caching"
```

---

## Task 14: SQL scalar helpers (gb, mb, kb, ago)

**Files:**
- Create: `src/proj/sql_funcs.py`
- Test: `tests/test_sql_funcs.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sql_funcs.py
import time

import pytest

from proj.sql_funcs import gb, mb, kb, ago


def test_kb():
    assert kb(1) == 1024
    assert kb(2) == 2048


def test_mb():
    assert mb(1) == 1024 * 1024


def test_gb():
    assert gb(1) == 1024 * 1024 * 1024


def test_ago_seconds():
    now = int(time.time())
    result = ago("60s", now=now)
    assert result == now - 60


def test_ago_minutes():
    now = 1_000_000
    assert ago("5m", now=now) == now - 5 * 60


def test_ago_hours():
    now = 1_000_000
    assert ago("3h", now=now) == now - 3 * 3600


def test_ago_days():
    now = 1_000_000
    assert ago("7d", now=now) == now - 7 * 86400


def test_ago_months():
    now = 1_000_000
    # 1 month = 30 days
    assert ago("2mo", now=now) == now - 2 * 30 * 86400


def test_ago_years():
    now = 1_000_000
    # 1 year = 365 days
    assert ago("1y", now=now) == now - 365 * 86400


def test_ago_invalid_format_raises():
    with pytest.raises(ValueError):
        ago("garbage")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sql_funcs.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/proj/sql_funcs.py
"""Scalar helper functions registered with SQLite."""

from __future__ import annotations

import re
import time


def kb(n: float) -> int:
    return int(n * 1024)


def mb(n: float) -> int:
    return int(n * 1024 * 1024)


def gb(n: float) -> int:
    return int(n * 1024 * 1024 * 1024)


_AGO_PATTERN = re.compile(r"^(\d+)(s|m|h|d|mo|y)$")
_AGO_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "mo": 30 * 86400,
    "y": 365 * 86400,
}


def ago(spec: str, now: int | None = None) -> int:
    """Return the Unix timestamp N units before now.

    Format: <digits><unit> where unit is s, m, h, d, mo, y.
    """
    m = _AGO_PATTERN.match(spec.strip())
    if not m:
        raise ValueError(f"invalid duration: {spec!r}")
    count, unit = int(m.group(1)), m.group(2)
    base = now if now is not None else int(time.time())
    return base - count * _AGO_UNITS[unit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sql_funcs.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/sql_funcs.py tests/test_sql_funcs.py
git commit -m "feat: SQL scalar helpers gb/mb/kb/ago"
```

---

## Task 15: SQLite schema construction

**Files:**
- Create: `src/proj/engine.py`
- Test: `tests/test_engine.py`

Build an in-memory SQLite table whose schema reflects the project and column registries: name + path + last_modified (cheap, eager), one INTEGER column per tag, then paired (`<name>`, `<name>_applies`) virtual columns for each non-tag registered column.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_engine.py
from pathlib import Path

import pytest

from proj.cache import Cache
from proj.columns import ColumnRegistry, ColumnSpec, make_shell_evaluator
from proj.builtins import register_cheap_builtins
from proj.dispatch import Dispatcher
from proj.engine import build_engine, Engine
from proj.projects import Project, ProjectRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "rust-proj").mkdir()
    (tmp_path / "rust-proj" / "Cargo.toml").write_text("")
    (tmp_path / "py-proj").mkdir()
    (tmp_path / "py-proj" / "pyproject.toml").write_text("")
    return tmp_path


@pytest.fixture
def projects(workspace) -> ProjectRegistry:
    return ProjectRegistry(
        {
            "rust-proj": Project("rust-proj", workspace / "rust-proj", ["mine", "library"], {}),
            "py-proj":   Project("py-proj",   workspace / "py-proj",   ["mine"], {}),
        },
        workspace,
    )


@pytest.fixture
def columns() -> ColumnRegistry:
    reg = ColumnRegistry()
    register_cheap_builtins(reg)
    return reg


@pytest.fixture
def engine(projects, columns, tmp_path):
    cache = Cache(tmp_path / "cache.db")
    dispatcher = Dispatcher(columns, projects, cache)
    return build_engine(projects, columns, dispatcher)


def test_engine_has_projects_table(engine):
    rows = engine.execute("SELECT name FROM projects ORDER BY name").fetchall()
    assert [r[0] for r in rows] == ["py-proj", "rust-proj"]


def test_tag_columns_populated(engine):
    rows = engine.execute("SELECT name, mine, library FROM projects ORDER BY name").fetchall()
    rows = {r[0]: (r[1], r[2]) for r in rows}
    assert rows["rust-proj"] == (1, 1)
    assert rows["py-proj"]   == (1, 0)


def test_language_columns_via_virtual_dispatch(engine):
    rows = engine.execute(
        "SELECT name, lang_rust, lang_python FROM projects ORDER BY name"
    ).fetchall()
    assert {r[0]: (r[1], r[2]) for r in rows} == {
        "py-proj":   (0, 1),
        "rust-proj": (1, 0),
    }


def test_applies_partner_present_for_cheap_columns(engine):
    rows = engine.execute("SELECT lang_rust_applies FROM projects").fetchall()
    # No applies-to/applies-when on lang_rust → always 1
    assert all(r[0] == 1 for r in rows)


def test_sql_funcs_available(engine):
    row = engine.execute("SELECT gb(1), mb(50), kb(1)").fetchone()
    assert row == (1024**3, 50 * 1024**2, 1024)


def test_filter_by_tag(engine):
    row = engine.execute("SELECT count(*) FROM projects WHERE mine").fetchone()
    assert row[0] == 2
    row = engine.execute("SELECT count(*) FROM projects WHERE library").fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement engine.py**

```python
# src/proj/engine.py
"""In-memory SQLite engine: schema construction and query execution."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from proj.columns import ColumnRegistry, ColumnSpec
from proj.dispatch import Dispatcher
from proj.projects import ProjectRegistry
from proj.sql_funcs import ago, gb, kb, mb


# Columns kept off the virtual-dispatch path: built into the projects table directly.
_EAGER_BUILTINS = {"last_modified"}


def _quote_ident(name: str) -> str:
    """Quote an identifier for SQL. Hyphens require quoting."""
    return '"' + name.replace('"', '""') + '"'


def _column_needs_quoting(name: str) -> bool:
    return not name.replace("_", "a").isalnum()


def _ref(name: str) -> str:
    """Render a column reference: quoted if needed."""
    return _quote_ident(name) if _column_needs_quoting(name) else name


class Engine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)


def build_engine(
    projects: ProjectRegistry,
    columns: ColumnRegistry,
    dispatcher: Dispatcher,
) -> Engine:
    """Build an in-memory SQLite database materialized from the registries."""
    conn = sqlite3.connect(":memory:")

    # Register scalar functions
    conn.create_function("gb", 1, gb)
    conn.create_function("mb", 1, mb)
    conn.create_function("kb", 1, kb)
    conn.create_function("ago", 1, ago)
    conn.create_function("get_column_value", 2, dispatcher.get_value)
    conn.create_function("get_column_applies", 2, dispatcher.get_applies)

    tag_set = sorted(projects.all_tags())
    virtual_cols = [
        spec for spec in columns
        if spec.name not in _EAGER_BUILTINS and spec.name != "unknown"
    ]

    # Build CREATE TABLE
    col_defs = [
        "name TEXT PRIMARY KEY",
        "path TEXT NOT NULL",
        "last_modified INTEGER",
        "unknown INTEGER DEFAULT 0",
    ]
    for t in tag_set:
        col_defs.append(f"{_ref(t)} INTEGER DEFAULT 0")
    for spec in virtual_cols:
        col_defs.extend(_virtual_col_defs(spec, tag_set))

    create_sql = "CREATE TABLE projects (\n  " + ",\n  ".join(col_defs) + "\n)"
    conn.execute(create_sql)

    # INSERT a row per project (eager values only)
    for project in projects:
        tag_values = [1 if t in project.tags else 0 for t in tag_set]
        last_mod = _eager_last_modified(project.path)
        cols = ["name", "path", "last_modified"] + [_ref(t) for t in tag_set]
        placeholders = ",".join(["?"] * len(cols))
        params = [project.name, str(project.path), last_mod] + tag_values
        conn.execute(
            f"INSERT INTO projects ({','.join(cols)}) VALUES ({placeholders})",
            params,
        )
    conn.commit()
    return Engine(conn)


def _eager_last_modified(path) -> int | None:
    try:
        mtimes = [int(p.stat().st_mtime) for p in path.iterdir() if p.is_file()]
        return max(mtimes) if mtimes else int(path.stat().st_mtime)
    except (OSError, FileNotFoundError):
        return None


def _sql_type(col_type: str) -> str:
    return {
        "text": "TEXT", "integer": "INTEGER", "boolean": "INTEGER", "real": "REAL",
    }[col_type]


def _virtual_col_defs(spec: ColumnSpec, tag_set: list[str]) -> list[str]:
    """Generate the (value, _applies) pair of virtual-column DEFs for a spec."""
    name_ref = _ref(spec.name)
    applies_ref = _ref(f"{spec.name}_applies")

    if spec.applies_to:
        # applies_to is a SQL expression referencing other columns (e.g., "oss" or "lang_elixir")
        gate = spec.applies_to
        applies_def = (
            f"{applies_ref} INTEGER GENERATED ALWAYS AS ("
            f"CASE WHEN {gate} THEN get_column_applies(name, '{spec.name}') ELSE 0 END"
            f") VIRTUAL"
        )
        value_def = (
            f"{name_ref} {_sql_type(spec.type)} GENERATED ALWAYS AS ("
            f"CASE WHEN {gate} THEN get_column_value(name, '{spec.name}') ELSE NULL END"
            f") VIRTUAL"
        )
    else:
        applies_def = (
            f"{applies_ref} INTEGER GENERATED ALWAYS AS ("
            f"get_column_applies(name, '{spec.name}')"
            f") VIRTUAL"
        )
        value_def = (
            f"{name_ref} {_sql_type(spec.type)} GENERATED ALWAYS AS ("
            f"get_column_value(name, '{spec.name}')"
            f") VIRTUAL"
        )
    # Applies column must come before value column referencing it? No — we don't reference it from value column.
    return [applies_def, value_def]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/engine.py tests/test_engine.py
git commit -m "feat: SQLite engine with paired virtual columns and registered scalar functions"
```

---

## Task 16: Output formatters

**Files:**
- Create: `src/proj/output.py`
- Test: `tests/test_output.py`

Render SQLite query results in three formats: `table` (rich), `json` (one JSON array of objects), `plain` (tab-separated, no header).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_output.py
import io
import json

import pytest

from proj.output import format_rows


def test_plain_format_outputs_tabs():
    out = io.StringIO()
    format_rows([("a", "b"), ("c", "d")], headers=["x", "y"], fmt="plain", file=out)
    assert out.getvalue() == "a\tb\nc\td\n"


def test_plain_format_handles_none():
    out = io.StringIO()
    format_rows([(None, 1)], headers=["x", "y"], fmt="plain", file=out)
    assert out.getvalue() == "\t1\n"


def test_json_format_emits_array_of_objects():
    out = io.StringIO()
    format_rows([(1, "a"), (2, "b")], headers=["id", "name"], fmt="json", file=out)
    data = json.loads(out.getvalue())
    assert data == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


def test_json_handles_none():
    out = io.StringIO()
    format_rows([(None, 1)], headers=["x", "y"], fmt="json", file=out)
    assert json.loads(out.getvalue()) == [{"x": None, "y": 1}]


def test_table_format_contains_headers_and_values():
    out = io.StringIO()
    format_rows([("a", "b")], headers=["X", "Y"], fmt="table", file=out)
    s = out.getvalue()
    assert "X" in s and "Y" in s and "a" in s and "b" in s


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        format_rows([], headers=[], fmt="bogus")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_output.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement output.py**

```python
# src/proj/output.py
"""Format query result rows for output."""

from __future__ import annotations

import json
import sys
from typing import Any, IO, Sequence

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
    data = [dict(zip(headers, row)) for row in rows]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_output.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/output.py tests/test_output.py
git commit -m "feat: table/json/plain output formatters"
```

---

## Task 17: Query builder

**Files:**
- Modify: `src/proj/engine.py` — add `build_query` helper
- Test: extend `tests/test_engine.py`

Translate `(input, where, order_by, group_by, limit)` to a valid SQL string. If `input` matches `^\s*select\s+`, treat it as a full statement and validate that no extra clauses were also passed. Else wrap as `SELECT <input> FROM projects ...`.

- [ ] **Step 1: Add failing tests**

```python
# Append to tests/test_engine.py
from proj.engine import build_query


def test_build_query_bare_cols():
    assert build_query("name, size") == "SELECT name, size FROM projects"


def test_build_query_with_where():
    assert build_query("name", where="mine") == "SELECT name FROM projects WHERE mine"


def test_build_query_with_order():
    assert build_query("name", order_by="size") == "SELECT name FROM projects ORDER BY size"


def test_build_query_with_limit():
    assert build_query("name", limit=5) == "SELECT name FROM projects LIMIT 5"


def test_build_query_with_group_by():
    assert build_query("lang, count(*)", group_by="lang") == \
        "SELECT lang, count(*) FROM projects GROUP BY lang"


def test_build_query_all_clauses():
    sql = build_query("name, size", where="mine", group_by=None, order_by="size desc", limit=10)
    assert sql == "SELECT name, size FROM projects WHERE mine ORDER BY size desc LIMIT 10"


def test_build_query_full_select_passes_through():
    sql = build_query("select name from projects where mine")
    assert sql == "select name from projects where mine"


def test_build_query_full_select_with_extra_clauses_raises():
    with pytest.raises(ValueError, match="full SELECT"):
        build_query("select name from projects", where="mine")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -k build_query -v`
Expected: ImportError on `build_query`.

- [ ] **Step 3: Implement**

```python
# Append to src/proj/engine.py
import re as _re

_SELECT_RE = _re.compile(r"^\s*select\s+", _re.IGNORECASE)


def build_query(
    input: str,
    where: str | None = None,
    group_by: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
) -> str:
    if _SELECT_RE.match(input):
        if where or group_by or order_by or limit:
            raise ValueError("full SELECT statement cannot be combined with --where/--order-by/--limit/--group-by")
        return input
    parts = [f"SELECT {input} FROM projects"]
    if where:
        parts.append(f"WHERE {where}")
    if group_by:
        parts.append(f"GROUP BY {group_by}")
    if order_by:
        parts.append(f"ORDER BY {order_by}")
    if limit is not None:
        parts.append(f"LIMIT {limit}")
    return " ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/engine.py tests/test_engine.py
git commit -m "feat: build_query translates flags to SQL"
```

---

## Task 18: Top-level builder

**Files:**
- Modify: `src/proj/engine.py` — add `build_from_manifest_path` convenience
- Test: extend `tests/test_engine.py`

Combines manifest load + registry setup + cache + dispatcher + engine into one call.

- [ ] **Step 1: Add failing test**

```python
# Append to tests/test_engine.py
import yaml

from proj.engine import build_from_manifest_path


def test_build_from_manifest_end_to_end(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo").mkdir()
    (workspace / "foo" / "Cargo.toml").write_text("")

    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(yaml.safe_dump({
        "workspace": {"root": str(workspace)},
        "projects": {"foo": {"tags": ["mine"]}},
    }))

    engine = build_from_manifest_path(manifest_path, cache_path=tmp_path / "cache.db")
    rows = engine.execute("SELECT name, lang_rust, mine FROM projects").fetchall()
    assert rows == [("foo", 1, 1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine.py -k build_from_manifest -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# Append to src/proj/engine.py
from pathlib import Path as _Path

from proj.builtins import register_cheap_builtins, register_expensive_builtins
from proj.cache import Cache as _Cache
from proj.columns import ColumnRegistry as _ColReg
from proj.columns import register_user_columns
from proj.dispatch import Dispatcher as _Dispatcher
from proj.manifest import load_manifest
from proj.projects import ProjectRegistry as _ProjReg


def build_from_manifest_path(manifest_path: _Path, cache_path: _Path) -> Engine:
    manifest = load_manifest(manifest_path)
    projects = _ProjReg.from_manifest(manifest)
    columns = _ColReg()
    register_cheap_builtins(columns)
    register_expensive_builtins(columns)
    register_user_columns(columns, manifest.columns)
    cache = _Cache(cache_path)
    dispatcher = _Dispatcher(columns, projects, cache)
    return build_engine(projects, columns, dispatcher)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/proj/engine.py tests/test_engine.py
git commit -m "feat: top-level build_from_manifest_path convenience"
```

---

## Task 19: CLI: replace stubs with working `query` command

**Files:**
- Modify: `src/proj/cli.py` (replace existing stubs)
- Modify: `tests/test_cli.py`

Drop the original stubs from Phase 1 of the project skeleton. Wire `proj query` to call into the engine. Keep `--help` working. Other commands (`list`, `run`, `status`, etc.) are deferred to follow-up plans; we'll remove them from the CLI here to avoid presenting non-functional commands.

- [ ] **Step 1: Update test_cli.py to reflect the new command surface**

Replace the whole file:

```python
# tests/test_cli.py
from pathlib import Path

import yaml
from click.testing import CliRunner

from proj import __version__
from proj.cli import main


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_query() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "query" in result.output


def _setup(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo").mkdir()
    (workspace / "foo" / "Cargo.toml").write_text("")
    (workspace / "bar").mkdir()
    (workspace / "bar" / "pyproject.toml").write_text("")
    manifest = tmp_path / "projects.yaml"
    manifest.write_text(yaml.safe_dump({
        "workspace": {"root": str(workspace)},
        "projects": {
            "foo": {"tags": ["mine"]},
            "bar": {"tags": ["mine", "library"]},
        },
    }))
    return manifest


def test_query_outputs_rows(tmp_path):
    manifest = _setup(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--manifest", str(manifest), "--cache-dir", str(tmp_path), "query",
         "name, lang_rust, mine", "--format", "plain"],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert set(lines) == {"foo\t1\t1", "bar\t0\t1"}


def test_query_with_where(tmp_path):
    manifest = _setup(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--manifest", str(manifest), "--cache-dir", str(tmp_path), "query",
         "name", "--where", "library", "--format", "plain"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "bar"


def test_query_json_output(tmp_path):
    import json
    manifest = _setup(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--manifest", str(manifest), "--cache-dir", str(tmp_path), "query",
         "name", "--where", "mine", "--format", "json", "--order-by", "name"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == [{"name": "bar"}, {"name": "foo"}]
```

- [ ] **Step 2: Replace cli.py**

```python
# src/proj/cli.py
"""Command-line entry point for proj."""

from __future__ import annotations

from pathlib import Path

import click

from proj import __version__
from proj.engine import build_from_manifest_path, build_query
from proj.output import format_rows
from proj.paths import cache_dir, config_path


@click.group()
@click.version_option(__version__, prog_name="proj")
@click.option(
    "--manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to projects.yaml (defaults to ~/.config/proj/projects.yaml).",
)
@click.option(
    "--cache-dir", type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Cache directory (defaults to ~/.cache/proj).",
)
@click.pass_context
def main(ctx: click.Context, manifest: Path | None, cache_dir: Path | None) -> None:
    """Manage a flat directory of heterogeneous projects."""
    ctx.ensure_object(dict)
    ctx.obj["manifest"] = manifest or config_path()
    ctx.obj["cache_dir"] = cache_dir or globals()["cache_dir"]()


@main.command()
@click.argument("input")
@click.option("--where", help="SQL WHERE clause.")
@click.option("--order-by", help="SQL ORDER BY clause.")
@click.option("--group-by", help="SQL GROUP BY clause.")
@click.option("--limit", type=int, help="SQL LIMIT.")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "plain"]), default="table")
@click.pass_context
def query(
    ctx: click.Context,
    input: str,
    where: str | None,
    order_by: str | None,
    group_by: str | None,
    limit: int | None,
    output_format: str,
) -> None:
    """Run a SQL query against the projects table."""
    manifest_path: Path = ctx.obj["manifest"]
    cdir: Path = ctx.obj["cache_dir"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")
    engine = build_from_manifest_path(manifest_path, cache_path=cdir / "cache.db")
    sql = build_query(input, where=where, order_by=order_by, group_by=group_by, limit=limit)
    try:
        cursor = engine.execute(sql)
    except Exception as e:
        raise click.ClickException(f"query failed: {e}") from e
    headers = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    format_rows(rows, headers, fmt=output_format)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run all CLI tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 4: Smoke test from command line**

Run:
```bash
mkdir -p /tmp/proj-smoke/ws/example
cd /tmp/proj-smoke/ws/example && touch Cargo.toml && cd -
cat > /tmp/proj-smoke/projects.yaml <<EOF
workspace:
  root: /tmp/proj-smoke/ws
projects:
  example:
    tags: [mine]
EOF
uv run proj --manifest /tmp/proj-smoke/projects.yaml --cache-dir /tmp/proj-smoke/cache query 'name, lang_rust, mine' --format plain
```
Expected: `example\t1\t1`

- [ ] **Step 5: Commit**

```bash
git add src/proj/cli.py tests/test_cli.py
git commit -m "feat: working proj query CLI with manifest and cache dir flags"
```

---

## Task 20: Integration test — user-defined columns end-to-end

**Files:**
- Create: `tests/test_query_integration.py`

Validates the whole stack with a manifest that defines a user column with `value-from`, `applies-to`, and a referenced project variable.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_query_integration.py
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from proj.cli import main


def write_manifest(path: Path, body: dict) -> None:
    path.write_text(yaml.safe_dump(body))


def setup_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "rusty").mkdir(parents=True)
    (ws / "rusty" / "Cargo.toml").write_text("")
    (ws / "rusty" / "README.md").write_text("# rusty")
    (ws / "pyish").mkdir()
    (ws / "pyish" / "pyproject.toml").write_text("")
    return ws


def test_user_column_with_applies_to(tmp_path):
    ws = setup_workspace(tmp_path)
    manifest = tmp_path / "projects.yaml"
    write_manifest(manifest, {
        "workspace": {"root": str(ws)},
        "projects": {
            "rusty": {"tags": ["mine"]},
            "pyish": {"tags": ["mine"]},
        },
        "columns": {
            "has_readme": {
                "applies-to": "lang_rust",
                "value-from": "test -f README.md && echo true || echo false",
                "type": "boolean",
            },
        },
    })
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--manifest", str(manifest), "--cache-dir", str(tmp_path),
         "query", "name, has_readme, has_readme_applies", "--order-by", "name", "--format", "plain"],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    # rusty applies (lang_rust=1) and has README → value 1
    # pyish does not apply (lang_rust=0) → applies=0, value=NULL (rendered as "")
    assert "pyish\t\t0" in lines
    assert "rusty\t1\t1" in lines


def test_user_column_with_project_var_interpolation(tmp_path):
    ws = setup_workspace(tmp_path)
    manifest = tmp_path / "projects.yaml"
    write_manifest(manifest, {
        "workspace": {"root": str(ws)},
        "projects": {
            "rusty": {"tags": ["mine"], "owner": "alice"},
            "pyish": {"tags": ["mine"], "owner": "bob"},
        },
        "columns": {
            "owner_echo": {
                "value-from": "echo {{owner}}",
                "type": "text",
            },
        },
    })
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--manifest", str(manifest), "--cache-dir", str(tmp_path),
         "query", "name, owner_echo", "--order-by", "name", "--format", "plain"],
    )
    assert result.exit_code == 0, result.output
    lines = sorted(result.output.strip().splitlines())
    assert lines == ["pyish\tbob", "rusty\talice"]


def test_user_column_with_applies_when(tmp_path):
    ws = setup_workspace(tmp_path)
    (ws / "rusty" / ".hgignore").write_text("foo\n")
    manifest = tmp_path / "projects.yaml"
    write_manifest(manifest, {
        "workspace": {"root": str(ws)},
        "projects": {
            "rusty": {"tags": ["mine"]},
            "pyish": {"tags": ["mine"]},
        },
        "columns": {
            "has_hg_foo": {
                "applies-when": "test -f .hgignore",
                "value-from": "grep -q foo .hgignore && echo true || echo false",
                "type": "boolean",
            },
        },
    })
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--manifest", str(manifest), "--cache-dir", str(tmp_path),
         "query", "name, has_hg_foo, has_hg_foo_applies", "--order-by", "name", "--format", "plain"],
    )
    assert result.exit_code == 0, result.output
    lines = sorted(result.output.strip().splitlines())
    assert lines == ["pyish\t\t0", "rusty\t1\t1"]
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/test_query_integration.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -v`
Expected: every test PASSES; if anything's red, fix before moving on.

- [ ] **Step 4: Run lint and format**

Run: `uv run ruff check && uv run ruff format`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_query_integration.py
git commit -m "test: integration coverage for user columns with applies-to, applies-when, and var interpolation"
```

---

## Task 21: README quickstart section

**Files:**
- Modify: `README.md`

Document the actual working subset (just `proj query` for now) so a new user can install and run something.

- [ ] **Step 1: Edit README.md**

Replace the "Quick start" section (and adjust the "Commands" table) with a `query`-centric quickstart that matches what's actually implemented. Drop or mark as "(coming soon)" the other commands. Keep the auto-detected properties and configuration sections.

Specifically update:
- `Quick start` section: example `projects.yaml` + a `proj query` command.
- `Commands` table: show only `proj query` as working; mark the rest as "coming soon" with a one-line description.

```markdown
## Quick start

Create a manifest at `~/.config/proj/projects.yaml`:

\`\`\`yaml
workspace:
  root: ~/projects

projects:
  my-cool-lib: { tags: [mine, library] }
  pandas-fork: { tags: [oss] }
  weekend-game: { tags: [mine, experiment] }
\`\`\`

Then query your workspace:

\`\`\`bash
proj query 'name, size, dirty' --where 'mine and lang_rust'
proj query 'name, last_modified' --where 'mine' --order-by 'last_modified desc'
proj query 'lang_rust, count(*)' --group-by lang_rust
\`\`\`

## Commands (v1)

| Command | Status | Purpose |
|---|---|---|
| `proj query` | ✓ working | Execute SQL against the projects table |
| `proj ls` / `status` / `clean` / `audit` / `archive` | coming soon | User-configurable commands shipped as defaults |
| `proj run` / `adopt` / `forget` / `new` | coming soon | Hardcoded primitives |
```

- [ ] **Step 2: Verify README renders sensibly**

Open in any markdown viewer or just `less README.md` — check that the quickstart is coherent and the command status is accurate.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README quickstart to reflect working proj query"
```

---

## Self-review

After implementing every task, walk through the spec sections and check coverage. Cross out lines below as you confirm:

- [x] Manifest loading: Task 3
- [x] Project registry + path override + vars: Task 4
- [x] Identifier normalization: Task 3
- [x] `_applies` suffix reservation: Task 3
- [x] Column registry, override semantics: Task 6
- [x] Type coercion + None-on-failure: Task 8
- [x] Built-in baseline (`name`, `path`, `last_modified`) + extended: Tasks 9, 10
- [x] User-defined columns via `value-from`: Task 12
- [x] Variable interpolation: Tasks 5, 13
- [x] Cache layer keyed by `(name, column, hash(rendered))`: Task 7, used in 13
- [x] Dispatch (`get_column_value` / `get_column_applies`): Task 13
- [x] `applies-to` baked into SQL CASE: Task 15
- [x] `applies-when` inside `get_column_applies`: Task 13
- [x] Paired `_applies` virtual columns: Task 15
- [x] SQLite engine schema construction: Task 15
- [x] Size/duration SQL helpers: Task 14
- [x] `build_query`: Task 17
- [x] Output formats: Task 16
- [x] CLI `proj query` end-to-end: Task 19
- [x] Integration tests: Task 20

**Out of scope (designed-for, not built here):**
- Commands as config + bundled defaults file + `proj defaults` command
- Grouped columns + marks + comparison expressions
- Mutating primitives (adopt, forget, new, archive)
- Unknown subdirectory detection (column exists but is constant 0)
- Auto-scoping based on cwd
- `--parallel`, `--summary`, `--dry-run`
- Templates
- `--all` / `--here` invocation context flags

These all build on the foundation this plan delivers and will get their own plans.
