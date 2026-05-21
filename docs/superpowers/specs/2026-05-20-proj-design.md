# proj v1 — Design

**Status:** Draft for review
**Date:** 2026-05-20

## Purpose

`proj` is a CLI for managing a flat directory of heterogeneous projects (OSS checkouts, experiments, datasets, personal code) with tagging, auditing, and cross-project task execution. It operates on a *global* workspace declared in a user-level manifest, not a workspace-local one.

The original spec called for an ad-hoc query/filter model split across `tags`, auto-detected properties, named checks, and a fixed command set. This design replaces all of those with two uniform abstractions: **columns** (everything observable about a project) and **commands** (everything you do with that data), backed by in-memory SQLite. Tags, language detection, check predicates, audit, dust, status, clean, and archive all collapse into configurable command definitions over columns. `--where` is the universal filter on every command, and `forget`/`adopt` are the two primitives that mutate the manifest from inside a shell pipeline.

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

Two command types are user-definable: `query` and `run`. Five primitives are hardcoded because they require imperative orchestration the YAML model can't express:

| Hardcoded primitive | Why it's not configurable |
|---|---|
| `query` | Exec arbitrary SQL — the underlying engine itself |
| `run` | Exec a shell command per matching project — the underlying engine itself |
| `adopt` | Interactive manifest edit (add project, prompt for tags) |
| `forget` | Manifest edit (remove a project entry) |
| `new` | Template runner + manifest update |

Everything else — `ls`, `status`, `clean`, `audit`, `archive`, plus anything the user invents (`fmt`, `lint`, `pull`) — is a user-overridable command defined in YAML. Bundled defaults ship inside the package and are merged before the user's manifest, so user definitions override defaults entry-by-entry.

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

  # Project variables: any key beyond `tags` and `path` is a per-project
  # variable available as {{key}} in this project's column value-from and
  # command cmd strings. Multiple project entries can share a `path:`.
  my-app:
    tags: [oss, mine]
  my-app-server-1:
    tags: [my-app, deployment]
    path: my-app                    # share source dir with the my-app entry
    deploy-path: /var/foo
    host: server-1.tld
  my-app-server-2:
    tags: [my-app, deployment]
    path: my-app
    deploy-path: /var/bar
    host: server-2.tld

columns:
  otp-version:
    applies-to: lang_elixir              # SQL where-expression; cheap, baked into schema
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
  swp_in_hgignore:
    applies-when: test -f .hgignore      # shell-evaluated; expensive, runs per project
    value-from: grep -q swp .hgignore && echo true || echo false
    type: boolean

  # Columns can reference per-project variables via {{key}}
  is_running:
    applies-to: my-app AND deployment
    value-from: ssh {{host}} 'pgrep -f myapp >/dev/null && echo true || echo false'
    type: boolean
    cache: false                         # don't cache live state
  deployed_version:
    applies-to: my-app AND deployment
    value-from: ssh {{host}} 'cat {{deploy-path}}/version.txt'
    type: text
  source_version:
    applies-to: my-app
    value-from: cat {{path}}/version.txt
    type: text

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
        mode: applicable
        columns: [has_readme, swp_in_gitignore, has_license]
        on_pass: hide
        on_fail: mark-bad
        on_error: mark-warn
        on_na: hide

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

Each non-tag column is synthesized as **two** paired VIRTUAL generated columns: `<name>` (the value) and `<name>_applies` (a boolean: is this column applicable to this project?). The `_applies` partner is always present, even for ungated columns (where it's a constant `1`).

```sql
CREATE TABLE projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    last_modified INTEGER,

    -- tags: one INTEGER column per declared tag (boolean as 0/1)
    oss INTEGER,
    mine INTEGER,

    -- ungated column: _applies is constant 1
    size_applies INTEGER GENERATED ALWAYS AS (1) VIRTUAL,
    size         INTEGER GENERATED ALWAYS AS (get_column_value(name, 'size')) VIRTUAL,

    -- applies-to gate: SQL CASE referencing other columns
    dirty_applies INTEGER GENERATED ALWAYS AS (
        CASE WHEN git THEN get_column_applies(name, 'dirty') ELSE 0 END
    ) VIRTUAL,
    dirty INTEGER GENERATED ALWAYS AS (
        CASE WHEN git THEN get_column_value(name, 'dirty') ELSE NULL END
    ) VIRTUAL,

    has_license_applies INTEGER GENERATED ALWAYS AS (
        CASE WHEN oss THEN get_column_applies(name, 'has_license') ELSE 0 END
    ) VIRTUAL,
    has_license INTEGER GENERATED ALWAYS AS (
        CASE WHEN oss THEN get_column_value(name, 'has_license') ELSE NULL END
    ) VIRTUAL,

    -- applies-when gate: lives inside get_column_applies (shell-evaluated)
    swp_in_hgignore_applies INTEGER GENERATED ALWAYS AS (
        get_column_applies(name, 'swp_in_hgignore')
    ) VIRTUAL,
    swp_in_hgignore INTEGER GENERATED ALWAYS AS (
        get_column_value(name, 'swp_in_hgignore')
    ) VIRTUAL,

    -- both gates: SQL CASE wraps get_column_applies
    "otp-version_applies" INTEGER GENERATED ALWAYS AS (
        CASE WHEN lang_elixir THEN get_column_applies(name, 'otp-version') ELSE 0 END
    ) VIRTUAL,
    "otp-version" TEXT GENERATED ALWAYS AS (
        CASE WHEN lang_elixir THEN get_column_value(name, 'otp-version') ELSE NULL END
    ) VIRTUAL
);
```

Two SQLite-registered Python functions back this:

- `get_column_value(name, column_name)` — returns the column's value, or `NULL` on error / applies-when miss
- `get_column_applies(name, column_name)` — returns `1` (applicable) or `0` (not applicable) based on the column's `applies-when`. Returns `1` when no `applies-when` is declared.

The SQL-level `applies-to` gate is baked into **both** the value and `_applies` expressions (it references other columns, which only SQL can see). The `applies-when` gate lives inside `get_column_applies`. `get_column_value` also internally invokes the applies-when check before running `value-from`, so a query that selects only the value column (not `_applies`) still gets correct NULLs.

The `_applies` suffix is reserved; the manifest validator errors if a user-defined column name ends in `_applies`.

### Dispatch functions

Two Python functions are registered with SQLite via `conn.create_function`. Both take `name` (the project name), not just path, so they can resolve per-project variables for interpolation:

```python
def get_column_applies(name: str, column_name: str) -> int:
    """Return 1 if the column's applies-when condition is satisfied (or no applies-when), else 0."""
    spec = column_registry[column_name]
    if spec.applies_when is None:
        return 1
    project = project_registry[name]
    rendered = interpolate(spec.applies_when, project.vars)  # {{host}}, {{path}}, etc.
    cache_key = spec.cache_key(name, rendered)
    cached = cache.lookup(name, f"{column_name}__applies", cache_key)
    if cached is not None:
        return cached
    applies = 1 if shell_ok(rendered, cwd=project.path) else 0
    cache.store(name, f"{column_name}__applies", cache_key, applies)
    return applies


def get_column_value(name: str, column_name: str) -> Any:
    """Resolve a column value for a project, with caching, applies-when gating, and type coercion."""
    spec = column_registry[column_name]
    if get_column_applies(name, column_name) == 0:
        return None                       # SQL NULL — not applicable
    project = project_registry[name]
    rendered = interpolate(spec.value_from, project.vars)
    cache_key = spec.cache_key(name, rendered)
    if spec.cache:
        cached = cache.lookup(name, column_name, cache_key)
        if cached is not None:
            return cached
    try:
        raw = spec.evaluate(rendered, cwd=project.path)
    except Exception as e:
        log.warning("column %s on %s failed: %s", column_name, name, e)
        return None                       # SQL NULL — error
    value = coerce_to_type(raw, spec.type)
    if spec.cache and value is not None:
        cache.store(name, column_name, cache_key, value)
    return value
```

The cache key hashes the **post-interpolation** command string, so editing a project's variable (e.g., changing `host`) automatically invalidates that project's cached values for columns that reference the changed variable.

All built-in extended columns and all user-defined columns flow through these functions. They are the single dispatch points where caching, applies-when gating, type coercion, and error handling live. `applies-to` gating lives in the generated-column SQL (above), not in these functions — by the time either is invoked, the cheap SQL-level applicability check has already passed.

### Applicability: two flavors

A column can be gated by either, both, or neither:

| Flavor | Where evaluated | Cost | Use when |
|---|---|---|---|
| `applies-to: <sql-expr>` | SQL `CASE WHEN ... THEN ... ELSE NULL END` baked into both the value and `_applies` generated columns | Cheap — references already-materialized columns | The gate is a tag or another column (`lang_elixir`, `oss`, `git`) |
| `applies-when: <shell-cmd>` | Inside `get_column_applies`, called with `cwd` = project path; `{{var}}` interpolation applies | Expensive — shell invocation per project (cached) | The gate requires touching the filesystem in a way no existing column captures (`test -f .hgignore`, `git config --get something`) |

When both are present: SQL gate runs first (via the generated-column `CASE WHEN`); if it passes, the shell gate runs (via `get_column_applies`); if both pass, `value-from` runs. The shell gate's exit code is the signal: zero → applicable, non-zero → not applicable.

The `applies-when` shell command is part of the cache key (hash) so editing it invalidates cached values.

### Project variables

A project entry's manifest dict can hold arbitrary user-defined keys alongside the two reserved keys:

| Key | Meaning |
|---|---|
| `tags:` (reserved) | List of tag strings. |
| `path:` (reserved) | Override the default project path. Defaults to `workspace.root/<name>`. Supports `~` and relative paths (resolved against `workspace.root`). Multiple project entries may share a path. |
| any other key | A per-project variable, accessible as `{{key}}` in this project's column `value-from`, column `applies-when`, and any `run`-type command's `cmd` when invoked on this project. |

The pre-defined variables `{{name}}`, `{{path}}`, `{{workspace_root}}`, and `{{archive_dir}}` are auto-injected. A project-defined variable with the same name as a pre-defined one shadows it (with a load-time warning).

Variables are substituted as raw strings; no shell quoting is added. If a value needs quoting in the resulting shell command, write `"{{host}}"` in your value-from. (A `{{quote(host)}}` helper may be added in v2; out of scope for v1.)

**Use case — per-deployment columns.** A single source directory can be represented by multiple project entries, each carrying its own deployment variables. Columns gated on the `deployment` tag (or whatever convention you adopt) automatically vary per entry:

```yaml
projects:
  my-app-server-1:
    tags: [my-app, deployment]
    path: my-app
    host: server-1.tld
  my-app-server-2:
    tags: [my-app, deployment]
    path: my-app
    host: server-2.tld

columns:
  is_running:
    applies-to: my-app AND deployment
    value-from: ssh {{host}} 'pgrep -f myapp >/dev/null'
    type: boolean
```

Each project row gets its own SSH target without any per-row plumbing.

### Applicability as a queryable column

Because `_applies` is a real virtual column, it's directly queryable:

```bash
# Find projects where the license check doesn't apply (i.e., non-oss)
proj query 'name, has_license_applies' --where 'not has_license_applies'

# Find OSS projects with no license (applies AND value=0)
proj query name --where 'has_license_applies and has_license = 0'

# Find OSS projects where the check errored (applies AND value IS NULL)
proj query name --where 'has_license_applies and has_license is null'
```

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

A `query`-type command can project **grouped columns**: multi-line cells that combine N input boolean columns into a count summary plus per-column status lines. Aggregation happens in **Python**, not SQL — SQLite projects raw column values, the formatter renders them.

Manifest schema:
```yaml
grouped_columns:
  <output_column_name>:
    mode: applicable | all
    columns: [<col-or-expr>, ...]      # input boolean columns OR simple comparison expressions
    on_pass:  hide | <mark-name>       # value=1 and applies=1     (default: mark-good)
    on_fail:  hide | <mark-name>       # value=0 and applies=1     (default: mark-bad)
    on_error: hide | <mark-name>       # value=NULL and applies=1  (default: mark-warn)
    on_na:    hide | <mark-name>       # applies=0                 (default: mark-ignored)
```

**Comparison expressions as input "columns":** an entry in `columns:` may be a simple binary comparison `<a> <op> <b>` where `<a>` and `<b>` are bare column names (identifiers may contain hyphens) and `<op>` is one of `=`, `!=`, `<`, `>`, `<=`, `>=`. The expression is treated as a derived boolean column whose:

- value is `(a OP b)` when both sides apply, else NULL
- `_applies` is `a_applies AND b_applies`
- cell label (in the rendered multi-line cell) is the verbatim expression string

Parser: a single regex `^\s*([\w-]+)\s*(=|!=|<=|>=|<|>)\s*([\w-]+)\s*$` applied to each entry; anything not matching is a bare column reference. `IS NULL`/`IS NOT NULL` are intentionally out of scope for v1 due to subtle applies-vs-null semantics — write a regular column if you need them.

Example:
```yaml
commands:
  deploy_ok:
    type: query
    columns: [name, host, deployed_version]
    grouped_columns:
      deploy_status:
        mode: all
        columns: [is_running, deployed_version=source_version]
        on_pass: hide
        on_fail: mark-bad
        on_error: mark-warn
        on_na: mark-ignored
```
Output (server-1 has the wrong version deployed):
```
NAME              HOST              DEPLOYED_VERSION   DEPLOY_STATUS
my-app-server-1   server-1.tld      1.4.2              1/2
                                                       ✗ deployed_version=source_version
my-app-server-2   server-2.tld      1.5.0              2/2
```

**Count semantics:**
- `mode: applicable` — `passed / applicable` (where `applies=1`; non-applicable excluded from denominator)
- `mode: all` — `passed / total` (all input columns counted in denominator regardless of applicability)

**Per-cell rendering:** for each input column, look at the pair `(<name>_applies, <name>)`:

| `_applies` | value | state | config key | default mark |
|---|---|---|---|---|
| 0 | NULL | not applicable | `on_na` | `mark-ignored` |
| 1 | 1 | pass | `on_pass` | `mark-good` |
| 1 | 0 | fail | `on_fail` | `mark-bad` |
| 1 | NULL | error | `on_error` | `mark-warn` |

`hide` skips the line entirely. Any other value names a **mark** (see below).

**Implementation:** at command-build time, the SELECT auto-projects each input column **and its `_applies` partner** (whether or not the user listed them in `columns:`). After SQLite returns rows, the formatter walks each row's grouped columns and emits a multi-line cell using both halves of each pair.

### Marks

A **mark** is a named visual style for a grouped-column cell line. Each mark has `prefix`, `suffix`, and `color`. The column name is rendered between prefix and suffix in the chosen color:

```
{prefix}{column_name}{suffix}    (in {color})
```

Bundled defaults (shipped in `proj/defaults.yaml`, mergeable):

```yaml
marks:
  mark-good:    { prefix: "✓ ", suffix: "",            color: green  }
  mark-bad:     { prefix: "✗ ", suffix: "",            color: red    }
  mark-warn:    { prefix: "⚠ ", suffix: "",            color: yellow }
  mark-ignored: { prefix: "",   suffix: " (ignored)",  color: grey   }
```

Sample output for `mark-good`: green text `"✓ has_readme"`. Sample for `mark-ignored`: grey text `"has_license (ignored)"`.

Users override marks in their manifest:

```yaml
marks:
  mark-good:
    prefix: "✅ "
    color: bright_green
  mark-fire:                           # invent new marks freely
    prefix: "🔥 "
    color: bright_red
```

A user-defined mark fully replaces the bundled one (whole-record replacement, no field merging). New mark names can be referenced from any `on_*` field. Color names follow [rich's color spec](https://rich.readthedocs.io/en/latest/appendix/colors.html).

Example — audit (hide passes and N/A, show only failures and errors):
```yaml
commands:
  audit:
    type: query
    columns: [name, path]
    grouped_columns:
      audit:
        mode: applicable
        columns: [has_readme, swp_in_gitignore, has_license]
        on_pass: hide
        on_fail: mark-bad
        on_error: mark-warn
        on_na: hide
```
Output:
```
NAME            PATH                       AUDIT
my-cool-lib     /path/lib                  3/3
pandas-fork     /path/pandas               2/3
                                           ✗ has_license
weekend-game    /path/game                 0/0
```

Example — full checks dashboard (show everything):
```yaml
commands:
  checks:
    type: query
    columns: [name]
    grouped_columns:
      checks:
        mode: all
        columns: [has_readme, swp_in_gitignore, has_license]
        on_pass: mark-good
        on_fail: mark-bad
        on_error: mark-warn
        on_na: mark-ignored
```
Output:
```
NAME            CHECKS
my-cool-lib     3/3
                ✓ has_readme
                ✓ swp_in_gitignore
                ✓ has_license
pandas-fork     1/3
                ✓ has_readme
                ✗ swp_in_gitignore
                ? has_license
```

Drill-down to find a specific failure: `proj query 'name, has_license' --where 'has_license = 0'`.

Future symbol/mode extensions are non-breaking (new enum values for `on_pass`/`on_fail`/`on_na`, new `mode:` values).

## Commands

All commands accept `--where <sql-expr>` as a filter and `--format table|json|plain`.

### Hardcoded primitives

| Command | Purpose |
|---|---|
| `proj query <input> [--where <expr>] [--order-by <col>] [--limit N] [--group-by <col>]` | Execute SQL. If `<input>` matches `^\s*select\s+`, run verbatim. Otherwise treat as comma-separated column list and wrap as `SELECT <input> FROM projects [WHERE ...] [GROUP BY ...] [ORDER BY ...] [LIMIT ...]`. |
| `proj run <cmd> [--where ...] [--parallel] [--summary] [--only-matches] [--only-failures] [--dry-run]` | Run shell command in each matching project (cwd set to project path). Exit code = number of failures. |
| `proj adopt [<subdir>]` | Interactively promote an unknown subdirectory to a declared project. Prompts for tags. Writes to manifest. |
| `proj forget <name>` | Remove a project entry from the manifest. Does not touch the filesystem. |
| `proj new <template> <name>` | Run template's `cmds` with `{{var}}` interpolation, auto-add to manifest with template's tags. |

### Bundled default commands

Shipped as a real, user-visible YAML file at `proj/defaults.yaml` inside the installed package — i.e., something like `<site-packages>/proj/defaults.yaml`. Merged before the user's manifest; users override by redefining the same key.

Discoverability:
- `proj defaults` prints the file's contents to stdout. Redirect to a file (`proj defaults > my-starter.yaml`) to use as a starting point.
- `proj defaults --path` prints the absolute path to the shipped file so users can `cat`, `less`, or symlink it.
- The file is intentionally readable: it documents the schema by example. New users can `proj defaults` and see exactly what `ls`, `status`, `clean`, `audit`, `archive`, the bundled marks, and the column registry look like.

The file is part of the package and read-only at its install path; user customizations live in `~/.config/proj/projects.yaml`.

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
        mode: applicable
        columns: [has_readme, has_license]
        on_pass: hide
        on_fail: mark-bad
        on_error: mark-warn
        on_na: hide

  archive:
    type: run
    cmd:
      - cd {{path}} && [ -n "{{clean_target}}" ] && {{clean_target}} || true
      - tar -C {{workspace_root}} -caf {{archive_dir}}/{{name}}.tar.zst {{name}}
      - rm -rf {{path}}
      - proj forget {{name}}
```

### `query`-type command schema

```yaml
<name>:
  type: query
  columns: [<col>, ...]              # required; output columns
  grouped_columns:                   # optional; per-row multi-line cell projections
    <output_col_name>:
      mode: applicable | all
      columns: [<col>, ...]
      on_pass:  hide | <mark-name>   # default mark-good
      on_fail:  hide | <mark-name>   # default mark-bad
      on_error: hide | <mark-name>   # default mark-warn
      on_na:    hide | <mark-name>   # default mark-ignored
  where: <sql-expr>                  # optional; merged with --where via AND
  order_by: <col-or-expr>            # optional
  limit: <int>                       # optional
```

### `run`-type command schema

```yaml
<name>:
  type: run
  cmd: <shell-command> | [<shell-command>, ...]   # required; string or list (sequential, fail on first non-zero)
  where: <sql-expr>                  # optional; merged with --where via AND
  parallel: <bool>                   # optional; default from settings.parallel
  summary: <bool>                    # optional; default false
  scope: <single|aggregate>          # optional; overrides type default
```

Variable interpolation in `cmd` uses `{{name}}` for any column **or** any per-project variable (declared in the project's manifest entry). Any column referenced is auto-required (added to materialization), so `cmd: "cd {{path}} && {{clean_target}}"` causes `clean_target` to be evaluated for each row. `{{name}}`, `{{path}}`, `{{workspace_root}}`, and `{{archive_dir}}` are auto-injected.

When `cmd` is a list, each entry runs as a separate shell invocation in sequence; first non-zero exit halts further steps for that project (subsequent projects still run unless `--summary` already failed).

`--dry-run` is available on all `run`-type commands and the `run` primitive: prints the interpolated command(s) per project without executing.

**Note on `--group-by` vs `grouped_columns`:** unrelated. `--group-by` is SQL `GROUP BY` (aggregates rows). `grouped_columns` is a per-row Python-side projection that combines multiple input columns into one multi-line output cell.

### Invocation context

`proj` is invokable from anywhere on the filesystem. Scope is determined by **command type**:

- **`run`-type commands** (and the `run` primitive) default to **single-project** when invoked inside a project: auto-scope to the current project.
- **`query`-type commands** (and the `query` primitive) default to **aggregate**: always cover the workspace regardless of cwd.
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
- **Fixed command set** — `list`, `status`, `clean`, `audit`, `dust`, `archive` are now user-overridable commands shipped as defaults; the spec keeps their semantics intact but they're no longer hardcoded.
- **Standalone `dust` command** — covered by the bundled `ls` default plus `proj query`; users can add a personal `dust` command if they want a specialized one.
- **Separate aggregate command** — collapses into `proj query` with `GROUP BY`.
- **Special "checks" concept** — checks are just boolean columns; audit is a query with a grouped projection.
- **`proj archive --restore`** — restore is now manual: `tar xzf` plus `proj adopt`. Can be added later as a bundled `restore` command if it earns its weight.

## v1 scope cuts (designed for, not built)

- AI-driven `proj new` (users can already invoke `claude` from a template's `cmds`)
- Plugin/extension system for built-in columns
- Concurrent cache writes (single-process v1; file lock if/when needed)
- Additional grouped-column modes/symbols beyond `applicable`/`all` and the three marks
- `proj config dump` to show effective merged config

## Open implementation notes

- **Cache key** for user-defined columns includes a hash of `value-from` (and `applies-when`, if present) so editing either invalidates entries. The `_applies` result caches separately under key `<name>__applies` (double underscore distinguishes from a hypothetical column literally named `name_applies` — though that name is reserved).
- **Reserved suffix**: column names ending in `_applies` are rejected at manifest load.
- **Parallel runs** share the cache via per-key file lock.
- **Tag column declaration**: when materializing the schema, the set of all tags referenced in any project's `tags:` is collected; each becomes a non-virtual INTEGER column, populated at INSERT.
- **`--where` from CLI and command-level `where:`** combine via `AND`.
- **`path:` resolution** at manifest load: `~` expands to home; relative paths resolve against `workspace.root`; absolute paths are used as-is. Paths outside `workspace.root` are allowed but disable cwd-based auto-scoping for those projects.
- **Boolean values in queries**: SQLite has no real boolean — `where dirty` and `where dirty = 1` are equivalent; `not dirty` works as `dirty = 0 OR dirty IS NULL` only if you mean it that way, otherwise prefer `dirty = 0`.
