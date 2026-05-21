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
