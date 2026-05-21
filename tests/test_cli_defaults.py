"""Tests for the `proj defaults` command."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from proj.cli import main


def test_defaults_prints_yaml() -> None:
    r = CliRunner().invoke(main, ["defaults"])
    assert r.exit_code == 0, r.output
    assert "commands:" in r.output
    assert "ls:" in r.output


def test_defaults_path_prints_absolute() -> None:
    r = CliRunner().invoke(main, ["defaults", "--path"])
    assert r.exit_code == 0, r.output
    out = r.output.strip()
    assert out.endswith("defaults.yaml")
    assert Path(out).is_absolute()
