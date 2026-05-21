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
    value_from: str | None
    applies_to: str | None
    applies_when: str | None
    cache: bool


@dataclass(frozen=True)
class Manifest:
    workspace_root: Path
    projects: dict[str, ProjectEntry]
    columns: dict[str, ColumnEntry]
    settings: dict[str, Any]
    raw_commands: dict[str, Any] = field(default_factory=dict)
    raw_marks: dict[str, Any] = field(default_factory=dict)
    raw_templates: dict[str, Any] = field(default_factory=dict)


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
        raise ReservedNameError(f"column {name!r}: names ending in _applies are reserved")
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

    raw_projects = data.get("projects") or {}
    if not isinstance(raw_projects, dict):
        raise ManifestError("'projects' must be a mapping")
    projects: dict[str, ProjectEntry] = {}
    for pname, praw in raw_projects.items():
        projects[pname] = _parse_project(pname, praw)

    raw_columns = data.get("columns") or {}
    if not isinstance(raw_columns, dict):
        raise ManifestError("'columns' must be a mapping")
    columns: dict[str, ColumnEntry] = {}
    for cname, craw in raw_columns.items():
        columns[cname] = _parse_column(cname, craw)

    settings = dict(data.get("settings") or {})

    raw_commands = data.get("commands") or {}
    if not isinstance(raw_commands, dict):
        raise ManifestError("'commands' must be a mapping")

    raw_marks = data.get("marks") or {}
    if not isinstance(raw_marks, dict):
        raise ManifestError("'marks' must be a mapping")

    raw_templates = data.get("templates") or {}
    if not isinstance(raw_templates, dict):
        raise ManifestError("'templates' must be a mapping")

    return Manifest(
        workspace_root=workspace_root,
        projects=projects,
        columns=columns,
        settings=settings,
        raw_commands=raw_commands,
        raw_marks=raw_marks,
        raw_templates=raw_templates,
    )
