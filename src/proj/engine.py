"""In-memory SQLite engine: schema construction and query execution."""

from __future__ import annotations

import sqlite3

from proj.columns import ColumnRegistry, ColumnSpec
from proj.dispatch import Dispatcher
from proj.projects import ProjectRegistry
from proj.sql_funcs import ago, gb, kb, mb

# Columns kept off the virtual-dispatch path: built into the projects table directly.
_EAGER_BUILTINS = {"last_modified"}


def _quote_ident(name: str) -> str:
    """Quote an identifier for SQL. Hyphens require quoting."""
    return '"' + name.replace('"', '""') + '"'


def _column_needs_quoting(name: str) -> bool:
    return not name.replace("_", "a").isalnum()


def _ref(name: str) -> str:
    """Render a column reference: quoted if needed."""
    return _quote_ident(name) if _column_needs_quoting(name) else name


class Engine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)


def build_engine(
    projects: ProjectRegistry,
    columns: ColumnRegistry,
    dispatcher: Dispatcher,
) -> Engine:
    """Build an in-memory SQLite database materialized from the registries."""
    conn = sqlite3.connect(":memory:")

    # Register scalar functions
    conn.create_function("gb", 1, gb)
    conn.create_function("mb", 1, mb)
    conn.create_function("kb", 1, kb)
    conn.create_function("ago", 1, ago)
    conn.create_function("get_column_value", 2, dispatcher.get_value, deterministic=True)
    conn.create_function("get_column_applies", 2, dispatcher.get_applies, deterministic=True)

    tag_set = sorted(projects.all_tags())
    virtual_cols = [
        spec for spec in columns
        if spec.name not in _EAGER_BUILTINS and spec.name != "unknown"
    ]

    # Build CREATE TABLE
    col_defs = [
        "name TEXT PRIMARY KEY",
        "path TEXT NOT NULL",
        "last_modified INTEGER",
        "unknown INTEGER DEFAULT 0",
    ]
    for t in tag_set:
        col_defs.append(f"{_ref(t)} INTEGER DEFAULT 0")
    for spec in virtual_cols:
        col_defs.extend(_virtual_col_defs(spec))

    create_sql = "CREATE TABLE projects (\n  " + ",\n  ".join(col_defs) + "\n)"
    conn.execute(create_sql)

    # INSERT a row per project (eager values only)
    for project in projects:
        tag_values = [1 if t in project.tags else 0 for t in tag_set]
        last_mod = _eager_last_modified(project.path)
        cols = ["name", "path", "last_modified"] + [_ref(t) for t in tag_set]
        placeholders = ",".join(["?"] * len(cols))
        params = [project.name, str(project.path), last_mod] + tag_values
        conn.execute(
            f"INSERT INTO projects ({','.join(cols)}) VALUES ({placeholders})",
            params,
        )
    conn.commit()
    return Engine(conn)


def _eager_last_modified(path) -> int | None:
    try:
        mtimes = [int(p.stat().st_mtime) for p in path.iterdir() if p.is_file()]
        return max(mtimes) if mtimes else int(path.stat().st_mtime)
    except (OSError, FileNotFoundError):
        return None


def _sql_type(col_type: str) -> str:
    return {
        "text": "TEXT", "integer": "INTEGER", "boolean": "INTEGER", "real": "REAL",
    }[col_type]


def _virtual_col_defs(spec: ColumnSpec) -> list[str]:
    """Generate the (value, _applies) pair of virtual-column DEFs for a spec."""
    name_ref = _ref(spec.name)
    applies_ref = _ref(f"{spec.name}_applies")

    if spec.applies_to:
        gate = spec.applies_to
        applies_def = (
            f"{applies_ref} INTEGER GENERATED ALWAYS AS ("
            f"CASE WHEN {gate} THEN get_column_applies(name, '{spec.name}') ELSE 0 END"
            f") VIRTUAL"
        )
        value_def = (
            f"{name_ref} {_sql_type(spec.type)} GENERATED ALWAYS AS ("
            f"CASE WHEN {gate} THEN get_column_value(name, '{spec.name}') ELSE NULL END"
            f") VIRTUAL"
        )
    else:
        applies_def = (
            f"{applies_ref} INTEGER GENERATED ALWAYS AS ("
            f"get_column_applies(name, '{spec.name}')"
            f") VIRTUAL"
        )
        value_def = (
            f"{name_ref} {_sql_type(spec.type)} GENERATED ALWAYS AS ("
            f"get_column_value(name, '{spec.name}')"
            f") VIRTUAL"
        )
    return [applies_def, value_def]
