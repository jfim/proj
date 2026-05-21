import io
import json

import pytest

from proj.output import format_rows


def test_plain_format_outputs_tabs():
    out = io.StringIO()
    format_rows([("a", "b"), ("c", "d")], headers=["x", "y"], fmt="plain", file=out)
    assert out.getvalue() == "a\tb\nc\td\n"


def test_plain_format_handles_none():
    out = io.StringIO()
    format_rows([(None, 1)], headers=["x", "y"], fmt="plain", file=out)
    assert out.getvalue() == "\t1\n"


def test_json_format_emits_array_of_objects():
    out = io.StringIO()
    format_rows([(1, "a"), (2, "b")], headers=["id", "name"], fmt="json", file=out)
    data = json.loads(out.getvalue())
    assert data == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


def test_json_handles_none():
    out = io.StringIO()
    format_rows([(None, 1)], headers=["x", "y"], fmt="json", file=out)
    assert json.loads(out.getvalue()) == [{"x": None, "y": 1}]


def test_table_format_contains_headers_and_values():
    out = io.StringIO()
    format_rows([("a", "b")], headers=["X", "Y"], fmt="table", file=out)
    s = out.getvalue()
    assert "X" in s and "Y" in s and "a" in s and "b" in s


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        format_rows([], headers=[], fmt="bogus")
