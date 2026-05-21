# proj

A CLI for managing a flat directory of heterogeneous projects (OSS checkouts, experiments, datasets, personal code) with tagging, auditing, and cross-project task execution.

## Why

If you keep dozens of unrelated projects in a single `~/projects` directory — forks, experiments, datasets, side projects — you eventually want to ask questions like:

- Which of my Rust projects are dirty?
- Which OSS forks haven't been touched in a year and are over 100MB?
- Are vim swapfiles gitignored in all my own repos?
- How much disk could I reclaim by running `cargo clean` everywhere?

`proj` answers those questions and runs ad-hoc commands across filtered subsets of projects.

## Install

Requires Python 3.10+. Using [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install proj
```

Or from a checkout:

```bash
git clone https://github.com/jfim/proj
cd proj
uv sync
uv run proj --help
```

## Quick start

Bootstrap a manifest from a directory of projects:

```bash
proj init ~/projects                  # treats each subdirectory as a project
```

This writes `~/.config/proj/projects.yaml` with one entry per immediate subdirectory and commented examples for `columns:` and `commands:`. Edit it freely.

Then run a bundled command:

```bash
proj ls                                # list projects + last_modified (defaults.yaml)
proj run 'echo hello from {{name}}'    # run a shell command per project
proj query 'name, size, dirty' --where 'mine and lang_rust'
proj query 'lang_rust, count(*)' --group-by lang_rust
```

`proj ls`, `proj status`, `proj clean`, and `proj archive` are user-overridable commands shipped inside the package — run `proj defaults` to see them, or `proj defaults --path` for the file location. Override any of them by adding a `commands:` block to your manifest:

```yaml
commands:
  ls:                              # override the bundled default
    type: query
    columns: [name, tags, size, last_modified]
    order_by: name
  fmt:                             # invent your own
    type: run
    where: has_justfile
    cmd: just fmt
```

The `query` command runs SQL against an in-memory table where each project is a row. Tags become boolean columns; built-in columns (`size`, `dirty`, `lang_rust`, `lang_python`, `branch`, `last_modified`, …) are computed lazily and cached on disk.

Define your own columns in the manifest:

```yaml
columns:
  has_license:
    applies-to: oss                              # SQL where-expression
    value-from: test -f LICENSE && echo true || echo false
    type: boolean
  otp_version:
    applies-when: test -f .tool-versions          # shell-evaluated gate
    value-from: grep otp .tool-versions | sed 's/.*-otp-//'
    type: text
    cache: true
```

Each non-tag column synthesizes a paired `<name>_applies` column so you can query applicability directly: `proj query 'name, has_license' --where 'has_license_applies and not has_license'`.

Per-project variables are interpolated as `{{var}}` into your column shell commands:

```yaml
projects:
  prod-server-1:
    tags: [deployment]
    host: server-1.tld
columns:
  is_running:
    applies-to: deployment
    value-from: ssh {{host}} 'pgrep -f myapp >/dev/null'
    type: boolean
```

## Commands (v1)

| Command | Status | Purpose |
|---|---|---|
| `proj init` | ✓ working | Bootstrap a manifest from a directory |
| `proj query` | ✓ working | Execute SQL against the projects table |
| `proj run` | ✓ working | Run a shell command per matching project |
| `proj forget` | ✓ working | Remove a project entry from the manifest |
| `proj defaults` | ✓ working | Print the bundled defaults.yaml (or its path) |
| `proj ls` / `status` / `clean` / `archive` | ✓ working | User-overridable bundled commands |
| `proj audit` / `proj checks` | ✓ working | Grouped-column dashboards |
| `proj adopt` | ✓ working | Promote an unknown subdirectory (preserves manifest comments) |
| `proj new` | ✓ working | Scaffold a new project from a template + auto-adopt |

`proj run` supports `--parallel`, `--summary`, `--dry-run`, `--here`/`--all` (auto-scopes to the current project when invoked inside one), and `{{column}}` / `{{var}}` interpolation in `cmd:`. Commands also merge from `~/.projrc` between the bundled defaults and your workspace manifest.

## Audit dashboards

`proj audit` and `proj checks` show grouped-column dashboards: each project gets a count (`passed/total`) plus per-column status lines marked ✓ / ✗ / ⚠. Define your own dashboards under `commands:` with `type: query` and a `grouped_columns:` block — see `proj defaults` for the bundled examples and `marks:` block.

Run `proj query --help` for the full flag list.

## Auto-detected properties

Many properties are derived from the filesystem without manual tagging:

| Property | Detected from |
|---|---|
| `git` | `.git/` |
| `dirty` | `git status --porcelain` non-empty |
| `lang:rust` | `Cargo.toml` |
| `lang:python` | `pyproject.toml`, `setup.py`, `requirements.txt` |
| `lang:js` / `lang:ts` | `package.json` |
| `lang:go` | `go.mod` |
| `has:makefile` | `Makefile` |
| `stale:<duration>` | mtime of most recent file |
| `large:<size>` | total directory size |

## Configuration

Settings are resolved in order (later overrides earlier):

1. `~/.projrc` — user defaults
2. `projects.yaml` `settings:` block — workspace settings
3. CLI flags — per-invocation

## Development

```bash
uv sync
uv run pytest
uv run ruff check
uv run ruff format
```

## Non-goals

- Not a monorepo build tool (no dependency graph, no incremental builds)
- Not a package manager
- Does not manage git remotes or branching
- No daemon or file-watching; all operations are on-demand

## License

Apache License 2.0. See [LICENSE](LICENSE).
