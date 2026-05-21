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

Create a manifest at `~/.config/proj/projects.yaml`:

```yaml
workspace:
  root: ~/projects

projects:
  my-cool-lib: { tags: [mine, library] }
  pandas-fork: { tags: [oss] }
  weekend-game: { tags: [mine, experiment] }
```

Then query your workspace:

```bash
proj query 'name, size, dirty' --where 'mine and lang_rust'
proj query 'name, last_modified' --where 'mine' --order-by 'last_modified desc'
proj query 'lang_rust, count(*)' --group-by lang_rust
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
| `proj query` | ✓ working | Execute SQL against the projects table |
| `proj ls` / `status` / `clean` / `audit` / `archive` | coming soon | User-configurable commands shipped as defaults |
| `proj run` / `adopt` / `forget` / `new` | coming soon | Hardcoded primitives |

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
