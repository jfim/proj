# tests/test_query_integration.py
from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main


def write_manifest(path: Path, body: dict) -> None:
    path.write_text(yaml.safe_dump(body))


def setup_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "rusty").mkdir(parents=True)
    (ws / "rusty" / "Cargo.toml").write_text("")
    (ws / "rusty" / "README.md").write_text("# rusty")
    (ws / "pyish").mkdir()
    (ws / "pyish" / "pyproject.toml").write_text("")
    return ws


def test_user_column_with_applies_to(tmp_path):
    ws = setup_workspace(tmp_path)
    manifest = tmp_path / "projects.yaml"
    write_manifest(
        manifest,
        {
            "workspace": {"root": str(ws)},
            "projects": {
                "rusty": {"tags": ["mine"]},
                "pyish": {"tags": ["mine"]},
            },
            "columns": {
                "has_readme": {
                    "applies-to": "lang_rust",
                    "value-from": "test -f README.md && echo true || echo false",
                    "type": "boolean",
                },
            },
        },
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--manifest",
            str(manifest),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name, has_readme, has_readme_applies",
            "--order-by",
            "name",
            "--format",
            "plain",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    # rusty applies (lang_rust=1) and has README → value 1
    # pyish does not apply (lang_rust=0) → applies=0, value=NULL (rendered as "")
    assert "pyish\t\t0" in lines
    assert "rusty\t1\t1" in lines


def test_user_column_with_project_var_interpolation(tmp_path):
    ws = setup_workspace(tmp_path)
    manifest = tmp_path / "projects.yaml"
    write_manifest(
        manifest,
        {
            "workspace": {"root": str(ws)},
            "projects": {
                "rusty": {"tags": ["mine"], "owner": "alice"},
                "pyish": {"tags": ["mine"], "owner": "bob"},
            },
            "columns": {
                "owner_echo": {
                    "value-from": "echo {{owner}}",
                    "type": "text",
                },
            },
        },
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--manifest",
            str(manifest),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name, owner_echo",
            "--order-by",
            "name",
            "--format",
            "plain",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = sorted(result.output.strip().splitlines())
    assert lines == ["pyish\tbob", "rusty\talice"]


def test_user_column_with_applies_when(tmp_path):
    ws = setup_workspace(tmp_path)
    (ws / "rusty" / ".hgignore").write_text("foo\n")
    manifest = tmp_path / "projects.yaml"
    write_manifest(
        manifest,
        {
            "workspace": {"root": str(ws)},
            "projects": {
                "rusty": {"tags": ["mine"]},
                "pyish": {"tags": ["mine"]},
            },
            "columns": {
                "has_hg_foo": {
                    "applies-when": "test -f .hgignore",
                    "value-from": "grep -q foo .hgignore && echo true || echo false",
                    "type": "boolean",
                },
            },
        },
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--manifest",
            str(manifest),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name, has_hg_foo, has_hg_foo_applies",
            "--order-by",
            "name",
            "--format",
            "plain",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = sorted(result.output.strip().splitlines())
    assert lines == ["pyish\t\t0", "rusty\t1\t1"]
