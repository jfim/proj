# proj v3 — Grouped columns + marks Implementation Plan

**Goal:** Make `proj audit` shine. After this plan lands, a `query`-type command can declare `grouped_columns:` producing multi-line cells that summarize N input boolean columns into a `passed/total` count plus per-column pass/fail/error/NA lines, each rendered with a configurable **mark** (prefix/suffix/color).

**Architecture:**
- New `grouped_columns:` block on `QueryCommand`. At command-build time, auto-project each input column and its `_applies` partner into the SELECT (whether or not the user listed them in `columns:`).
- New `Mark` dataclass + bundled defaults (`mark-good`, `mark-bad`, `mark-warn`, `mark-ignored`). Marks may be redefined in the manifest with whole-record replacement.
- New `marks:` top-level config in `defaults.yaml` and accepted in the user manifest.
- Comparison-expression input columns: an entry of `grouped_columns.<g>.columns` matching `^\s*([\w-]+)\s*(=|!=|<=|>=|<|>)\s*([\w-]+)\s*$` desugars to a derived boolean expression with `_applies = a_applies AND b_applies`.
- Python-side formatter (lives in `output.py` or a new `grouped.py`) walks rows post-fetch and emits multi-line cells. Rich rendering for the table format.
- Bundle `audit` (hide passes + NA) and `checks` (show all) commands.

**Tech Stack:** Existing — pyyaml, rich, click, sqlite3. No new dependencies.

**Out of scope** (deferred):
- `mode:` values beyond `applicable`/`all`
- Symbols/states beyond pass/fail/error/NA
- `IS NULL`/`IS NOT NULL` in comparison expressions
- Per-cell user-supplied rendering callbacks

---

## File Structure

```
src/proj/
  marks.py               # NEW: Mark dataclass + parse_marks + bundled defaults
  grouped.py             # NEW: grouped-column formatter + SELECT augmentation
  defaults.yaml          # EXTEND: add `marks:` block + `audit`/`checks` commands
  commands.py            # EXTEND: QueryCommand carries grouped_columns
  cli.py                 # EXTEND: query-command synth augments SELECT, post-processes rows
  output.py              # EXTEND: pass `grouped_columns` config to formatters

tests/
  test_marks.py          # NEW
  test_grouped.py        # NEW (formatter, expression parser, SELECT augmentation)
  test_cli_audit.py      # NEW (end-to-end `proj audit` / `proj checks`)
```

---

## Task 1: `Mark` dataclass + parsing + bundled defaults

**Files:** `src/proj/marks.py` (new), `tests/test_marks.py` (new), `src/proj/defaults.yaml` (extend).

- [ ] **Step 1: Tests**

```python
# tests/test_marks.py
import pytest
from proj.marks import Mark, parse_marks, BUNDLED_MARKS, merge_marks


def test_bundled_marks_present():
    assert {"mark-good", "mark-bad", "mark-warn", "mark-ignored"} <= set(BUNDLED_MARKS)


def test_parse_marks_full_fields():
    parsed = parse_marks({"mark-fire": {"prefix": "🔥 ", "suffix": "!", "color": "red"}})
    assert parsed["mark-fire"] == Mark(prefix="🔥 ", suffix="!", color="red")


def test_parse_marks_defaults_empty_when_omitted():
    parsed = parse_marks({"x": {"color": "green"}})
    assert parsed["x"].prefix == ""
    assert parsed["x"].suffix == ""


def test_merge_marks_whole_record_replacement():
    """Per spec: user override replaces the entire mark (no field merging)."""
    user = parse_marks({"mark-good": {"prefix": "✅ "}})
    merged = merge_marks(BUNDLED_MARKS, user)
    assert merged["mark-good"].prefix == "✅ "
    assert merged["mark-good"].color == ""   # user did not specify, no inheritance from bundled


def test_parse_marks_rejects_non_string_fields():
    with pytest.raises(ValueError):
        parse_marks({"x": {"prefix": 42}})
```

- [ ] **Step 2: `src/proj/marks.py`**

```python
"""Visual marks for grouped-column cells."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Mark:
    prefix: str = ""
    suffix: str = ""
    color: str = ""


BUNDLED_MARKS: dict[str, Mark] = {
    "mark-good":    Mark(prefix="✓ ", suffix="",            color="green"),
    "mark-bad":     Mark(prefix="✗ ", suffix="",            color="red"),
    "mark-warn":    Mark(prefix="⚠ ", suffix="",            color="yellow"),
    "mark-ignored": Mark(prefix="",   suffix=" (ignored)",  color="grey50"),
}


def parse_marks(raw: dict[str, Any] | None) -> dict[str, Mark]:
    if not raw:
        return {}
    out: dict[str, Mark] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"mark {name!r}: must be a mapping")
        for field in ("prefix", "suffix", "color"):
            if field in body and not isinstance(body[field], str):
                raise ValueError(f"mark {name!r}: {field} must be a string")
        out[name] = Mark(
            prefix=body.get("prefix", ""),
            suffix=body.get("suffix", ""),
            color=body.get("color", ""),
        )
    return out


def merge_marks(defaults: dict[str, Mark], user: dict[str, Mark]) -> dict[str, Mark]:
    """Whole-record override — user wins, no field merging."""
    merged = dict(defaults)
    merged.update(user)
    return merged
```

- [ ] **Step 3: Extend `defaults.yaml`** with a `marks:` block declaring the four bundled marks (so `proj defaults` reveals them; the in-code `BUNDLED_MARKS` remains the source of truth — the YAML is documentation-by-example and loaded for consistency).

---

## Task 2: Comparison expression parser

**Files:** `src/proj/grouped.py` (new), `tests/test_grouped.py` (new).

- [ ] **Step 1: Tests**

```python
# tests/test_grouped.py (partial)
import pytest
from proj.grouped import parse_input_column, ComparisonExpr, ColumnRef


def test_parse_bare_column():
    p = parse_input_column("has_readme")
    assert p == ColumnRef("has_readme")


def test_parse_hyphenated_column():
    p = parse_input_column("otp-version")
    assert p == ColumnRef("otp-version")


@pytest.mark.parametrize("op", ["=", "!=", "<", ">", "<=", ">="])
def test_parse_comparison(op):
    p = parse_input_column(f"a {op} b")
    assert p == ComparisonExpr("a", op, "b")


def test_parse_comparison_no_whitespace():
    assert parse_input_column("a=b") == ComparisonExpr("a", "=", "b")


def test_label_for_comparison():
    expr = ComparisonExpr("deployed_version", "=", "source_version")
    assert expr.label() == "deployed_version = source_version"


def test_label_for_columnref():
    assert ColumnRef("has_readme").label() == "has_readme"
```

- [ ] **Step 2: `grouped.py` parser**

```python
"""Grouped-column SELECT augmentation + post-fetch formatter."""
from __future__ import annotations
import re
from dataclasses import dataclass

_COMPARISON_RE = re.compile(r"^\s*([\w-]+)\s*(=|!=|<=|>=|<|>)\s*([\w-]+)\s*$")


@dataclass(frozen=True)
class ColumnRef:
    name: str
    def label(self) -> str: return self.name


@dataclass(frozen=True)
class ComparisonExpr:
    left: str
    op: str
    right: str
    def label(self) -> str: return f"{self.left} {self.op} {self.right}"


InputColumn = ColumnRef | ComparisonExpr


def parse_input_column(expr: str) -> InputColumn:
    m = _COMPARISON_RE.match(expr)
    if m:
        return ComparisonExpr(m.group(1), m.group(2), m.group(3))
    if not re.match(r"^[\w-]+$", expr.strip()):
        raise ValueError(f"grouped_columns.columns entry not a valid column or comparison: {expr!r}")
    return ColumnRef(expr.strip())
```

---

## Task 3: SELECT augmentation

For each input column referenced in a grouped column, the SELECT must include the value AND the `_applies` partner. For comparison expressions, project two synthesized expressions: `(<a> <op> <b>) AS "<label>"` and `(<a>_applies AND <b>_applies) AS "<label>_applies"`.

- [ ] **Step 1: Tests**

```python
# tests/test_grouped.py (continued)
from proj.grouped import build_grouped_selects, GroupedColumnConfig


def test_build_selects_for_columnref():
    gc = GroupedColumnConfig(name="audit", mode="applicable", inputs=[ColumnRef("has_readme")],
                             on_pass="hide", on_fail="mark-bad", on_error="mark-warn", on_na="hide")
    selects = build_grouped_selects([gc])
    # Two columns (value + applies); order: pairs together.
    assert any('has_readme' in s for s in selects)
    assert any('has_readme_applies' in s for s in selects)


def test_build_selects_dedupes_across_groups():
    g1 = GroupedColumnConfig(name="a", mode="all", inputs=[ColumnRef("x")], ...)
    g2 = GroupedColumnConfig(name="b", mode="all", inputs=[ColumnRef("x")], ...)
    selects = build_grouped_selects([g1, g2])
    # Just one (x, x_applies) pair.
    assert sum(1 for s in selects if "x_applies" in s) == 1


def test_build_selects_for_comparison_emits_labeled_pair():
    expr = ComparisonExpr("a", "=", "b")
    gc = GroupedColumnConfig(name="g", mode="all", inputs=[expr], ...)
    selects = build_grouped_selects([gc])
    label = expr.label()
    assert any(f'AS "{label}"' in s for s in selects)
    assert any(f'AS "{label}_applies"' in s for s in selects)
```

- [ ] **Step 2:** Implement `GroupedColumnConfig` dataclass + `build_grouped_selects(configs) -> list[str]` (each list element is a fragment to be joined with `,` into the SELECT clause). Use existing `engine._ref` for safe quoting.

---

## Task 4: `QueryCommand` extension + bundled `audit`/`checks`

- [ ] **Step 1:** Extend `QueryCommand` with `grouped_columns: list[GroupedColumnConfig]` (default empty). Extend `parse_commands` to parse the `grouped_columns:` mapping.
- [ ] **Step 2:** Add bundled commands to `defaults.yaml`:

```yaml
commands:
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

  checks:
    type: query
    columns: [name]
    grouped_columns:
      checks:
        mode: all
        columns: [has_readme, has_license]
        on_pass: mark-good
        on_fail: mark-bad
        on_error: mark-warn
        on_na: mark-ignored
```

- [ ] **Step 3:** Tests for the parser extension (`test_commands.py` additions).

---

## Task 5: Formatter — multi-line cells with marks

**Files:** `src/proj/grouped.py` (extend), `src/proj/output.py` (extend), `tests/test_grouped.py` (extend), `tests/test_output.py` (extend).

A new function `format_grouped_cell(config, row_dict, marks) -> list[(text, mark_or_None)]` returns the lines for one row's grouped cell. The first line is the count summary (`"3/3"` or `"2/3"`); subsequent lines are per-input lines for inputs whose state isn't `hide`.

- [ ] **Step 1: Tests for the formatter logic**

```python
# tests/test_grouped.py (continued)
def test_format_grouped_cell_all_pass_applicable_mode():
    """3 inputs, all apply, all pass, on_pass=hide → just '3/3'."""
    cfg = GroupedColumnConfig(name="audit", mode="applicable",
                              inputs=[ColumnRef("a"), ColumnRef("b"), ColumnRef("c")],
                              on_pass="hide", on_fail="mark-bad",
                              on_error="mark-warn", on_na="hide")
    row = {"a": 1, "a_applies": 1, "b": 1, "b_applies": 1, "c": 1, "c_applies": 1}
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines[0][0] == "3/3"
    assert len(lines) == 1


def test_format_grouped_cell_mixed_states():
    cfg = GroupedColumnConfig(name="audit", mode="applicable",
                              inputs=[ColumnRef("a"), ColumnRef("b"), ColumnRef("c")],
                              on_pass="hide", on_fail="mark-bad",
                              on_error="mark-warn", on_na="mark-ignored")
    row = {"a": 1, "a_applies": 1,   # pass → hide
           "b": 0, "b_applies": 1,   # fail → mark-bad
           "c": None, "c_applies": 0}  # n/a → mark-ignored
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines[0][0] == "1/2"  # applicable mode: 1 pass / 2 applicable
    assert any("b" in t for t, _ in lines)
    assert any("c" in t for t, _ in lines)


def test_format_grouped_cell_mode_all_counts_total():
    cfg = GroupedColumnConfig(name="g", mode="all",
                              inputs=[ColumnRef("a"), ColumnRef("b")],
                              on_pass="mark-good", on_fail="mark-bad",
                              on_error="mark-warn", on_na="mark-ignored")
    row = {"a": 1, "a_applies": 1, "b": None, "b_applies": 0}
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines[0][0] == "1/2"   # mode all: 1/(total inputs)


def test_format_grouped_cell_error_state():
    cfg = GroupedColumnConfig(name="g", mode="applicable",
                              inputs=[ColumnRef("a")],
                              on_pass="hide", on_fail="hide",
                              on_error="mark-warn", on_na="hide")
    row = {"a": None, "a_applies": 1}
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert "a" in lines[1][0]
    assert lines[1][1].prefix == "⚠ "
```

- [ ] **Step 2: Implement `format_grouped_cell`.** Determine per-input state from `(applies, value)`; look up the mark key from the config (`on_pass`/`on_fail`/`on_error`/`on_na`); resolve to a `Mark` via the merged marks registry.

- [ ] **Step 3:** Extend `output.py`'s `_format_table` to accept grouped-column configs + marks. When a row has grouped cells, emit multi-line content using rich's newline-joined text spans with the mark's color applied. For `plain` and `json` formats, render the count summary as the cell value and emit one extra line per per-input line (plain) or include a nested list (json).

---

## Task 6: End-to-end `proj audit` integration

- [ ] **Step 1: Tests in `tests/test_cli_audit.py`**

```python
# Bundled audit hides passes / NA, shows fails + errors.
def test_audit_shows_only_failures(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "good").mkdir(); (ws / "good" / "README.md").write_text("hi"); (ws / "good" / "LICENSE").write_text("apache")
    (ws / "bad").mkdir(); (ws / "bad" / "README.md").write_text("hi")  # no LICENSE
    m = tmp_path / "projects.yaml"; m.write_text(yaml.safe_dump({
        "workspace": {"root": str(ws)},
        "projects": {"good": {"tags": []}, "bad": {"tags": []}},
    }))
    r = CliRunner().invoke(main, [
        "--manifest", str(m), "--cache-dir", str(tmp_path),
        "audit", "--format", "plain",
    ])
    assert r.exit_code == 0, r.output
    assert "has_license" in r.output    # bad project's missing license shows
    assert "✓" not in r.output          # passes hidden


def test_user_grouped_command_with_comparison(tmp_path):
    """Define a custom command using a comparison expression."""
    # ... user defines:
    #   deploy_ok:
    #     type: query
    #     columns: [name]
    #     grouped_columns:
    #       deploy_status:
    #         mode: all
    #         columns: [deployed_version = source_version]
    #         on_pass: hide
    #         on_fail: mark-bad
```

- [ ] **Step 2:** Wire `_make_query_click` to:
  1. Auto-append the grouped-column SELECT fragments to `spec.columns` before calling `build_query`.
  2. Pass `spec.grouped_columns` + merged marks into `format_rows`.
  3. The formatter knows which output columns are "raw projected from grouped configs" vs. user-declared, so it can hide the raw projection columns from the visible output (only the synthesized grouped cell shows).

---

## Task 7: Final integration

- [ ] Full test suite passes.
- [ ] `uv run ruff check` / `uv run ruff format` clean.
- [ ] Smoke test: create a workspace, run `proj audit` and `proj checks`, eyeball the output.
- [ ] README: add `proj audit` example showing the multi-line dashboard.
- [ ] ROADMAP: mark Plan C as shipped.

## Risk Notes

- **Auto-projected columns vs. user's `columns:`** is the subtle piece. Implementation: build a SELECT clause with two parts — `user_columns + auto_projections` — and have the formatter know which output indices belong to which grouped cell. The user-facing column list (rendered in the table header) is `user_columns + grouped_column_names`. Auto-projections are stripped from the output.
- **Rich color spec** vary across terminals; mark colors that don't resolve should fall back to plain text (rich handles this).
- **Hyphenated column names in comparisons** (`otp-version = source-version`) — quote both sides via `_ref` when emitting SQL, but use the raw label for the rendered cell line.
