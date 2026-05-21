"""Visual marks for grouped-column cells."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Mark:
    prefix: str = ""
    suffix: str = ""
    color: str = ""


BUNDLED_MARKS: dict[str, Mark] = {
    "mark-good": Mark(prefix="✓ ", suffix="", color="green"),
    "mark-bad": Mark(prefix="✗ ", suffix="", color="red"),
    "mark-warn": Mark(prefix="⚠ ", suffix="", color="yellow"),
    "mark-ignored": Mark(prefix="", suffix=" (ignored)", color="grey50"),
}

_FIELDS = ("prefix", "suffix", "color")


def parse_marks(raw: dict[str, Any] | None) -> dict[str, Mark]:
    """Parse a `marks:` mapping into Mark objects."""
    if not raw:
        return {}
    out: dict[str, Mark] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"mark {name!r}: must be a mapping")
        for f in _FIELDS:
            if f in body and not isinstance(body[f], str):
                raise ValueError(f"mark {name!r}: {f} must be a string")
        out[name] = Mark(
            prefix=body.get("prefix", ""),
            suffix=body.get("suffix", ""),
            color=body.get("color", ""),
        )
    return out


def merge_marks(defaults: dict[str, Mark], user: dict[str, Mark]) -> dict[str, Mark]:
    """Whole-record override per spec — user wins, no field merging."""
    merged = dict(defaults)
    merged.update(user)
    return merged
