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


def projrc_path() -> Path | None:
    """Return ~/.projrc if it exists, else None."""
    p = Path.home() / ".projrc"
    return p if p.exists() else None


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
