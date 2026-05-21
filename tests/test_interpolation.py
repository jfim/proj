import pytest

from proj.interpolation import interpolate


def test_simple_substitution():
    assert interpolate("hello {{name}}", {"name": "world"}) == "hello world"


def test_multiple_substitutions():
    assert interpolate("{{a}} and {{b}}", {"a": "x", "b": "y"}) == "x and y"


def test_repeated_substitution():
    assert interpolate("{{name}}-{{name}}", {"name": "z"}) == "z-z"


def test_hyphenated_key():
    assert interpolate("path: {{deploy-path}}", {"deploy-path": "/var/foo"}) == "path: /var/foo"


def test_missing_var_leaves_literal():
    # We choose: missing variables produce a clear error rather than silent passthrough.
    with pytest.raises(KeyError, match="missing"):
        interpolate("hello {{nope}}", {"name": "x"})


def test_no_substitution_when_no_braces():
    assert interpolate("plain string", {"x": "y"}) == "plain string"


def test_adjacent_substitutions():
    assert interpolate("{{a}}{{b}}", {"a": "1", "b": "2"}) == "12"
