"""Plan F: column-value interpolation, --parallel, --summary, --here/--all, ~/.projrc."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main


def _setup(tmp_path: Path, projects: dict | None = None, commands: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    declared = projects or {"foo": {"tags": ["mine"]}, "bar": {"tags": []}}
    for name in declared:
        (ws / name).mkdir()
    m = tmp_path / "projects.yaml"
    data = {"workspace": {"root": str(ws)}, "projects": declared}
    if commands is not None:
        data["commands"] = commands
    m.write_text(yaml.safe_dump(data))
    return m


# ---------- column-value interpolation ----------


def test_run_interpolates_project_var(tmp_path: Path) -> None:
    m = _setup(
        tmp_path,
        projects={
            "alpha": {"tags": [], "host": "alpha.tld"},
            "beta": {"tags": [], "host": "beta.tld"},
        },
    )
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "echo {{host}} > out",
            "--all",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "alpha" / "out").read_text().strip() == "alpha.tld"
    assert (tmp_path / "ws" / "beta" / "out").read_text().strip() == "beta.tld"


def test_run_interpolates_column_value(tmp_path: Path) -> None:
    """A column value referenced in `cmd` should be looked up per-project."""
    m = _setup(
        tmp_path,
        projects={
            "p1": {"tags": ["mine"]},
            "p2": {"tags": []},
        },
    )
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "echo {{mine}} > tag",
            "--all",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "p1" / "tag").read_text().strip() == "1"
    assert (tmp_path / "ws" / "p2" / "tag").read_text().strip() == "0"


# ---------- --here / --all auto-scope ----------


def test_run_here_scopes_to_cwd_project(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    cwd = tmp_path / "ws" / "foo"
    old = os.getcwd()
    os.chdir(cwd)
    try:
        r = CliRunner().invoke(
            main,
            [
                "--manifest",
                str(m),
                "--cache-dir",
                str(tmp_path),
                "run",
                "touch marker",
                "--here",
            ],
        )
    finally:
        os.chdir(old)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert not (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_all_overrides_here_default(tmp_path: Path) -> None:
    """When cwd is inside a project, run defaults to single; --all overrides."""
    m = _setup(tmp_path)
    cwd = tmp_path / "ws" / "foo"
    old = os.getcwd()
    os.chdir(cwd)
    try:
        r = CliRunner().invoke(
            main,
            [
                "--manifest",
                str(m),
                "--cache-dir",
                str(tmp_path),
                "run",
                "touch marker",
                "--all",
            ],
        )
    finally:
        os.chdir(old)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_default_scopes_to_cwd_project_when_inside(tmp_path: Path) -> None:
    """Inside a project, `proj run X` (no flags) should auto-scope to single project."""
    m = _setup(tmp_path)
    cwd = tmp_path / "ws" / "foo"
    old = os.getcwd()
    os.chdir(cwd)
    try:
        r = CliRunner().invoke(
            main,
            ["--manifest", str(m), "--cache-dir", str(tmp_path), "run", "touch marker"],
        )
    finally:
        os.chdir(old)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert not (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_default_aggregates_outside_workspace(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    old = os.getcwd()
    os.chdir(tmp_path)  # not inside workspace
    try:
        r = CliRunner().invoke(
            main,
            ["--manifest", str(m), "--cache-dir", str(tmp_path), "run", "touch marker"],
        )
    finally:
        os.chdir(old)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert (tmp_path / "ws" / "bar" / "marker").exists()


def test_here_and_all_conflict(tmp_path: Path) -> None:
    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "run",
            "true",
            "--here",
            "--all",
        ],
    )
    assert r.exit_code != 0
    assert "mutually exclusive" in r.output


# ---------- --parallel + --summary ----------


def test_run_parallel_executes_all(tmp_path: Path) -> None:
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
            "--parallel",
            "--all",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "marker").exists()
    assert (tmp_path / "ws" / "bar" / "marker").exists()


def test_run_summary_prints_pass_fail_table(tmp_path: Path) -> None:
    m = _setup(
        tmp_path,
        projects={
            "ok": {"tags": []},
            "broken": {"tags": []},
        },
    )
    # ok will pass (mkdir already exists is fine because we touch); broken will fail.
    # Use a cmd that succeeds in `ok` and fails in `broken` via project name interpolation.
    m.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(tmp_path / "ws")},
                "projects": {"ok": {"tags": []}, "broken": {"tags": []}},
                "commands": {
                    "x": {
                        "type": "run",
                        "cmd": "[ {{name}} = ok ] && true || false",
                    }
                },
            }
        )
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "x", "--summary", "--all"],
    )
    assert r.exit_code == 1
    out = r.output
    assert "PASS" in out
    assert "FAIL" in out
    assert "1 passed, 1 failed" in out


# ---------- ~/.projrc overlay ----------


def test_projrc_command_is_loaded(tmp_path: Path, monkeypatch) -> None:
    """A command defined in ~/.projrc should be available when not overridden."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".projrc").write_text(
        yaml.safe_dump({"commands": {"rc_only": {"type": "run", "cmd": "touch from_rc"}}})
    )
    monkeypatch.setenv("HOME", str(home))

    m = _setup(tmp_path)
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "rc_only", "--all"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "from_rc").exists()


def test_manifest_overrides_projrc(tmp_path: Path, monkeypatch) -> None:
    """When the workspace manifest defines the same command name, it wins."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".projrc").write_text(
        yaml.safe_dump({"commands": {"greet": {"type": "run", "cmd": "echo from_rc > out"}}})
    )
    monkeypatch.setenv("HOME", str(home))

    m = _setup(
        tmp_path,
        commands={"greet": {"type": "run", "cmd": "echo from_manifest > out"}},
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "greet", "--all"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "foo" / "out").read_text().strip() == "from_manifest"
