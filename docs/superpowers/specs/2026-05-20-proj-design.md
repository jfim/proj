# proj v1 — Design

**Status:** Draft for review
**Date:** 2026-05-20

## Purpose

`proj` is a CLI for managing a flat directory of heterogeneous projects (OSS checkouts, experiments, datasets, personal code) with tagging, auditing, and cross-project task execution. It operates on a *global* workspace declared in a user-level manifest, not a workspace-local one.

The original spec called for an ad-hoc query/filter model split across `tags`, auto-detected properties, and named checks. This design replaces all three with a single uniform abstraction — **columns** — and a query engine backed by in-memory SQLite. Tags, language detection, and check predicates all become columns. `--where` is the universal filter on every command.

## Core model

Everything observable about a project is a **column**. Columns come in three tiers:

1. **Built-in baseline** — always cheap, always shown by default in `proj list`:
   `name`, `path`, `size`, `last_modified`
2. **Built-in extended** — shipped with the tool, evaluated lazily when referenced:
   `git`, `dirty`, `lang_rust`, `lang_elixir`, `lang_scala`, `lang_r`, `lang_python`, `lang_js`, `lang_ts`, `lang_go`, `lang_java`, `lang_kotlin`, `has_makefile`, `unknown`
3. **User-defined** — declared in manifest, evaluated lazily, `cache: true` opt-in for persistent caching

**Tags** are syntactic sugar for boolean columns. The manifest entry `tags: [oss, mine]` desugars to `oss: true, mine: true`. The convenient `tags: [...]` syntax is preserved in YAML; internally each tag is a column.

Users can **override any built-in column** by redeclaring it in their manifest.

## Manifest format

Single global manifest at `~/.config/proj/projects.yaml`:

```yaml
workspace:
  root: ~/projects

settings:
  parallel: true
  color: auto
  unknown_handling: include   # include | warn | ignore
  archive_dir: _archive

projects:
  my-cool-lib:
    tags: [oss, mine, library]
  pandas-fork:
    tags: [oss, not-mine]
  churn-analysis:
    tags: [dataset, work]

columns:
  otp-version:
    applies-to: "lang_elixir"           # SQL-where on a project; null means all
    value-from: grep otp .tool-versions | sed 's/.*-otp-//'
    cache: true
  has-readme:
    value-from: test -f README.md && echo true || echo false
    type: boolean

templates:
  python-uv:
    tags: [mine, lang_python]
    cmds:
      - mkdir {{name}}
      - cd {{name}} && git init -b master
      - cd {{name}} && claude "scaffold a Python project with uv, ruff, justfile, pytest"
```

`~/.projrc` may provide user-level defaults that the workspace manifest overrides; CLI flags override both.

## Query engine

In-memory SQLite (`:memory:`) materialized per invocation:

```sql
CREATE TABLE projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    last_modified INTEGER,
    -- one column per declared tag (boolean)
    oss BOOLEAN,
    mine BOOLEAN,
    -- expensive built-ins and user-defined columns as VIRTUAL generated columns
    size INTEGER GENERATED ALWAYS AS (get_column_value(path, 'size')) VIRTUAL,
    dirty BOOLEAN GENERATED ALWAYS AS (get_column_value(path, 'dirty')) VIRTUAL,
    lang_rust BOOLEAN GENERATED ALWAYS AS (get_column_value(path, 'lang_rust')) VIRTUAL,
    "otp-version" TEXT GENERATED ALWAYS AS (get_column_value(path, 'otp-version')) VIRTUAL
);
```

### Single dispatch function

One Python function is registered with SQLite via `conn.create_function`:

```python
def get_column_value(path: str, column_name: str) -> Any:
    """Resolve a column value for a project, with caching."""
    spec = column_registry[column_name]   # built-in or user-defined
    if spec.cache:
        cached = cache.lookup(path, column_name, dir_mtime(path))
        if cached is not None:
            return cached
    value = spec.evaluate(path)           # stat, git, shell, etc.
    if spec.cache:
        cache.store(path, column_name, dir_mtime(path), value)
    return value
```

All built-in extended columns and all user-defined columns flow through this function. The single dispatch point is where caching, error handling, and `applies-to` gating live.

### Cache

On-disk at `~/.cache/proj/`, keyed by `(path, column_name, dir_mtime)`. Expensive built-ins (`size`, `dirty`) cache by default; user-defined columns cache when `cache: true`. Cache invalidates automatically when the project directory's recursive mtime changes.

A progress indicator displays when more than ~5 uncached expensive columns must be computed in a single query ("Computing size for 80 projects…").

### Lazy evaluation

SQLite only invokes `get_column_value` for columns referenced in the query. Cheap columns (tags, `name`, `path`, `last_modified`) are INSERTed eagerly; everything else is lazy and free when not referenced.

### Identifier convention

Column names use **underscores**, not hyphens — to keep SQL identifiers unquoted in the common case. The YAML `tags: [lang:elixir]` syntax is preserved for human ergonomics; colons are normalized to underscores internally (`lang:elixir` → `lang_elixir`). User-defined columns with hyphens in the name (`otp-version`) must be SQL-quoted (`"otp-version"`).

### Size / duration literals

Registered SQL functions provide ergonomic literals:
- `gb(1)`, `mb(50)`, `kb(100)` → bytes
- `ago("6m")`, `ago("90d")`, `ago("1y")` → unix timestamp N units before now

Example: `--where 'size > gb(1) and last_modified < ago("6m")'`

## Commands

All commands accept `--where <sql-expr>` as a filter. Output formats: `--format table|json|plain`.

| Command | Purpose |
|---|---|
| `proj query <input> [--where <expr>] [--order-by <col>] [--limit N] [--group-by <col>]` | General primitive. If `<input>` matches `^\s*select\s+`, it's executed verbatim. Otherwise it's treated as a comma-separated column list and wrapped as `select <input> from projects [where ...] [group by ...] [order by ...] [limit ...]`. |
| `proj list [--where ...]` | Sugar for `select name, tags from projects`. |
| `proj run <cmd> [--where ...] [--parallel] [--summary] [--only-matches] [--only-failures]` | Run shell command in each matching project. Exit code = number of failures. |
| `proj status [--where ...]` | Sugar for `select name, branch, dirty, ahead, behind, last_commit from projects where git`. |
| `proj clean [--where ...] [--dry-run]` | Run each project's auto-detected clean target. |
| `proj archive [--where ...] [--dry-run] [--restore <name>]` | Run clean, compress to `_archive/`, update manifest. |
| `proj adopt [<subdir>]` | Interactively promote an unknown subdirectory to a declared project. Prompts for tags. |
| `proj new <template> <name>` | Run template's `cmds` with variable interpolation, auto-add to manifest with template's tags. |

### Invocation context

`proj` is invokable from anywhere on the filesystem.

- **Single-project commands** (`status`, `clean`, `run` with no `--where`) auto-scope to the current project when invoked inside one.
- **Aggregate commands** (`list`, `query`, `archive`) always cover the workspace regardless of cwd.
- Override with `--all` (force workspace) or `--here` (force current project).

Detection of "inside a project": walk up from cwd until the parent equals `workspace.root`; the last directory before that parent is the current project. If cwd is not under `workspace.root`, no auto-scoping applies and aggregate behavior is used.

### Unknown subdirectories

Any subdirectory of `workspace.root` not listed in `projects` is implicitly present in the `projects` table with `unknown = true`. Behavior controlled by `settings.unknown_handling`:

- `include` (default) — unknowns appear in all queries; `proj list` shows them with `unknown` flag
- `warn` — unknowns appear with a warning footer counting them
- `ignore` — unknowns excluded from queries entirely; only visible via `proj adopt`

`proj adopt foo` prompts for tags interactively and writes the entry to the manifest.

### Templates

User-defined in `templates:`. Each template has:
- `tags: [...]` — applied to the new project's manifest entry
- `cmds: [...]` — shell commands run in sequence from `workspace.root`

Variable interpolation uses `{{var}}` (mustache-style; no shell collision):
- `{{name}}` — the project name argument
- `{{workspace_root}}` — absolute path
- `{{date}}` — ISO date

After all `cmds` succeed, the new project is auto-added to `projects:` with the template's tags.

## Examples

```bash
proj list --where mine
proj query 'name, size, "otp-version"' --where 'lang_elixir and size > gb(1)'
proj query '"otp-version", count(*)' --where lang_elixir --group-by '"otp-version"'
proj run --where 'lang_rust and mine' 'cargo fmt --check'
proj status --where dirty
proj archive --where 'last_modified < ago("1y") and not mine' --dry-run
proj new python-uv my-experiment
```

## What's dropped from the original spec

- **Workspace-local `projects.yaml`** — replaced by global `~/.config/proj/projects.yaml`.
- **Standalone `audit` command** — checks become boolean columns; `proj query name --where 'not has_readme'` covers the use case. May ship as a sugar command later.
- **Standalone `dust` command** — `proj query 'name, size, last_modified' --where 'size > mb(50)' --order-by size desc` covers it. May ship as sugar later.
- **Separate "aggregate" command** — collapses into `proj query` with `GROUP BY`.

## v1 scope cuts (designed for, not built)

- Sugar commands `audit`, `dust` (use `query` directly)
- AI-driven `proj new` (users can invoke `claude` from a template's `cmds`)
- Plugin/extension system for columns
- Concurrent cache writes (single-process v1; lock if/when needed)

## Open questions for implementation

- Cache invalidation strategy when `value-from` shell command itself changes (cache key includes a hash of the command).
- Behavior when `value-from` fails (non-zero exit): treat as `NULL` value, log to stderr, do not abort.
- Whether `proj run --parallel` shares the cache layer (yes — file lock per cache key).
- Column type inference for user-defined columns: declare `type: boolean|integer|text` in manifest, default to `text`.
