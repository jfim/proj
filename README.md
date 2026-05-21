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

Create a `projects.yaml` at your workspace root:

```yaml
workspace:
  root: ~/projects
  defaults:
    stale_threshold: 6mo
    large_threshold: 50mb

projects:
  my-cool-lib:
    tags: [oss, mine, rust, library]
  pandas-fork:
    tags: [oss, not-mine, python]

checks:
  has-readme:
    run: test -f README.md
    tags: [mine]
    description: "project has a README"
```

Then:

```bash
proj list --tag mine
proj status --filter dirty
proj run --tag rust 'cargo fmt --check'
proj audit
proj dust --stale 6mo --min-size 50mb
proj clean --dry-run
```

## Commands

| Command | Purpose |
|---|---|
| `proj list` | List projects, filtered by tag. |
| `proj run <cmd>` | Run a shell command in each matching project. |
| `proj status` | Pretty-printed git status across matching projects. |
| `proj audit` | Run defined checks and display a dashboard. |
| `proj dust` | Disk usage report, sorted by size. |
| `proj clean` | Run each project's clean target. |
| `proj archive` | Move stale projects to a compressed archive. |

Run `proj <command> --help` for full options.

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
