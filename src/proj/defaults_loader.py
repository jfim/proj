"""Load the bundled defaults.yaml shipped inside the package."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from proj.manifest import ColumnEntry, parse_columns


def defaults_path() -> Path:
    return Path(str(files("proj").joinpath("defaults.yaml")))


def load_defaults() -> dict[str, Any]:
    return yaml.safe_load(defaults_path().read_text()) or {}


def load_default_columns() -> dict[str, ColumnEntry]:
    """Parse the `columns:` block of the bundled defaults.yaml."""
    return parse_columns(load_defaults().get("columns") or {})
