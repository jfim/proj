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
