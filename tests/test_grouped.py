"""Tests for grouped-column parsing, SELECT augmentation, and formatting."""

from __future__ import annotations

import pytest

from proj.grouped import (
    ColumnRef,
    ComparisonExpr,
    GroupedColumnConfig,
    Line,
    build_grouped_selects,
    format_grouped_cell,
    parse_grouped_columns,
    parse_input_column,
)
from proj.marks import BUNDLED_MARKS


def _cfg(
    name="g",
    mode="applicable",
    inputs=None,
    on_pass="hide",
    on_fail="mark-bad",
    on_error="mark-warn",
    on_na="hide",
):
    if inputs is None:
        inputs = (ColumnRef("a"),)
    return GroupedColumnConfig(
        name=name,
        mode=mode,
        inputs=tuple(inputs),
        on_pass=on_pass,
        on_fail=on_fail,
        on_error=on_error,
        on_na=on_na,
    )


# ---------- parser ----------


def test_parse_bare_column() -> None:
    assert parse_input_column("has_readme") == ColumnRef("has_readme")


def test_parse_hyphenated_column() -> None:
    assert parse_input_column("otp-version") == ColumnRef("otp-version")


@pytest.mark.parametrize("op", ["=", "!=", "<", ">", "<=", ">="])
def test_parse_comparison(op: str) -> None:
    assert parse_input_column(f"a {op} b") == ComparisonExpr("a", op, "b")


def test_parse_comparison_no_whitespace() -> None:
    assert parse_input_column("a=b") == ComparisonExpr("a", "=", "b")


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_input_column("a + b")


def test_label_for_comparison() -> None:
    assert ComparisonExpr("a", "=", "b").label() == "a = b"


def test_label_for_columnref() -> None:
    assert ColumnRef("x").label() == "x"


def test_parse_grouped_columns_full() -> None:
    cfgs = parse_grouped_columns(
        {
            "audit": {
                "mode": "applicable",
                "columns": ["has_readme", "has_license"],
                "on_pass": "hide",
                "on_fail": "mark-bad",
            }
        }
    )
    assert len(cfgs) == 1
    assert cfgs[0].name == "audit"
    assert cfgs[0].mode == "applicable"
    assert cfgs[0].on_pass == "hide"
    assert cfgs[0].on_fail == "mark-bad"
    # Defaults filled in for unspecified slots
    assert cfgs[0].on_error == "mark-warn"
    assert cfgs[0].on_na == "mark-ignored"


def test_parse_grouped_columns_rejects_bad_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        parse_grouped_columns({"g": {"mode": "weird", "columns": ["a"]}})


def test_parse_grouped_columns_rejects_empty_columns() -> None:
    with pytest.raises(ValueError, match="columns"):
        parse_grouped_columns({"g": {"mode": "all", "columns": []}})


# ---------- SELECT augmentation ----------


def test_build_selects_for_columnref() -> None:
    selects = build_grouped_selects([_cfg(inputs=[ColumnRef("has_readme")])])
    joined = " ".join(selects)
    assert "has_readme" in joined
    assert "has_readme_applies" in joined


def test_build_selects_dedupes_across_groups() -> None:
    g1 = _cfg(name="a", inputs=[ColumnRef("x")])
    g2 = _cfg(name="b", inputs=[ColumnRef("x")])
    selects = build_grouped_selects([g1, g2])
    assert sum(1 for s in selects if "x_applies" in s) == 1


def test_build_selects_for_comparison_emits_labeled_pair() -> None:
    expr = ComparisonExpr("a", "=", "b")
    selects = build_grouped_selects([_cfg(inputs=[expr])])
    joined = " ".join(selects)
    assert '"a = b"' in joined
    assert '"a = b_applies"' in joined


# ---------- formatter ----------


def test_format_grouped_cell_all_pass_applicable_hides_passes() -> None:
    cfg = _cfg(
        inputs=[ColumnRef("a"), ColumnRef("b"), ColumnRef("c")],
        on_pass="hide",
    )
    row = {
        "a": 1,
        "a_applies": 1,
        "b": 1,
        "b_applies": 1,
        "c": 1,
        "c_applies": 1,
    }
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines == [Line(text="3/3", mark=None)]


def test_format_grouped_cell_mixed_states_applicable_mode() -> None:
    cfg = _cfg(
        inputs=[ColumnRef("a"), ColumnRef("b"), ColumnRef("c")],
        on_pass="hide",
        on_fail="mark-bad",
        on_error="mark-warn",
        on_na="mark-ignored",
    )
    row = {
        "a": 1,
        "a_applies": 1,  # pass → hidden
        "b": 0,
        "b_applies": 1,  # fail → mark-bad
        "c": None,
        "c_applies": 0,  # n/a → mark-ignored
    }
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines[0] == Line(text="1/2", mark=None)  # applicable: 1 pass / 2 applicable
    detail_texts = [line.text for line in lines[1:]]
    assert "b" in detail_texts
    assert "c" in detail_texts


def test_format_grouped_cell_mode_all_counts_total() -> None:
    cfg = _cfg(
        mode="all",
        inputs=[ColumnRef("a"), ColumnRef("b")],
        on_pass="mark-good",
        on_fail="mark-bad",
        on_error="mark-warn",
        on_na="mark-ignored",
    )
    row = {"a": 1, "a_applies": 1, "b": None, "b_applies": 0}
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines[0].text == "1/2"


def test_format_grouped_cell_error_state_uses_warn_mark() -> None:
    cfg = _cfg(
        inputs=[ColumnRef("a")],
        on_pass="hide",
        on_fail="hide",
        on_error="mark-warn",
        on_na="hide",
    )
    row = {"a": None, "a_applies": 1}
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert len(lines) == 2
    assert lines[1].text == "a"
    assert lines[1].mark is not None
    assert lines[1].mark.prefix == "⚠ "


def test_format_grouped_cell_unknown_mark_key_defaults_to_blank_mark() -> None:
    cfg = _cfg(inputs=[ColumnRef("a")], on_fail="mark-does-not-exist")
    row = {"a": 0, "a_applies": 1}
    lines = format_grouped_cell(cfg, row, BUNDLED_MARKS)
    assert lines[1].text == "a"
    assert lines[1].mark is not None
    assert lines[1].mark.prefix == ""
