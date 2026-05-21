# proj v2 — Commands as Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the hardcoded `proj query` into the broader command system. After this plan lands, `proj ls`, `proj status`, `proj clean`, `proj archive` work out of the box from a bundled `defaults.yaml`; users can override or add their own (`proj fmt`, `proj pull`) by editing `~/.config/proj/projects.yaml`. The `run` primitive executes shell commands per matching project. `proj forget` mutates the manifest; `proj defaults` shows the shipped file.

**Architecture:**
- Bundled YAML at `src/proj/defaults.yaml`, read at import-time via `importlib.resources`.
- Config merge: `defaults.yaml` → `~/.projrc` (optional) → workspace manifest (`~/.config/proj/projects.yaml`), entry-by-entry. CLI flags override anything per-invocation.
- New `Command` dataclass + registry, populated from the merged config.
- `cli.py` grows dynamic subcommand dispatch: hardcoded primitives (`query`, `run`, `adopt`, `forget`, `new`) are registered as click subcommands; everything else (`ls`, `status`, `clean`, `audit`, `archive`, `fmt`, ...) is resolved at click-invoke time against the merged command registry.
- `query`-type commands shell out to the existing `build_query` / engine path with their declared `columns`/`where`/`order_by`/`limit`.
- `run`-type commands iterate projects (filtered by `where`), interpolate `cmd` per-project, and shell out via `subprocess.run`. Exit code = number of project failures.

**Tech Stack:** Python 3.10+, existing deps. No new third-party libraries.

**Out of scope** (deferred to later plans):
- Grouped columns, marks, comparison expressions → Plan C
- `proj adopt` interactive flow → Plan D (this plan ships a no-op stub that errors with "not yet implemented")
- `proj new` and templates → Plan E (stub here too)
- `--parallel`, `--summary`, `--only-matches`, `--only-failures` → Plan F
- Auto-scoping based on cwd → Plan F
- Unknown-subdirectory detection → Plan D
- Progress indicator → Plan F

---

## File Structure

```
src/proj/
  defaults.yaml          # NEW: bundled defaults (ls, status, clean, archive, …)
  commands.py            # NEW: Command dataclass + registry + merge logic
  run.py                 # NEW: `run`-type execution (per-project shell loop)
  defaults_loader.py     # NEW: load bundled defaults.yaml via importlib.resources
  cli.py                 # CHANGED: dynamic command dispatch + new primitives
  manifest.py            # CHANGED: parse `commands:` section
  interpolation.py       # CHANGED (maybe): support {{column}} from row dict
  init.py                # (existing — leave alone)

tests/
  test_defaults.py       # NEW: defaults.yaml loads cleanly, contains expected keys
  test_commands.py       # NEW: Command parsing + merge precedence
  test_run.py            # NEW: run-type execution, dry-run, failure counting
  test_cli_commands.py   # NEW: end-to-end CLI invocation of bundled commands
  test_cli_forget.py     # NEW: forget primitive mutates manifest correctly
  test_cli_defaults.py   # NEW: `proj defaults` and `proj defaults --path`
```

`pyproject.toml`: add `"defaults.yaml"` to `[tool.hatch.build.targets.wheel]` package-data.

---

## Task 1: Bundled `defaults.yaml`

**Files:** `src/proj/defaults.yaml` (new), `src/proj/defaults_loader.py` (new), `tests/test_defaults.py` (new).

The file must be syntactically valid YAML parseable by the existing `load_manifest` schema (extended below for `commands:`). It contains **no `workspace:` or `projects:` section** — only `commands:` and (later in Plan C) `marks:`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_defaults.py
import yaml
from proj.defaults_loader import load_defaults, defaults_path


def test_defaults_path_exists():
    p = defaults_path()
    assert p.exists() and p.suffix == ".yaml"


def test_defaults_yaml_parses():
    data = load_defaults()
    assert isinstance(data, dict)
    assert "commands" in data


def test_bundled_commands_present():
    cmds = load_defaults()["commands"]
    for name in ("ls", "status", "clean", "archive"):
        assert name in cmds, f"missing bundled command {name}"


def test_ls_is_query_type_with_columns():
    ls = load_defaults()["commands"]["ls"]
    assert ls["type"] == "query"
    assert "name" in ls["columns"]


def test_clean_is_run_type():
    clean = load_defaults()["commands"]["clean"]
    assert clean["type"] == "run"
    assert "{{path}}" in clean["cmd"] or any("{{path}}" in c for c in clean["cmd"])
```

- [ ] **Step 2: Create `src/proj/defaults.yaml`**

```yaml
# Bundled defaults for proj. Merged before the user's manifest;
# any command redefined in ~/.config/proj/projects.yaml wins entry-by-entry.
# See: `proj defaults --path` to find this file on disk.

commands:
  ls:
    type: query
    columns: [name, last_modified]
    order_by: name

  status:
    type: query
    columns: [name, branch, dirty, ahead, behind, last_commit]
    where: git

  clean:
    type: run
    where: clean_target is not null
    cmd: "cd {{path}} && {{clean_target}}"

  archive:
    type: run
    cmd:
      - cd {{path}} && [ -n "{{clean_target}}" ] && {{clean_target}} || true
      - tar -C {{workspace_root}} -caf {{archive_dir}}/{{name}}.tar.zst {{name}}
      - rm -rf {{path}}
      - proj forget {{name}}
```

(Note: `ls` deliberately omits `tags` and `size` from the v2 default columns because tag listing and `size` formatting are Plan C concerns. Users can override.)

- [ ] **Step 3: Implement `defaults_loader.py`**

```python
"""Load the bundled defaults.yaml shipped inside the package."""
from __future__ import annotations
from importlib.resources import files
from pathlib import Path
from typing import Any
import yaml


def defaults_path() -> Path:
    return Path(str(files("proj").joinpath("defaults.yaml")))


def load_defaults() -> dict[str, Any]:
    return yaml.safe_load(defaults_path().read_text()) or {}
```

- [ ] **Step 4: Update `pyproject.toml`** to include the YAML file in the wheel:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/proj"]
include = ["src/proj/defaults.yaml"]
```

- [ ] **Step 5: Run tests** — all four pass; full suite still green.

---

## Task 2: `Command` dataclass and merged registry

**Files:** `src/proj/commands.py` (new), `tests/test_commands.py` (new), `src/proj/manifest.py` (extend).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_commands.py
import pytest
from proj.commands import (
    Command, QueryCommand, RunCommand, parse_commands, merge_commands, HARDCODED_PRIMITIVES,
)


def test_hardcoded_primitives_set():
    assert HARDCODED_PRIMITIVES == {"query", "run", "adopt", "forget", "new", "defaults", "init"}


def test_parse_query_command():
    cmds = parse_commands({"ls": {"type": "query", "columns": ["name"], "order_by": "name"}})
    assert isinstance(cmds["ls"], QueryCommand)
    assert cmds["ls"].columns == ["name"]
    assert cmds["ls"].order_by == "name"


def test_parse_run_command_string_cmd():
    cmds = parse_commands({"fmt": {"type": "run", "cmd": "just fmt"}})
    assert isinstance(cmds["fmt"], RunCommand)
    assert cmds["fmt"].cmds == ["just fmt"]


def test_parse_run_command_list_cmd():
    cmds = parse_commands({"big": {"type": "run", "cmd": ["a", "b"]}})
    assert cmds["big"].cmds == ["a", "b"]


def test_unknown_type_raises():
    with pytest.raises(ValueError, match="type"):
        parse_commands({"x": {"type": "weird", "cmd": "x"}})


def test_merge_overrides_by_name():
    defaults = parse_commands({"ls": {"type": "query", "columns": ["name"]}})
    user = parse_commands({"ls": {"type": "query", "columns": ["name", "path"]}})
    merged = merge_commands(defaults, user)
    assert merged["ls"].columns == ["name", "path"]


def test_merge_adds_new_user_commands():
    defaults = parse_commands({"ls": {"type": "query", "columns": ["name"]}})
    user = parse_commands({"fmt": {"type": "run", "cmd": "just fmt"}})
    merged = merge_commands(defaults, user)
    assert set(merged) == {"ls", "fmt"}


def test_cannot_redefine_hardcoded_primitive():
    with pytest.raises(ValueError, match="hardcoded"):
        parse_commands({"query": {"type": "run", "cmd": "x"}})
```

- [ ] **Step 2: Implement `commands.py`**

```python
"""Command definitions parsed from defaults.yaml + user manifest."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

HARDCODED_PRIMITIVES = {"query", "run", "adopt", "forget", "new", "defaults", "init"}


@dataclass(frozen=True)
class QueryCommand:
    name: str
    columns: list[str]
    where: str | None = None
    order_by: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class RunCommand:
    name: str
    cmds: list[str]                 # always a list internally
    where: str | None = None


Command = QueryCommand | RunCommand


def parse_commands(raw: dict[str, Any] | None) -> dict[str, Command]:
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
            )
        elif t == "run":
            cmd = body.get("cmd")
            if cmd is None:
                raise ValueError(f"command {name!r}: run needs 'cmd'")
            cmds = [cmd] if isinstance(cmd, str) else list(cmd)
            out[name] = RunCommand(name=name, cmds=cmds, where=body.get("where"))
        else:
            raise ValueError(f"command {name!r}: unknown type {t!r}")
    return out


def merge_commands(
    defaults: dict[str, Command],
    user: dict[str, Command],
) -> dict[str, Command]:
    merged = dict(defaults)
    merged.update(user)
    return merged
```

- [ ] **Step 3: Extend `manifest.py`** to expose raw `commands:` block on the `Manifest`:

```python
# in manifest.py
@dataclass(frozen=True)
class Manifest:
    workspace_root: Path
    projects: dict[str, ProjectEntry]
    columns: dict[str, ColumnEntry]
    settings: dict[str, Any]
    raw_commands: dict[str, Any] = field(default_factory=dict)   # NEW

# inside load_manifest():
raw_commands = data.get("commands") or {}
if not isinstance(raw_commands, dict):
    raise ManifestError("'commands' must be a mapping")
return Manifest(..., raw_commands=raw_commands)
```

Tests for manifest extension go in `test_manifest.py` (add 1-2 cases).

- [ ] **Step 4: Run tests** — all pass; full suite green.

---

## Task 3: `proj defaults` command

**Files:** `src/proj/cli.py` (extend), `tests/test_cli_defaults.py` (new).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_defaults.py
from click.testing import CliRunner
from proj.cli import main


def test_defaults_prints_yaml():
    r = CliRunner().invoke(main, ["defaults"])
    assert r.exit_code == 0
    assert "commands:" in r.output
    assert "ls:" in r.output


def test_defaults_path_prints_absolute():
    r = CliRunner().invoke(main, ["defaults", "--path"])
    assert r.exit_code == 0
    out = r.output.strip()
    assert out.endswith("defaults.yaml")
    from pathlib import Path
    assert Path(out).is_absolute()
```

- [ ] **Step 2: Add `defaults` subcommand to `cli.py`**

```python
@main.command()
@click.option("--path", "show_path", is_flag=True, help="Print the file path instead of contents.")
def defaults(show_path: bool) -> None:
    """Print the bundled defaults.yaml (or its path)."""
    from proj.defaults_loader import defaults_path
    if show_path:
        click.echo(str(defaults_path()))
    else:
        click.echo(defaults_path().read_text(), nl=False)
```

- [ ] **Step 3: Run tests.**

---

## Task 4: `proj run` primitive

**Files:** `src/proj/run.py` (new), `tests/test_run.py` (new), `src/proj/cli.py` (extend), `src/proj/interpolation.py` (extend if needed).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_run.py
from pathlib import Path
import yaml
from click.testing import CliRunner
from proj.cli import main


def _setup(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo").mkdir()
    (ws / "bar").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({
        "workspace": {"root": str(ws)},
        "projects": {"foo": {"tags": ["mine"]}, "bar": {"tags": []}},
    }))
    return m


def test_run_executes_per_project(tmp_path):
    m = _setup(tmp_path)
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "run", "touch marker",
    ])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_where_filters(tmp_path):
    m = _setup(tmp_path)
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "run", "touch marker", "--where", "mine",
    ])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert not (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_dry_run_prints_without_executing(tmp_path):
    m = _setup(tmp_path)
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "run", "touch marker", "--dry-run",
    ])
    assert r.exit_code == 0
    assert "touch marker" in r.output
    assert not (tmp_path / "ws" / "foo" / "marker").exists()


def test_run_exit_code_counts_failures(tmp_path):
    m = _setup(tmp_path)
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "run", "false",
    ])
    assert r.exit_code == 2  # both projects failed


def test_run_interpolates_path_and_name(tmp_path):
    m = _setup(tmp_path)
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "run", "echo {{name}} > out", "--where", "mine",
    ])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "out").read_text().strip() == "foo"
```

- [ ] **Step 2: Implement `run.py`**

```python
"""Per-project execution of `run`-type commands."""
from __future__ import annotations
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from proj.engine import Engine
from proj.interpolation import interpolate


@dataclass
class RunResult:
    name: str
    cmd: str
    returncode: int
    stdout: str
    stderr: str


def select_projects(
    engine: Engine,
    where: str | None,
) -> list[tuple[str, str]]:
    sql = "SELECT name, path FROM projects"
    if where:
        sql += f" WHERE {where}"
    return [(name, path) for name, path in engine.execute(sql).fetchall()]


def render_cmds(
    cmds: list[str],
    project_name: str,
    project_path: str,
    workspace_root: Path,
    archive_dir: str,
    extra: dict[str, str] | None = None,
) -> list[str]:
    base = {
        "name": project_name,
        "path": project_path,
        "workspace_root": str(workspace_root),
        "archive_dir": archive_dir,
    }
    if extra:
        base.update(extra)
    return [interpolate(c, base) for c in cmds]


def execute_run(
    engine: Engine,
    cmds: list[str],
    where: str | None,
    workspace_root: Path,
    archive_dir: str,
    dry_run: bool,
) -> int:
    """Returns: number of project failures (suitable as process exit code)."""
    failures = 0
    for name, path in select_projects(engine, where):
        rendered = render_cmds(cmds, name, path, workspace_root, archive_dir)
        if dry_run:
            for c in rendered:
                print(f"[{name}] {c}")
            continue
        project_failed = False
        for c in rendered:
            result = subprocess.run(
                ["sh", "-c", c], cwd=path, text=True
            )
            if result.returncode != 0:
                project_failed = True
                print(f"[{name}] FAILED ({result.returncode}): {c}", file=sys.stderr)
                break  # halt this project's remaining cmds
        if project_failed:
            failures += 1
    return failures
```

- [ ] **Step 3: Wire up `run` primitive in `cli.py`**

```python
@main.command()
@click.argument("cmd")
@click.option("--where", default=None)
@click.option("--dry-run", is_flag=True)
@click.pass_context
def run(ctx, cmd, where, dry_run):
    """Run a shell command per matching project."""
    from proj.run import execute_run
    from proj.engine import build_from_manifest_path
    from proj.manifest import load_manifest

    manifest_path = ctx.obj["manifest"]
    if not manifest_path.exists():
        raise click.UsageError(f"manifest not found: {manifest_path}")
    m = load_manifest(manifest_path)
    engine = build_from_manifest_path(manifest_path, cache_path=ctx.obj["cache_dir"] / "cache.db")
    archive_dir = m.settings.get("archive_dir", "_archive")
    failures = execute_run(engine, [cmd], where, m.workspace_root, archive_dir, dry_run)
    ctx.exit(failures)
```

- [ ] **Step 4: Run tests** — all pass.

---

## Task 5: `proj forget` primitive

**Files:** `src/proj/cli.py` (extend), `tests/test_cli_forget.py` (new).

For v2, use plain `pyyaml` (does not preserve comments). Roadmap note: when `proj adopt` lands in Plan D, both `adopt` and `forget` should be migrated to `ruamel.yaml` together to preserve manifest formatting.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_forget.py
from pathlib import Path
import yaml
from click.testing import CliRunner
from proj.cli import main


def test_forget_removes_entry(tmp_path: Path):
    ws = tmp_path / "ws"; ws.mkdir(); (ws / "foo").mkdir(); (ws / "bar").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({
        "workspace": {"root": str(ws)},
        "projects": {"foo": {"tags": ["mine"]}, "bar": {"tags": []}},
    }))
    r = CliRunner().invoke(main, ["--manifest", str(m), "forget", "foo"])
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(m.read_text())
    assert "foo" not in data["projects"]
    assert "bar" in data["projects"]


def test_forget_unknown_errors(tmp_path: Path):
    ws = tmp_path / "ws"; ws.mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({"workspace": {"root": str(ws)}, "projects": {}}))
    r = CliRunner().invoke(main, ["--manifest", str(m), "forget", "ghost"])
    assert r.exit_code != 0
    assert "ghost" in r.output
```

- [ ] **Step 2: Implement `forget` in `cli.py`** (read YAML, pop key, write back).

- [ ] **Step 3: Tests pass.**

---

## Task 6: User-overridable commands wired into CLI

**Files:** `src/proj/cli.py` (substantial change), `tests/test_cli_commands.py` (new).

The challenge: click's `Group` resolves subcommands eagerly. For dynamic dispatch, override `Group.get_command(ctx, name)` so that a name not matching a built-in subcommand falls through to a "user command" resolver that loads the merged registry and dispatches a synthesized click command.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_commands.py
from pathlib import Path
import yaml
from click.testing import CliRunner
from proj.cli import main


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"; ws.mkdir(); (ws / "foo").mkdir(); (ws / "bar").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({
        "workspace": {"root": str(ws)},
        "projects": {"foo": {"tags": ["mine"]}, "bar": {"tags": []}},
    }))
    return m


def test_bundled_ls_runs(tmp_path):
    m = _ws(tmp_path)
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "ls", "--format", "plain",
    ])
    assert r.exit_code == 0, r.output
    names = {line.split("\t", 1)[0] for line in r.output.strip().splitlines()}
    assert names == {"foo", "bar"}


def test_user_run_command_overrides_or_adds(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir(); (ws / "foo").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({
        "workspace": {"root": str(ws)},
        "projects": {"foo": {"tags": []}},
        "commands": {"touch_it": {"type": "run", "cmd": "touch marker"}},
    }))
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "touch_it",
    ])
    assert r.exit_code == 0, r.output
    assert (ws / "foo" / "marker").exists()


def test_user_query_override_of_ls(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir(); (ws / "foo").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({
        "workspace": {"root": str(ws)},
        "projects": {"foo": {"tags": ["mine"]}},
        "commands": {"ls": {"type": "query", "columns": ["name", "mine"]}},
    }))
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "ls", "--format", "plain",
    ])
    assert r.exit_code == 0, r.output
    assert "foo\t1" in r.output
```

- [ ] **Step 2: Implement dynamic dispatch in `cli.py`**

Subclass `click.Group`:

```python
class ProjGroup(click.Group):
    def get_command(self, ctx, name):
        cmd = super().get_command(ctx, name)
        if cmd is not None:
            return cmd
        # Fall through to user/bundled commands from merged registry.
        return _resolve_user_command(ctx, name)
```

`_resolve_user_command`:
1. Resolve manifest path (CLI flag or default).
2. If manifest doesn't exist, return None (let click 404).
3. Load defaults + user commands; merge.
4. If name not in merged, return None.
5. Build a click command on-the-fly that, when invoked, executes the resolved `QueryCommand` or `RunCommand`.

```python
def _resolve_user_command(ctx, name):
    manifest_path = ctx.obj["manifest"] if ctx.obj else default_config_path()
    if not manifest_path.exists():
        return None
    from proj.commands import parse_commands, merge_commands, QueryCommand, RunCommand
    from proj.defaults_loader import load_defaults
    from proj.manifest import load_manifest
    defaults = parse_commands(load_defaults().get("commands"))
    user_m = load_manifest(manifest_path)
    user_cmds = parse_commands(user_m.raw_commands)
    merged = merge_commands(defaults, user_cmds)
    if name not in merged:
        return None
    spec = merged[name]
    if isinstance(spec, QueryCommand):
        return _make_query_click(spec)
    return _make_run_click(spec)
```

`_make_query_click(spec)` returns a `click.Command` whose callback builds a SELECT from `spec.columns` (joined with comma), merges `--where`/`--order-by` flags AND-style with `spec.where`/`spec.order_by`, calls the engine, formats output.

`_make_run_click(spec)` returns a `click.Command` accepting `--where`, `--dry-run` flags; calls `execute_run(engine, spec.cmds, merge_where(spec.where, cli_where), ..., dry_run)`.

`merge_where(a, b)` returns `None` if both None, else parenthesized `AND`.

- [ ] **Step 3: Run tests** — all pass.

---

## Task 7: `adopt` and `new` stubs

**Files:** `src/proj/cli.py` (extend), `tests/test_cli_stubs.py` (new).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_stubs.py
from click.testing import CliRunner
from proj.cli import main


def test_adopt_stub_errors_with_not_implemented():
    r = CliRunner().invoke(main, ["adopt", "foo"])
    assert r.exit_code != 0
    assert "not yet implemented" in r.output.lower()


def test_new_stub_errors_with_not_implemented():
    r = CliRunner().invoke(main, ["new", "python-uv", "exp"])
    assert r.exit_code != 0
    assert "not yet implemented" in r.output.lower()
```

- [ ] **Step 2: Add stubs to `cli.py`** that exit with `ClickException("not yet implemented (see Plans D/E)")`.

- [ ] **Step 3: Tests pass.**

---

## Task 8: Final integration

- [ ] Run the full test suite.
- [ ] Run `uv run ruff format` and `uv run ruff check`.
- [ ] Manually smoke-test:
  - `proj init <tmpdir>` → creates manifest
  - `proj ls --format plain` → lists projects from manifest
  - `proj run 'echo hi'` → runs in each project
  - `proj defaults` → prints YAML
  - `proj defaults --path` → prints file path
- [ ] Update `README.md` quickstart with `proj init` + `proj ls` example.
- [ ] Update `docs/superpowers/ROADMAP.md` to mark Plan B as shipped.

---

## Risk Notes

- **Dynamic click dispatch** is the only architectural risk. The `Group.get_command` override pattern is documented in click's docs and is the canonical solution; the indirection cost is one extra function call per CLI invocation.
- **Merged config loading happens per CLI invocation**, including for `--help` and for unknown subcommands. If this becomes painful (e.g., user has 200 projects and YAML parse is slow), cache the merged config inside `ctx.obj`. Not needed for v2 ship.
- **`raw_commands` on Manifest** is intentionally raw (dicts) rather than parsed (`Command` objects) so the `Manifest` dataclass doesn't depend on the command system. Parsing happens in the dispatch layer.
