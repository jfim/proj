"""Round-tripping manifest edits that preserve comments and ordering.

Used by mutating primitives (`proj adopt`, `proj forget`). Backed by ruamel.yaml.
Read-only consumers should use `proj.manifest.load_manifest` (pyyaml-backed)
instead — it's faster and the manifest module doesn't depend on ruamel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def load_for_edit(path: Path) -> Any:
    """Load a manifest YAML preserving comments and ordering."""
    with open(path) as f:
        return _yaml.load(f) or {}


def dump_after_edit(path: Path, data: Any) -> None:
    """Write data back to the manifest path, preserving formatting where possible."""
    with open(path, "w") as f:
        _yaml.dump(data, f)


def add_project(data: Any, name: str, tags: list[str]) -> None:
    """Insert a project entry into the manifest data (mutating)."""
    if "projects" not in data or data["projects"] is None:
        data["projects"] = {}
    if name in data["projects"]:
        raise KeyError(f"project {name!r} already declared in manifest")
    data["projects"][name] = {"tags": list(tags)}


def remove_project(data: Any, name: str) -> None:
    """Remove a project entry (mutating)."""
    projects = data.get("projects") or {}
    if name not in projects:
        raise KeyError(f"project {name!r} not declared in manifest")
    del projects[name]
