"""Mustache-style {{var}} substitution for shell command strings."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"\{\{([\w-]+)\}\}")


def interpolate(template: str, vars: dict[str, str]) -> str:
    """Substitute {{key}} occurrences in template with vars[key].

    Raises KeyError if a referenced variable is missing.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in vars:
            raise KeyError(f"missing variable: {{{{ {key} }}}}")
        return vars[key]

    return _PATTERN.sub(replace, template)
