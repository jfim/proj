"""Templates for `proj new`."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from proj.interpolation import interpolate


@dataclass(frozen=True)
class Template:
    name: str
    tags: list[str]
    cmds: list[str]


def parse_templates(raw: dict[str, Any] | None) -> dict[str, Template]:
    if not raw:
        return {}
    out: dict[str, Template] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"template {name!r}: must be a mapping")
        tags = body.get("tags") or []
        if not isinstance(tags, list):
            raise ValueError(f"template {name!r}: tags must be a list")
        cmds = body.get("cmds")
        if not isinstance(cmds, list) or not cmds:
            raise ValueError(f"template {name!r}: cmds must be a non-empty list")
        out[name] = Template(
            name=name,
            tags=[str(t) for t in tags],
            cmds=[str(c) for c in cmds],
        )
    return out


@dataclass
class StepResult:
    cmd: str
    returncode: int


def render_template_cmds(cmds: list[str], project_name: str, workspace_root: Path) -> list[str]:
    vars_ = {
        "name": project_name,
        "workspace_root": str(workspace_root),
        "date": date.today().isoformat(),
    }
    return [interpolate(c, vars_) for c in cmds]


def run_template(
    template: Template,
    project_name: str,
    workspace_root: Path,
    dry_run: bool = False,
) -> tuple[int, list[StepResult]]:
    """Run template cmds sequentially from `workspace_root`. Stops on first failure.

    Returns (failing_step_index_or_-1, step_results). -1 means all steps succeeded.
    """
    rendered = render_template_cmds(template.cmds, project_name, workspace_root)
    results: list[StepResult] = []
    for i, cmd in enumerate(rendered):
        if dry_run:
            results.append(StepResult(cmd=cmd, returncode=0))
            continue
        proc = subprocess.run(["sh", "-c", cmd], cwd=workspace_root, text=True)
        results.append(StepResult(cmd=cmd, returncode=proc.returncode))
        if proc.returncode != 0:
            return i, results
    return -1, results
