"""Tests for the bundled defaults.yaml and its loader."""

from __future__ import annotations

from proj.defaults_loader import defaults_path, load_defaults


def test_defaults_path_exists() -> None:
    p = defaults_path()
    assert p.exists() and p.suffix == ".yaml"


def test_defaults_yaml_parses() -> None:
    data = load_defaults()
    assert isinstance(data, dict)
    assert "commands" in data


def test_bundled_commands_present() -> None:
    cmds = load_defaults()["commands"]
    for name in ("ls", "status", "clean", "archive"):
        assert name in cmds, f"missing bundled command {name}"


def test_ls_is_query_type_with_columns() -> None:
    ls = load_defaults()["commands"]["ls"]
    assert ls["type"] == "query"
    assert "name" in ls["columns"]


def test_clean_is_run_type_with_path_interpolation() -> None:
    clean = load_defaults()["commands"]["clean"]
    assert clean["type"] == "run"
    cmd = clean["cmd"]
    cmd_str = cmd if isinstance(cmd, str) else "\n".join(cmd)
    assert "{{path}}" in cmd_str


def test_archive_is_run_with_list_cmd() -> None:
    archive = load_defaults()["commands"]["archive"]
    assert archive["type"] == "run"
    assert isinstance(archive["cmd"], list)
    assert len(archive["cmd"]) >= 2
