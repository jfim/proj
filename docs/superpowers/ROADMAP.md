# proj — Roadmap

**Design reference:** [`specs/2026-05-20-proj-design.md`](specs/2026-05-20-proj-design.md)

This document tracks what's been shipped, what's deferred, and how the remaining work is sliced into follow-up implementation plans. Each follow-up plan should produce working, testable software on its own and slot into the architecture defined in the design spec.

---

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

Five proposed follow-up plans, in suggested implementation order. Each plan corresponds to one or more sections of the design spec.

### Plan B — Commands as config

**Spec sections:** "Commands" (the user-overridable side), "Bundled default commands", "`query`-type command schema", "`run`-type command schema", "Marks" (foundational subset).

**Goal:** Lift the hardcoded `proj query` and add five hardcoded primitives + the user-configurable command layer that's the heart of the design.

**Scope:**
- Five hardcoded primitives:
  - `proj query` (already done — keep)
  - `proj run <cmd>` — exec shell per matching project, `cwd=path`, exit code = number of failures
  - `proj adopt [<subdir>]` — interactive promotion of an unknown subdirectory (depends on Plan D below; can ship as a no-op stub if Plan D not yet built)
  - `proj forget <name>` — remove project entry from manifest
  - `proj new <template> <name>` — defer until Plan E
- User-overridable commands defined in `commands:` section of manifest, with two types: `query` and `run`
- `cmd:` accepts string or list (sequential, fail-on-first-error)
- Variable interpolation in `run`-type `cmd` (`{{path}}`, `{{name}}`, any column value, project vars)
- `--dry-run` flag on `run`-type
- Command resolution: hardcoded primitive wins, else look up `commands.<name>` in merged config
- Ship `proj/defaults.yaml` inside the package with `ls`, `status`, `clean`, `archive` as `query`/`run` commands using existing built-in columns
- `proj defaults` command prints contents; `proj defaults --path` prints absolute path
- Config merge order: defaults.yaml → `~/.projrc` → workspace manifest → CLI flags

**Deliverable:** `proj ls`, `proj status`, `proj clean`, `proj archive` all work out of the box; users can override or add their own (`proj fmt`, `proj pull`).

**Out of scope (still deferred):** grouped columns, marks beyond what's needed for the bundled defaults (which don't yet use grouped columns), `proj adopt`/`proj new`.

### Plan C — Grouped columns and marks

**Spec sections:** "Grouped columns", "Marks", "comparison expressions" subsection.

**Goal:** Make `proj audit` shine with multi-line cells and configurable status symbols.

**Scope:**
- `grouped_columns:` schema on `query`-type commands with `mode: applicable|all`, `columns:`, `on_pass`, `on_fail`, `on_error`, `on_na`
- Auto-projection of input columns and their `_applies` partners into the SELECT
- Python-side formatter that walks rows and emits multi-line cells
- Marks system: `marks:` top-level config with `prefix`, `suffix`, `color`; four bundled defaults (`mark-good`, `mark-bad`, `mark-warn`, `mark-ignored`); whole-record replacement on override
- Rich-based rendering of multi-line cells with color
- Comparison expressions as `grouped_columns.columns:` entries: `a = b`, `a != b`, `a > b`, `a < b`, `a <= b`, `a >= b`. Parser is a single regex; anything not matching is a bare column reference.
- Bundled `audit` and `checks` commands in `defaults.yaml`

**Deliverable:** `proj audit` shows the dashboard from the spec; users can define their own grouped commands.

### Plan D — Unknown subdirectories and `proj adopt`

**Spec sections:** "Unknown subdirectories", "`proj adopt`".

**Goal:** Make undeclared workspace subdirectories first-class citizens.

**Scope:**
- Workspace scan at engine-build time: directories under `workspace.root` not listed in `projects:` get auto-inserted with `unknown = 1`
- `settings.unknown_handling`: `include` (default) / `warn` / `ignore`
- `warn` mode emits a stderr footer counting unknowns
- `ignore` mode excludes unknowns from the projects table entirely
- `proj adopt <subdir>` (interactive): prompts for tags, writes a new entry to the manifest (preserving comments and ordering — use `ruamel.yaml` rather than `pyyaml` for this command only)
- `proj adopt` with no arg: lists unknowns, lets user pick

**Deliverable:** users can run `proj adopt foo`, type a few tags, and the project is in the manifest. Unknowns show up in `proj ls` with a flag.

### Plan E — Templates and `proj new`

**Spec sections:** "Templates", "`proj new`".

**Goal:** Spin up new projects with one command.

**Scope:**
- `templates:` section in manifest with `tags:` and `cmds:` (list of shell strings)
- Variable interpolation: `{{name}}`, `{{workspace_root}}`, `{{date}}`
- `proj new <template> <name>` runs each `cmd` from `workspace.root`, then auto-adopts the new project with the template's tags
- On any step's failure: stop, report which step, leave the partial state in place (user resolves manually)

**Deliverable:** `proj new python-uv my-experiment` creates the directory, runs the template's commands (which can include `claude "scaffold a Python project ..."` per user taste), and adds the entry.

### Plan F — Polish

**Spec sections:** "Invocation context", "parallel" in run schema, settings, "`run` primitive" flag set.

**Goal:** Make `proj` feel like a finished tool.

**Scope:**
- Auto-scoping based on cwd: `run`-type commands invoked inside a project auto-scope to it; `query`-type aggregate by default. `--all` / `--here` overrides. Per-command `scope:` config.
- `proj run --parallel` (and `parallel: true` on user commands): concurrent execution with per-key cache locking
- `proj run --summary`: pass/fail table instead of full per-project output
- `proj run --only-matches`, `--only-failures` filters
- `progress` indicator when >5 uncached expensive columns are about to be evaluated in one query
- Color theme via `settings.color: auto|always|never`
- `proj run` exit code = number of project failures (already in spec; verify it's wired)

**Deliverable:** the tool feels production-grade. Nothing surprising, predictable failure modes.

---

## Suggested ordering rationale

- **Plan B first** because the design's central insight (commands-as-config) only delivers value once users can run `proj ls`, `proj status`, etc. without writing SQL.
- **Plan C** next because audit was specifically called out as a needed feature during brainstorming. It's also a natural showcase for the column model.
- **Plan D and E** are independent of each other; D depends on Plan B's `forget` primitive working but otherwise stands alone. E is a self-contained vertical slice.
- **Plan F** last because it's polish on a working tool; before then, the design's load-bearing pieces aren't all in place to even know what needs polish.

Each plan can be brainstormed independently for any open design questions (e.g., the exact semantics of `--here` when invoked inside a nested git submodule) using [`superpowers:brainstorming`](https://github.com/anthropics/claude-skills/tree/main/superpowers), then expanded into an implementation plan via [`superpowers:writing-plans`](https://github.com/anthropics/claude-skills/tree/main/superpowers).
