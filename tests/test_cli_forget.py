"""Tests for `proj forget` and stub primitives."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main


def test_forget_removes_entry(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo").mkdir()
    (ws / "bar").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(ws)},
                "projects": {
                    "foo": {"tags": ["mine"]},
                    "bar": {"tags": []},
                },
            }
        )
    )
    r = CliRunner().invoke(main, ["--manifest", str(m), "forget", "foo"])
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(m.read_text())
    assert "foo" not in data["projects"]
    assert "bar" in data["projects"]


def test_forget_unknown_errors(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(yaml.safe_dump({"workspace": {"root": str(ws)}, "projects": {}}))
    r = CliRunner().invoke(main, ["--manifest", str(m), "forget", "ghost"])
    assert r.exit_code != 0
    assert "ghost" in r.output
