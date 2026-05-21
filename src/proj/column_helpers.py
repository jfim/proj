"""Logic for the few built-in columns that are awkward in shell.

Invoked from defaults.yaml as ``proj-col <name>``; the helper inspects ``$PWD``
and prints the column value to stdout. Lives here (rather than as a shell
one-liner) because the logic either needs portable byte counting or branchy
package-manager probing that's ugly inline.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path


def column_size(cwd: Path) -> int | None:
    """Total bytes in cwd, recursive. Returns None on failure."""
    if not cwd.exists():
        return None
    total = 0
    try:
        for p in cwd.rglob("*"):
            if p.is_file():
                with contextlib.suppress(OSError):
                    total += p.stat().st_size
    except OSError:
        return None
    return total


def column_clean_target(cwd: Path) -> str | None:
    """Auto-detect the project's clean command. Order: justfile, Makefile, Cargo, npm, gradle."""
    if (cwd / "justfile").exists() and "clean" in (cwd / "justfile").read_text():
        return "just clean"
    if (cwd / "Makefile").exists() and "clean" in (cwd / "Makefile").read_text():
        return "make clean"
    if (cwd / "Cargo.toml").exists():
        return "cargo clean"
    pkg = cwd / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            if "clean" in (data.get("scripts") or {}):
                return "npm run clean"
        except (json.JSONDecodeError, OSError):
            pass
    if (cwd / "build.gradle").exists() or (cwd / "build.gradle.kts").exists():
        return "./gradlew clean"
    return None


_HELPERS = {
    "size": column_size,
    "clean_target": column_clean_target,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in _HELPERS:
        names = ", ".join(sorted(_HELPERS))
        print(f"usage: proj-col <{names}>", file=sys.stderr)
        return 2
    value = _HELPERS[args[0]](Path.cwd())
    if value is not None:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
