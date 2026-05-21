"""Tests for marks (visual styles for grouped-column cells)."""

from __future__ import annotations

import pytest

from proj.marks import BUNDLED_MARKS, Mark, merge_marks, parse_marks


def test_bundled_marks_present() -> None:
    assert {"mark-good", "mark-bad", "mark-warn", "mark-ignored"} <= set(BUNDLED_MARKS)


def test_bundled_mark_good_has_green() -> None:
    assert BUNDLED_MARKS["mark-good"].color == "green"


def test_parse_marks_full_fields() -> None:
    parsed = parse_marks({"mark-fire": {"prefix": "🔥 ", "suffix": "!", "color": "red"}})
    assert parsed["mark-fire"] == Mark(prefix="🔥 ", suffix="!", color="red")


def test_parse_marks_defaults_empty_when_omitted() -> None:
    parsed = parse_marks({"x": {"color": "green"}})
    assert parsed["x"].prefix == ""
    assert parsed["x"].suffix == ""
    assert parsed["x"].color == "green"


def test_parse_marks_empty_input_returns_empty() -> None:
    assert parse_marks(None) == {}
    assert parse_marks({}) == {}


def test_parse_marks_non_mapping_body_errors() -> None:
    with pytest.raises(ValueError, match="mapping"):
        parse_marks({"x": "red"})


def test_parse_marks_rejects_non_string_fields() -> None:
    with pytest.raises(ValueError, match="prefix"):
        parse_marks({"x": {"prefix": 42}})


def test_merge_marks_whole_record_replacement() -> None:
    """User override replaces entire mark — no field merging."""
    user = parse_marks({"mark-good": {"prefix": "✅ "}})
    merged = merge_marks(BUNDLED_MARKS, user)
    assert merged["mark-good"].prefix == "✅ "
    assert merged["mark-good"].color == ""


def test_merge_marks_adds_new_marks() -> None:
    user = parse_marks({"mark-fire": {"prefix": "🔥 "}})
    merged = merge_marks(BUNDLED_MARKS, user)
    assert "mark-fire" in merged
    assert "mark-good" in merged
