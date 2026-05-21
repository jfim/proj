"""Tests for the proj-col helper script (size, clean_target)."""

from __future__ import annotations

import os
import subprocess

import pytest

from proj.column_helpers import column_clean_target, column_size, main


def test_size_returns_int(tmp_path):
    (tmp_path / "f.bin").write_bytes(b"a" * 1024)
    result = column_size(tmp_path)
    assert isinstance(result, int)
    assert result >= 1024


def test_size_missing_dir_returns_none(tmp_path):
    assert column_size(tmp_path / "missing") is None


def test_clean_target_for_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("clean:\n\trm -rf build\n")
    assert column_clean_target(tmp_path) == "make clean"


def test_clean_target_for_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("")
    assert column_clean_target(tmp_path) == "cargo clean"


def test_clean_target_for_justfile(tmp_path):
    (tmp_path / "justfile").write_text("clean:\n  echo cleaning\n")
    assert column_clean_target(tmp_path) == "just clean"


def test_clean_target_for_npm(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"clean":"rm -rf dist"}}')
    assert column_clean_target(tmp_path) == "npm run clean"


def test_clean_target_for_gradle(tmp_path):
    (tmp_path / "build.gradle").write_text("")
    assert column_clean_target(tmp_path) == "./gradlew clean"


def test_clean_target_none(tmp_path):
    assert column_clean_target(tmp_path) is None


def test_main_size_prints_number(tmp_path, capsys, monkeypatch):
    (tmp_path / "f.bin").write_bytes(b"x" * 100)
    monkeypatch.chdir(tmp_path)
    rc = main(["size"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert int(out) >= 100


def test_main_clean_target_prints_when_present(tmp_path, capsys, monkeypatch):
    (tmp_path / "Cargo.toml").write_text("")
    monkeypatch.chdir(tmp_path)
    rc = main(["clean_target"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "cargo clean"


def test_main_clean_target_prints_nothing_when_absent(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["clean_target"])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_main_unknown_helper_returns_2(capsys):
    rc = main(["nope"])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_main_no_args_returns_2(capsys):
    capsys.readouterr()  # drain
    rc = main([])
    assert rc == 2


@pytest.mark.skipif(
    os.environ.get("PROJ_SKIP_INTEGRATION") == "1",
    reason="opt-out for environments without the installed console script",
)
def test_console_script_installed(tmp_path):
    """proj-col is on PATH as an installed console script."""
    (tmp_path / "Cargo.toml").write_text("")
    result = subprocess.run(
        ["proj-col", "clean_target"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "not found" in (result.stderr or "").lower():
        pytest.skip("proj-col not on PATH in this environment")
    assert result.returncode == 0
    assert result.stdout.strip() == "cargo clean"
