# proj — Roadmap

**Design reference:** [`specs/2026-05-20-proj-design.md`](specs/2026-05-20-proj-design.md)

This document tracks what's been shipped, what's deferred, and how the remaining work is sliced into follow-up implementation plans. Each follow-up plan should produce working, testable software on its own and slot into the architecture defined in the design spec.

---

## What's shipped (v1.5)

Plan F — polish:

- Column-value interpolation in `run`-type `cmd` (any `{{column}}` reference auto-queries the projects table per-row; unblocks the bundled `clean`/`archive` commands)
- Per-project variable interpolation in `cmd` (`{{host}}`, etc.)
- `proj run --parallel` (thread-pool concurrency, bounded to 8)
- `proj run --summary` pass/fail table at end
- Auto-scoping: invoked inside a workspace project, `proj run` defaults to that project; `--all` forces workspace, `--here` is explicit single-project
- `~/.projrc` user-wide overlay merged between defaults.yaml and the workspace manifest

## What's shipped (v1.4)

Plan E — templates and `proj new`:

- `templates:` section in manifest with `tags:` and `cmds:` (sequential shell strings)
- `{{name}}`, `{{workspace_root}}`, `{{date}}` interpolation in template cmds
- `proj new <template> <name>` runs cmds from `workspace.root`, halts on first failure (partial state preserved), auto-adopts on success
- `--dry-run` flag

## What's shipped (v1.3)

Plan D — unknown subdirectories and `proj adopt`:

- Workspace auto-scan at engine build: any subdirectory not declared in `projects:` appears as a row with `unknown = 1`
- `settings.unknown_handling`: `include` (default) / `warn` (stderr footer counting unknowns) / `ignore` (excluded entirely)
- `proj adopt [SUBDIR] [--tags T,U,V]` interactive promotion; `--list` prints unknowns without prompting; no-arg form picks from a numbered list
- Manifest mutations (`adopt`, `forget`) migrated to ruamel.yaml — comments and ordering preserved on round-trip
- `Manifest.raw_marks` carried through; `Project.unknown` field on the registry

## What's shipped (v1.2)

Delivered by [`plans/2026-05-21-proj-v3-grouped-columns.md`](plans/2026-05-21-proj-v3-grouped-columns.md):

- `grouped_columns:` schema on `query`-type commands with `mode: applicable|all`, `columns:`, `on_pass`/`on_fail`/`on_error`/`on_na`
- Comparison-expression inputs (`a = b`, `a != b`, `a <= b`, ...) with auto-`_applies` from both sides
- Marks system: `marks:` top-level block with `prefix`/`suffix`/`color`; four bundled marks; whole-record override
- Bundled `audit` (passes hidden) and `checks` (all states shown) commands
- Rich-rendered multi-line cells with color; plain and json formats also supported
- `Manifest.raw_marks` field

## What's shipped (v1.1)

Delivered by [`plans/2026-05-21-proj-v2-commands-as-config.md`](plans/2026-05-21-proj-v2-commands-as-config.md):

- `proj init [DIRECTORY]` — bootstrap a manifest from a directory of subdirectories
- Bundled `defaults.yaml` shipped inside the package (`ls`, `status`, `clean`, `archive`)
- `proj defaults` / `proj defaults --path` for discoverability
- `proj run <cmd>` primitive with `--where`, `--dry-run`, `{{name}}`/`{{path}}`/`{{workspace_root}}`/`{{archive_dir}}` interpolation, exit-code = failure count
- `proj forget <name>` primitive (manifest edit; plain pyyaml — comment preservation deferred to Plan D when adopt lands)
- `proj adopt` / `proj new` stubs (error with "not yet implemented")
- User-overridable commands in a `commands:` block: `type: query` or `type: run`, `cmd:` as string or list (sequential, fail-on-first-error), CLI `--where` AND-merges with command's `where:`
- Dynamic CLI dispatch: unknown subcommand names resolve against merged defaults+user commands
- `Manifest.raw_commands` field exposed alongside existing `projects`/`columns`/`settings`

## What's shipped (v1.0)

Delivered by [`plans/2026-05-21-proj-v1-query-engine.md`](plans/2026-05-21-proj-v1-query-engine.md):

- Global manifest at `~/.config/proj/projects.yaml` with `workspace.root`, `projects`, `columns`, `settings`
- Project entries with arbitrary user variables and optional `path:` override
- Column registry: built-in baseline (`name`, `path`, `last_modified`), built-in extended (`size`, `dirty`, `branch`, `ahead`, `behind`, `last_commit`, `clean_target`, `lang_*`, `has_*`, `git`), user-defined columns with `applies-to`, `applies-when`, `value-from`, `type`, `cache`
- Tag normalization (`lang:elixir` → `lang_elixir`); `_applies` suffix reserved
- In-memory SQLite engine with paired `<name>` / `<name>_applies` virtual columns
- Two dispatch functions: `get_column_value` and `get_column_applies`
- On-disk cache at `~/.cache/proj/cache.db`, keyed by post-interpolation command hash
- `{{var}}` interpolation in column shell commands (auto-injected: `name`, `path`, `workspace_root`)
- SQL helpers: `gb()`, `mb()`, `kb()`, `ago()`
- `proj query <cols-or-select>` with `--where`, `--order-by`, `--group-by`, `--limit`, `--format {table,json,plain}`
- Type coercion (`text|integer|boolean|real`) with None-on-failure

The user can install, drop a manifest, and run real SQL against their workspace today.

---

## What's left

All five follow-up plans (B–F) shipped. Remaining design-spec scope cuts (intentionally deferred from v1):

- AI-driven `proj new` (users can already invoke `claude` from a template's `cmds`)
- Plugin/extension system for built-in columns
- Per-key file locks for concurrent cache writes (single-process for now; parallel mode shares an in-memory engine within one process)
- `--only-matches`, `--only-failures` filters on `proj run`
- Progress indicator when >5 uncached expensive columns are about to be evaluated
- Explicit `settings.color: auto|always|never` (rich auto-detects today)
- `proj config dump` to show effective merged config
- `proj archive --restore`

---

## Plans (all shipped)

- [Plan B — Commands as config](plans/2026-05-21-proj-v2-commands-as-config.md)
- [Plan C — Grouped columns and marks](plans/2026-05-21-proj-v3-grouped-columns.md)
- Plans D/E/F (no separate plan docs; implemented incrementally from the design spec)
