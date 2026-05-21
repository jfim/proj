# tests/test_cli.py
from pathlib import Path

import yaml
from click.testing import CliRunner

from proj import __version__
from proj.cli import main


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_query() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "query" in result.output


def _setup(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo").mkdir()
    (workspace / "foo" / "Cargo.toml").write_text("")
    (workspace / "bar").mkdir()
    (workspace / "bar" / "pyproject.toml").write_text("")
    manifest = tmp_path / "projects.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(workspace)},
                "projects": {
                    "foo": {"tags": ["mine"]},
                    "bar": {"tags": ["mine", "library"]},
                },
            }
        )
    )
    return manifest


def test_query_outputs_rows(tmp_path):
    manifest = _setup(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--manifest",
            str(manifest),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name, lang_rust, mine",
            "--format",
            "plain",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert set(lines) == {"foo\t1\t1", "bar\t0\t1"}


def test_query_with_where(tmp_path):
    manifest = _setup(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--manifest",
            str(manifest),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name",
            "--where",
            "library",
            "--format",
            "plain",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "bar"


def test_query_json_output(tmp_path):
    import json

    manifest = _setup(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--manifest",
            str(manifest),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name",
            "--where",
            "mine",
            "--format",
            "json",
            "--order-by",
            "name",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == [{"name": "bar"}, {"name": "foo"}]
