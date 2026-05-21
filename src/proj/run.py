"""Per-project execution of `run`-type commands."""

from __future__ import annotations

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import click

from proj.engine import Engine, _ref
from proj.interpolation import interpolate
from proj.projects import ProjectRegistry

_VAR_RE = re.compile(r"\{\{([\w-]+)\}\}")
_BUILTIN_VARS = {"name", "path", "workspace_root", "archive_dir"}


def merge_where(a: str | None, b: str | None) -> str | None:
    """AND-combine two optional SQL WHERE clauses."""
    if a and b:
        return f"({a}) AND ({b})"
    return a or b


def select_projects(engine: Engine, where: str | None) -> list[tuple[str, str]]:
    """Return [(name, path), ...] for projects matching `where`."""
    sql = "SELECT name, path FROM projects"
    if where:
        sql += f" WHERE {where}"
    return [(name, path) for name, path in engine.execute(sql).fetchall()]


def _extract_column_refs(cmds: list[str], project_vars: set[str]) -> list[str]:
    """Names referenced by `{{var}}` that aren't built-ins or per-project vars."""
    refs: list[str] = []
    seen: set[str] = set()
    for cmd in cmds:
        for m in _VAR_RE.finditer(cmd):
            name = m.group(1)
            if name in _BUILTIN_VARS or name in project_vars or name in seen:
                continue
            seen.add(name)
            refs.append(name)
    return refs


def _column_values(engine: Engine, project_name: str, column_names: list[str]) -> dict[str, str]:
    """Fetch column values for a single project; coerce None to empty string."""
    if not column_names:
        return {}
    select = ", ".join(_ref(c) for c in column_names)
    row = engine.execute(
        f"SELECT {select} FROM projects WHERE name = ?", (project_name,)
    ).fetchone()
    if row is None:
        return {}
    return {
        name: "" if value is None else str(value)
        for name, value in zip(column_names, row, strict=False)
    }


def render_cmds(
    cmds: list[str],
    project_name: str,
    project_path: str,
    workspace_root: Path,
    archive_dir: str,
    extra_vars: dict[str, str] | None = None,
) -> list[str]:
    """Interpolate built-in vars + any extra (column or project) vars."""
    vars_ = {
        "name": project_name,
        "path": project_path,
        "workspace_root": str(workspace_root),
        "archive_dir": archive_dir,
    }
    if extra_vars:
        vars_.update(extra_vars)
    return [interpolate(c, vars_) for c in cmds]


@dataclass
class ProjectRunResult:
    name: str
    failed_step: int  # -1 means all succeeded
    failed_cmd: str | None
    returncode: int


def _run_one_project(
    name: str,
    path: str,
    cmds: list[str],
    engine: Engine,
    workspace_root: Path,
    archive_dir: str,
    project_registry: ProjectRegistry | None,
    dry_run: bool,
) -> ProjectRunResult:
    project = project_registry.get(name) if project_registry else None
    project_vars = dict(project.vars) if project else {}

    column_refs = _extract_column_refs(cmds, set(project_vars))
    extra_vars: dict[str, str] = {}
    extra_vars.update(project_vars)
    extra_vars.update(_column_values(engine, name, column_refs))

    try:
        rendered = render_cmds(cmds, name, path, workspace_root, archive_dir, extra_vars=extra_vars)
    except KeyError as e:
        click.echo(f"[{name}] interpolation error: {e}", err=True)
        return ProjectRunResult(name=name, failed_step=0, failed_cmd=None, returncode=1)

    if dry_run:
        for c in rendered:
            click.echo(f"[{name}] {c}")
        return ProjectRunResult(name=name, failed_step=-1, failed_cmd=None, returncode=0)

    for i, c in enumerate(rendered):
        result = subprocess.run(["sh", "-c", c], cwd=path, text=True)
        if result.returncode != 0:
            click.echo(f"[{name}] FAILED ({result.returncode}): {c}", err=True)
            return ProjectRunResult(
                name=name, failed_step=i, failed_cmd=c, returncode=result.returncode
            )
    return ProjectRunResult(name=name, failed_step=-1, failed_cmd=None, returncode=0)


def execute_run(
    engine: Engine,
    cmds: list[str],
    where: str | None,
    workspace_root: Path,
    archive_dir: str,
    dry_run: bool,
    project_registry: ProjectRegistry | None = None,
    parallel: bool = False,
    summary: bool = False,
) -> int:
    """Execute `cmds` per matching project. Returns number of failures."""
    selected = select_projects(engine, where)

    if parallel and not dry_run and len(selected) > 1:
        results: list[ProjectRunResult] = []
        with ThreadPoolExecutor(max_workers=min(len(selected), 8)) as pool:
            futures = {
                pool.submit(
                    _run_one_project,
                    name,
                    path,
                    cmds,
                    engine,
                    workspace_root,
                    archive_dir,
                    project_registry,
                    dry_run,
                ): name
                for name, path in selected
            }
            for fut in as_completed(futures):
                results.append(fut.result())
    else:
        results = [
            _run_one_project(
                name,
                path,
                cmds,
                engine,
                workspace_root,
                archive_dir,
                project_registry,
                dry_run,
            )
            for name, path in selected
        ]

    if summary and not dry_run:
        _print_summary(results)

    return sum(1 for r in results if r.failed_step >= 0)


def _print_summary(results: list[ProjectRunResult]) -> None:
    """Compact pass/fail table."""
    if not results:
        return
    width = max(len(r.name) for r in results)
    click.echo("")
    for r in sorted(results, key=lambda x: x.name):
        status = "PASS" if r.failed_step < 0 else f"FAIL (step {r.failed_step + 1})"
        click.echo(f"  {r.name.ljust(width)}  {status}")
    failed = sum(1 for r in results if r.failed_step >= 0)
    click.echo(f"\n{len(results) - failed} passed, {failed} failed")
