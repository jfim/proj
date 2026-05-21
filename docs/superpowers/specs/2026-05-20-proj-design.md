# proj v1 — Design

**Status:** Draft for review
**Date:** 2026-05-20

## Purpose

`proj` is a CLI for managing a flat directory of heterogeneous projects (OSS checkouts, experiments, datasets, personal code) with tagging, auditing, and cross-project task execution. It operates on a *global* workspace declared in a user-level manifest, not a workspace-local one.

The original spec called for an ad-hoc query/filter model split across `tags`, auto-detected properties, named checks, and a fixed command set. This design replaces all of those with two uniform abstractions: **columns** (everything observable about a project) and **commands** (everything you do with that data), both backed by in-memory SQLite. Tags, language detection, check predicates, audit, dust, status, and clean all collapse into configurable command definitions over columns. `--where` is the universal filter on every command.

## Core model

### Columns

Everything observable about a project is a **column**. Three tiers:

1. **Built-in baseline** — always cheap, shown by default in `proj ls`:
   `name`, `path`, `size`, `last_modified`, `tags`
2. **Built-in extended** — shipped with the tool, evaluated lazily when referenced:
   - Language detection: `lang_rust`, `lang_elixir`, `lang_scala`, `lang_r`, `lang_python`, `lang_js`, `lang_ts`, `lang_go`, `lang_java`, `lang_kotlin`
   - Filesystem: `has_makefile`, `has_justfile`, `has_readme`, `has_license`, `unknown`
   - Git: `git`, `dirty`, `branch`, `ahead`, `behind`, `last_commit`
   - Auto-detection: `clean_target` (returns `"make clean"`, `"cargo clean"`, `"just clean"`, `"npm run clean"`, `"./gradlew clean"`, or `NULL`)
3. **User-defined** — declared in manifest, evaluated lazily, `cache: true` opt-in for persistent caching

**Tags** are sugar for boolean columns. The manifest entry `tags: [oss, mine]` desugars to `oss: true, mine: true`. The YAML `tags: [...]` syntax is preserved; internally each tag is a column.

Users can **override any built-in column** by redeclaring it in their manifest.

### Commands

Two command types are user-definable: `query` and `run`. Five primitives are hardcoded because they require imperative orchestration:

| Hardcoded primitive | Why it's not configurable |
|---|---|
| `query` | Exec arbitrary SQL — the underlying engine itself |
| `run` | Exec a shell command per matching project — the underlying engine itself |
| `adopt` | Interactive manifest edit |
| `new` | Template runner + manifest update |
| `archive` | Multi-step (clean → tar → move → manifest update) |

Everything else — `ls`, `status`, `clean`, `audit`, plus anything the user invents (`fmt`, `lint`, `pull`) — is a user-overridable command defined in YAML. Bundled defaults ship inside the package and are merged before the user's manifest, so user definitions override defaults entry-by-entry.

`proj <name>` resolution: hardcoded primitive (if matched) wins; otherwise look up `commands.<name>` in the merged config.

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
    applies-to: lang_elixir              # SQL where-expression; column is NULL when false
    value-from: grep otp .tool-versions | sed 's/.*-otp-//'
    type: text                           # required: text | integer | boolean | real
    cache: true                          # default false
  has_license:
    applies-to: oss
    value-from: test -f LICENSE && echo true || echo false
    type: boolean
  swp_in_gitignore:
    applies-to: git
    value-from: grep -q swp .gitignore && echo true || echo false
    type: boolean

commands:
  ls:                                    # overrides bundled default
    type: query
    columns: [name, tags, size, last_modified]
    order_by: name

  audit:                                 # overrides bundled default
    type: query
    columns: [name, path]
    grouped_columns:
      audit:
        applicable: [has_readme, swp_in_gitignore, has_license]

  fmt:                                   # user-invented
    type: run
    where: has_justfile
    cmd: "cd {{path}} && just fmt"

templates:
  python-uv:
    tags: [mine, lang_python]
    cmds:
      - mkdir {{name}}
      - cd {{name}} && git init -b master
      - cd {{name}} && claude "scaffold a Python project with uv, ruff, justfile, pytest"
```

CLI flags override manifest values per invocation.

## Query engine

In-memory SQLite (`:memory:`) materialized per invocation:

```sql
CREATE TABLE projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    last_modified INTEGER,
    -- one INTEGER column per declared tag (boolean as 0/1)
    oss INTEGER,
    mine INTEGER,
    -- expensive built-ins and user-defined columns as VIRTUAL generated columns
    -- applies-to is baked into the generated expression: NULL when not applicable
    size INTEGER GENERATED ALWAYS AS (get_column_value(path, 'size')) VIRTUAL,
    dirty INTEGER GENERATED ALWAYS AS (
        CASE WHEN git THEN get_column_value(path, 'dirty') ELSE NULL END
    ) VIRTUAL,
    has_license INTEGER GENERATED ALWAYS AS (
        CASE WHEN oss THEN get_column_value(path, 'has_license') ELSE NULL END
    ) VIRTUAL,
    "otp-version" TEXT GENERATED ALWAYS AS (
        CASE WHEN lang_elixir THEN get_column_value(path, 'otp-version') ELSE NULL END
    ) VIRTUAL
);
```

### Single dispatch function

One Python function is registered with SQLite via `conn.create_function`:

```python
def get_column_value(path: str, column_name: str) -> Any:
    """Resolve a column value for a project, with caching and type coercion."""
    spec = column_registry[column_name]   # built-in or user-defined
    if spec.cache:
        cached = cache.lookup(path, column_name, spec.cache_key(path))
        if cached is not None:
            return cached
    try:
        raw = spec.evaluate(path)         # stat, git, shell, etc.
    except Exception as e:
        log.warning("column %s on %s failed: %s", column_name, path, e)
        return None                       # SQL NULL
    value = coerce_to_type(raw, spec.type)  # None if coercion fails
    if spec.cache and value is not None:
        cache.store(path, column_name, spec.cache_key(path), value)
    return value
```

All built-in extended columns and all user-defined columns flow through this function. It's the single dispatch point where caching, type coercion, and error handling live. `applies-to` gating lives in the generated-column SQL (above), not in this function — by the time `get_column_value` is invoked, applicability is already true.

### Type system

User-defined columns **must** declare `type:` (`text|integer|boolean|real`). `get_column_value` coerces the raw shell output to the declared type:
- `boolean`: `"true"|"1"|"yes"` → `1`; `"false"|"0"|"no"|""` → `0`; anything else → `None`
- `integer`: `int(raw.strip())`, `None` on `ValueError`
- `real`: `float(raw.strip())`, `None` on `ValueError`
- `text`: `raw.strip()`

On any failure (non-zero exit, exception, coercion error): return `None` (SQL `NULL`), log a one-liner to stderr, do not abort the query.

### Cache

On-disk at `~/.cache/proj/`, keyed by `(path, column_name, cache_key)` where `cache_key` is by default `dir_mtime(path)` but for user-defined columns also includes a hash of `value-from` (so changing the shell command invalidates). Expensive built-ins (`size`, `dirty`, `clean_target`) cache by default; user-defined columns cache when `cache: true`.

A progress indicator displays when >5 uncached expensive columns must be computed in one query.

### Lazy evaluation

SQLite only invokes `get_column_value` for columns referenced in the query. Cheap columns (`name`, `path`, `last_modified`, tags) are INSERTed eagerly; everything else is lazy and free when not referenced.

### Identifier convention

Column names use **underscores**. YAML `tags: [lang:elixir]` is preserved for ergonomics; colons normalize to underscores internally (`lang:elixir` → `lang_elixir`). User-defined columns with hyphens (`otp-version`) must be SQL-quoted (`"otp-version"`) in queries.

### Size / duration literals

Registered SQL scalar functions:
- `gb(1)`, `mb(50)`, `kb(100)` → bytes
- `ago("6m")`, `ago("90d")`, `ago("1y")` → unix timestamp N units before now

Example: `--where 'size > gb(1) and last_modified < ago("6m")'`

### Grouped columns

A `query`-type command can project **grouped columns** that aggregate multiple input columns into a single derived value per row. v1 ships one grouping kind: `applicable` — counts how many of a list of columns apply and how many pass.

Manifest:
```yaml
commands:
  audit:
    type: query
    columns: [name, path]
    grouped_columns:
      audit:
        applicable: [has_readme, swp_in_gitignore, has_license]
```

Expands at command-build time to:
```sql
SELECT name, path,
  CAST(COALESCE(has_readme,0) + COALESCE(swp_in_gitignore,0) + COALESCE(has_license,0) AS TEXT)
    || '/' ||
  CAST(((has_readme IS NOT NULL) + (swp_in_gitignore IS NOT NULL) + (has_license IS NOT NULL)) AS TEXT)
    AS audit
FROM projects;
```

Sample output:
```
NAME            PATH                       AUDIT
my-cool-lib     /home/me/projects/lib      3/3
pandas-fork     /home/me/projects/pandas   2/3
weekend-game    /home/me/projects/game     0/0
```

A project where no columns apply shows `0/0`. Drill-down: `proj query 'name, has_readme, has_license, swp_in_gitignore' --where 'has_readme = 0 or has_license = 0 or swp_in_gitignore = 0'`.

Future grouping kinds (out of scope for v1) could include `min`, `max`, `count_failing`, `failing_names`.

## Commands

All commands accept `--where <sql-expr>` as a filter and `--format table|json|plain`.

### Hardcoded primitives

| Command | Purpose |
|---|---|
| `proj query <input> [--where <expr>] [--order-by <col>] [--limit N] [--group-by <col>]` | Execute SQL. If `<input>` matches `^\s*select\s+`, run verbatim. Otherwise treat as comma-separated column list and wrap as `SELECT <input> FROM projects [WHERE ...] [GROUP BY ...] [ORDER BY ...] [LIMIT ...]`. |
| `proj run <cmd> [--where ...] [--parallel] [--summary] [--only-matches] [--only-failures]` | Run shell command in each matching project (cwd set to project path). Exit code = number of failures. |
| `proj adopt [<subdir>]` | Interactively promote an unknown subdirectory to a declared project. Prompts for tags. |
| `proj new <template> <name>` | Run template's `cmds` with `{{var}}` interpolation, auto-add to manifest with template's tags. |
| `proj archive [--where ...] [--dry-run] [--restore <name>]` | Run clean target, compress to `archive_dir`, update manifest. |

### Bundled default commands

Shipped in `proj/defaults.yaml`, merged before the user's manifest. Users override by redefining the same key.

```yaml
commands:
  ls:
    type: query
    columns: [name, tags, size, last_modified]
    order_by: name

  status:
    type: query
    columns: [name, branch, dirty, ahead, behind, last_commit]
    where: git

  clean:
    type: run
    where: clean_target is not null
    cmd: "cd {{path}} && {{clean_target}}"

  audit:
    type: query
    columns: [name, path]
    grouped_columns:
      audit:
        applicable: [has_readme, has_license]
```

### `query`-type command schema

```yaml
<name>:
  type: query
  columns: [<col>, ...]              # required; output columns
  grouped_columns:                   # optional; derived projections
    <output_col_name>:
      applicable: [<col>, ...]       # v1: only "applicable" kind supported
  where: <sql-expr>                  # optional; merged with --where via AND
  order_by: <col-or-expr>            # optional
  limit: <int>                       # optional
```

### `run`-type command schema

```yaml
<name>:
  type: run
  cmd: <shell-command>               # required; {{path}}, {{name}}, and any column value can be interpolated
  where: <sql-expr>                  # optional; merged with --where via AND
  parallel: <bool>                   # optional; default from settings.parallel
  summary: <bool>                    # optional; default false
  scope: <single|aggregate>          # optional; overrides type default
```

Variable interpolation in `cmd` uses `{{column_name}}`. Any column referenced is auto-required (added to materialization), so `cmd: "cd {{path}} && {{clean_target}}"` causes `clean_target` to be evaluated for each row.

`--dry-run` is available on all `run`-type commands and the `run` primitive: prints the interpolated command per project without executing.

**Note on `--group-by` vs `grouped_columns`:** these are unrelated. `--group-by` is SQL `GROUP BY` (aggregates rows). `grouped_columns` is a per-row projection that combines multiple input columns into one output column.

### Invocation context

`proj` is invokable from anywhere on the filesystem. Scope is determined by **command type**:

- **`run`-type commands** (and the `run` primitive) default to **single-project** when invoked inside a project: auto-scope to the current project.
- **`query`-type commands** (and the `query` primitive, plus `archive`) default to **aggregate**: always cover the workspace regardless of cwd.
- Override with `--all` (force workspace) or `--here` (force current project).
- A command config may set `scope: single|aggregate` to override the type default (e.g., a `status` query that the user wants to default to single-project inside one).

Detection of "inside a project": walk up from cwd until the parent equals `workspace.root`; the last directory before that parent is the current project. If cwd is not under `workspace.root`, no auto-scoping applies.

### Unknown subdirectories

Any subdirectory of `workspace.root` not listed in `projects` is implicitly present in the table with `unknown = 1`. Behavior controlled by `settings.unknown_handling`:

- `include` (default) — unknowns appear in all queries
- `warn` — unknowns appear with a stderr footer counting them
- `ignore` — unknowns excluded from queries entirely; only visible via `proj adopt`

`proj adopt foo` (or just `proj adopt` to pick from a list) prompts for tags interactively and writes the entry to the manifest.

### Templates

User-defined under `templates:`. Each template has:
- `tags: [...]` — applied to the new project's manifest entry
- `cmds: [...]` — shell commands run in sequence from `workspace.root`

Variable interpolation uses `{{var}}`:
- `{{name}}` — the project name argument
- `{{workspace_root}}` — absolute path
- `{{date}}` — ISO date

After all `cmds` succeed, the new project is auto-added to `projects:` with the template's tags.

## Examples

```bash
proj ls --where mine
proj query 'name, size, "otp-version"' --where 'lang_elixir and size > gb(1)'
proj query '"otp-version", count(*)' --where lang_elixir --group-by '"otp-version"'
proj run --where 'lang_rust and mine' 'cargo fmt --check'
proj status --where dirty
proj audit --where mine
proj clean --dry-run
proj fmt                                   # user-defined
proj archive --where 'last_modified < ago("1y") and not mine' --dry-run
proj new python-uv my-experiment
```

## What's dropped from the original spec

- **Workspace-local `projects.yaml`** — replaced by global `~/.config/proj/projects.yaml`.
- **Fixed command set** — `list`, `status`, `clean`, `audit`, `dust` are now user-overridable commands shipped as defaults; the spec keeps `ls` and `audit` semantics intact but they're no longer hardcoded.
- **Standalone `dust` command** — covered by the bundled `ls` default plus `proj query`; users can add a personal `dust` command if they want a specialized one.
- **Separate aggregate command** — collapses into `proj query` with `GROUP BY`.
- **Special "checks" concept** — checks are just boolean columns; audit is a query with a grouped projection.

## v1 scope cuts (designed for, not built)

- AI-driven `proj new` (users can already invoke `claude` from a template's `cmds`)
- Plugin/extension system for built-in columns
- Concurrent cache writes (single-process v1; file lock if/when needed)
- Additional grouping kinds (`min`, `max`, `count_failing`, `failing_names`)
- `proj config dump` to show effective merged config

## Open implementation notes

- **Cache key** for user-defined columns includes a hash of `value-from` so editing the command invalidates entries.
- **Parallel runs** share the cache via per-key file lock.
- **Tag column declaration**: when materializing the schema, the set of all tags referenced in any project's `tags:` is collected; each becomes a non-virtual INTEGER column, populated at INSERT.
- **`--where` from CLI and command-level `where:`** combine via `AND`.
- **Boolean values in queries**: SQLite has no real boolean — `where dirty` and `where dirty = 1` are equivalent; `not dirty` works as `dirty = 0 OR dirty IS NULL` only if you mean it that way, otherwise prefer `dirty = 0`.
