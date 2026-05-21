"""Tests for `proj init`."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main
from proj.init import list_subdirectories, render_manifest


def test_list_subdirectories_sorted_skips_hidden_and_files(tmp_path: Path) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "readme.txt").write_text("hi")
    assert list_subdirectories(tmp_path) == ["alpha", "zeta"]


def test_list_subdirectories_missing_returns_empty(tmp_path: Path) -> None:
    assert list_subdirectories(tmp_path / "nope") == []


def test_render_manifest_with_projects_parses_as_yaml(tmp_path: Path) -> None:
    out = render_manifest(tmp_path, ["one", "two"])
    data = yaml.safe_load(out)
    assert data["workspace"]["root"] == str(tmp_path)
    assert "one" in data["projects"]
    assert data["projects"]["one"] == {"tags": []}
    assert "two" in data["projects"]


def test_render_manifest_empty_still_parses(tmp_path: Path) -> None:
    out = render_manifest(tmp_path, [])
    data = yaml.safe_load(out)
    assert data["workspace"]["root"] == str(tmp_path)
    assert data["projects"] is None or data["projects"] == {}


def test_init_via_xdg_config_home(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo").mkdir()
    (workspace / "bar").mkdir()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(workspace)])
    assert result.exit_code == 0, result.output

    manifest_path = config_home / "proj" / "projects.yaml"
    assert manifest_path.exists()
    data = yaml.safe_load(manifest_path.read_text())
    assert data["workspace"]["root"] == str(workspace.resolve())
    assert set(data["projects"].keys()) == {"foo", "bar"}


def test_init_refuses_to_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    manifest_path = config_home / "proj" / "projects.yaml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("# existing\n")

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(workspace)])
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert manifest_path.read_text() == "# existing\n"


def test_init_force_overwrites(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo").mkdir()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    manifest_path = config_home / "proj" / "projects.yaml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("# existing\n")

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(workspace), "--force"])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(manifest_path.read_text())
    assert "foo" in data["projects"]


def test_init_defaults_directory_to_cwd(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "alpha").mkdir()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.chdir(workspace)

    runner = CliRunner()
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0, result.output

    manifest_path = config_home / "proj" / "projects.yaml"
    data = yaml.safe_load(manifest_path.read_text())
    assert data["workspace"]["root"] == str(workspace.resolve())
    assert "alpha" in data["projects"]


def test_init_resulting_manifest_loads_via_load_manifest(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: init then load_manifest must accept the output."""
    from proj.manifest import load_manifest

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo").mkdir()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(workspace)])
    assert result.exit_code == 0, result.output

    manifest = load_manifest(config_home / "proj" / "projects.yaml")
    assert manifest.workspace_root == workspace.resolve()
    assert "foo" in manifest.projects
