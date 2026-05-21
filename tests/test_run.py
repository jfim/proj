"""Tests for the `proj run` primitive."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main


def _setup(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo").mkdir()
    (ws / "bar").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(ws)},
                "projects": {"foo": {"tags": ["mine"]}, "bar": {"tags": []}},
            }
        )
    )
    return m


def test_run_executes_per_project(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "run", "touch marker"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_where_filters(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "touch marker",
            "--where",
            "mine",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert not (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_dry_run_prints_without_executing(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "touch marker",
            "--dry-run",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "touch marker" in r.output
    assert not (tmp_path / "ws" / "foo" / "marker").exists()
    assert not (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_exit_code_counts_failures(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "run", "false"],
    )
    assert r.exit_code == 2  # both projects failed


def test_run_interpolates_name_and_path(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "echo {{name}} > out",
            "--where",
            "mine",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "out").read_text().strip() == "foo"


def test_run_interpolates_workspace_root(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "echo {{workspace_root}} > root.txt",
            "--where",
            "mine",
        ],
    )
    assert r.exit_code == 0, r.output
    content = (tmp_path / "ws" / "foo" / "root.txt").read_text().strip()
    assert content == str((tmp_path / "ws").resolve())


def test_merge_where_helper() -> None:
    from proj.run import merge_where

    assert merge_where(None, None) is None
    assert merge_where("a", None) == "a"
    assert merge_where(None, "b") == "b"
    assert merge_where("a", "b") == "(a) AND (b)"
