"""Tests for dynamic dispatch of user-defined and bundled commands."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main


def _ws(tmp_path: Path, commands: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo").mkdir()
    (ws / "bar").mkdir()
    m = tmp_path / "projects.yaml"
    data = {
        "workspace": {"root": str(ws)},
        "projects": {"foo": {"tags": ["mine"]}, "bar": {"tags": []}},
    }
    if commands is not None:
        data["commands"] = commands
    m.write_text(yaml.safe_dump(data))
    return m


def test_bundled_ls_runs(tmp_path: Path) -> None:
    m = _ws(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "ls",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    names = {line.split("\t", 1)[0] for line in r.output.strip().splitlines()}
    assert names == {"foo", "bar"}


def test_user_run_command(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        commands={"touch_it": {"type": "run", "cmd": "touch marker"}},
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "touch_it"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert (tmp_path / "ws" / "bar" / "marker").exists()


def test_user_run_command_with_where(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        commands={"touch_mine": {"type": "run", "cmd": "touch marker", "where": "mine"}},
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "touch_mine"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert not (tmp_path / "ws" / "bar" / "marker").exists()


def test_user_run_command_cli_where_ands_with_command_where(tmp_path: Path) -> None:
    """CLI --where AND-merges with command's where."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo").mkdir()
    (ws / "bar").mkdir()
    (ws / "baz").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(ws)},
                "projects": {
                    "foo": {"tags": ["mine", "library"]},
                    "bar": {"tags": ["mine"]},
                    "baz": {"tags": ["library"]},
                },
                "commands": {
                    "touch_mine": {
                        "type": "run",
                        "cmd": "touch marker",
                        "where": "mine",
                    }
                },
            }
        )
    )
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "touch_mine",
            "--where",
            "library",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (ws / "foo" / "marker").exists()  # mine AND library
    assert not (ws / "bar" / "marker").exists()  # mine only
    assert not (ws / "baz" / "marker").exists()  # library only


def test_user_query_overrides_bundled_ls(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        commands={"ls": {"type": "query", "columns": ["name", "mine"]}},
    )
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "ls",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    rows = {tuple(line.split("\t")) for line in r.output.strip().splitlines()}
    assert ("foo", "1") in rows
    assert ("bar", "0") in rows


def test_user_query_command_with_where_and_order(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        commands={
            "mine": {
                "type": "query",
                "columns": ["name"],
                "where": "mine",
                "order_by": "name",
            }
        },
    )
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "mine",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "foo"


def test_unknown_command_errors(tmp_path: Path) -> None:
    m = _ws(tmp_path)
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "definitely-not-a-cmd"],
    )
    assert r.exit_code != 0


def test_run_command_with_list_cmd(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        commands={"two_step": {"type": "run", "cmd": ["touch a", "touch b"]}},
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "two_step"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "a").exists()
    assert (tmp_path / "ws" / "foo" / "b").exists()


def test_run_list_cmd_halts_on_failure(tmp_path: Path) -> None:
    """A failing step halts subsequent steps for that project."""
    m = _ws(
        tmp_path,
        commands={"break": {"type": "run", "cmd": ["false", "touch shouldnotexist"]}},
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "break"],
    )
    assert r.exit_code == 2  # both projects fail
    assert not (tmp_path / "ws" / "foo" / "shouldnotexist").exists()
