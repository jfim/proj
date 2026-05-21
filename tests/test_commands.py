"""Tests for the command parser and merge logic."""

from __future__ import annotations

import pytest

from proj.commands import (
    HARDCODED_PRIMITIVES,
    QueryCommand,
    RunCommand,
    merge_commands,
    parse_commands,
)


def test_hardcoded_primitives_set() -> None:
    expected = {"query", "run", "adopt", "forget", "new", "defaults", "init"}
    assert set(HARDCODED_PRIMITIVES) == expected


def test_parse_query_command() -> None:
    cmds = parse_commands({"ls": {"type": "query", "columns": ["name"], "order_by": "name"}})
    assert isinstance(cmds["ls"], QueryCommand)
    assert cmds["ls"].columns == ["name"]
    assert cmds["ls"].order_by == "name"


def test_parse_query_command_with_where_and_limit() -> None:
    cmds = parse_commands(
        {
            "biggest": {
                "type": "query",
                "columns": ["name", "size"],
                "where": "mine",
                "limit": 5,
            }
        }
    )
    q = cmds["biggest"]
    assert isinstance(q, QueryCommand)
    assert q.where == "mine"
    assert q.limit == 5


def test_parse_run_command_string_cmd() -> None:
    cmds = parse_commands({"fmt": {"type": "run", "cmd": "just fmt"}})
    assert isinstance(cmds["fmt"], RunCommand)
    assert cmds["fmt"].cmds == ["just fmt"]


def test_parse_run_command_list_cmd() -> None:
    cmds = parse_commands({"big": {"type": "run", "cmd": ["a", "b"]}})
    assert cmds["big"].cmds == ["a", "b"]


def test_parse_run_empty_list_errors() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_commands({"x": {"type": "run", "cmd": []}})


def test_parse_query_missing_columns_errors() -> None:
    with pytest.raises(ValueError, match="columns"):
        parse_commands({"x": {"type": "query"}})


def test_parse_run_missing_cmd_errors() -> None:
    with pytest.raises(ValueError, match="cmd"):
        parse_commands({"x": {"type": "run"}})


def test_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="type"):
        parse_commands({"x": {"type": "weird", "cmd": "x"}})


def test_missing_type_raises() -> None:
    with pytest.raises(ValueError, match="type"):
        parse_commands({"x": {"cmd": "x"}})


def test_empty_input_returns_empty() -> None:
    assert parse_commands(None) == {}
    assert parse_commands({}) == {}


def test_merge_overrides_by_name() -> None:
    defaults = parse_commands({"ls": {"type": "query", "columns": ["name"]}})
    user = parse_commands({"ls": {"type": "query", "columns": ["name", "path"]}})
    merged = merge_commands(defaults, user)
    assert merged["ls"].columns == ["name", "path"]


def test_merge_adds_new_user_commands() -> None:
    defaults = parse_commands({"ls": {"type": "query", "columns": ["name"]}})
    user = parse_commands({"fmt": {"type": "run", "cmd": "just fmt"}})
    merged = merge_commands(defaults, user)
    assert set(merged) == {"ls", "fmt"}


def test_cannot_redefine_hardcoded_primitive() -> None:
    with pytest.raises(ValueError, match="hardcoded"):
        parse_commands({"query": {"type": "run", "cmd": "x"}})


def test_bundled_defaults_parse_cleanly() -> None:
    """Sanity: the shipped defaults.yaml passes parse_commands."""
    from proj.defaults_loader import load_defaults

    cmds = parse_commands(load_defaults().get("commands"))
    assert {"ls", "status", "clean", "archive"} <= set(cmds)
    assert isinstance(cmds["ls"], QueryCommand)
    assert isinstance(cmds["clean"], RunCommand)
