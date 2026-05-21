"""End-to-end tests for `proj audit`, `proj checks`, and user grouped-column commands."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main


def _ws_with_files(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    good = ws / "good"
    good.mkdir()
    (good / "README.md").write_text("hi")
    (good / "LICENSE").write_text("apache")
    bad = ws / "bad"
    bad.mkdir()
    (bad / "README.md").write_text("hi")  # no LICENSE
    m = tmp_path / "projects.yaml"
    m.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(ws)},
                "projects": {"good": {"tags": []}, "bad": {"tags": []}},
            }
        )
    )
    return m


def test_audit_shows_only_failures_plain(tmp_path: Path) -> None:
    m = _ws_with_files(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "audit",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    # The "good" project: 2/2, no detail lines (passes hidden).
    # The "bad" project: 1/2 with one detail line (has_license).
    assert "good" in r.output
    assert "bad" in r.output
    assert "2/2" in r.output
    assert "1/2" in r.output
    assert "has_license" in r.output  # the failure detail appears
    assert "has_readme" not in r.output  # passes are hidden


def test_audit_json_format(tmp_path: Path) -> None:
    m = _ws_with_files(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "audit",
            "--format",
            "json",
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    by_name = {row["name"]: row for row in data}
    assert by_name["good"]["audit"]["summary"] == "2/2"
    assert by_name["good"]["audit"]["lines"] == []
    assert by_name["bad"]["audit"]["summary"] == "1/2"
    assert len(by_name["bad"]["audit"]["lines"]) == 1
    assert by_name["bad"]["audit"]["lines"][0]["text"] == "has_license"


def test_checks_shows_all_states(tmp_path: Path) -> None:
    m = _ws_with_files(tmp_path)
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "checks",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    # checks shows passes and fails.
    assert "has_readme" in r.output  # all rows pass this
    assert "has_license" in r.output  # bad row fails this


def test_user_defined_grouped_command(tmp_path: Path) -> None:
    """User-defined grouped command (mode: all, all marks visible)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a"
    a.mkdir()
    (a / "README.md").write_text("hi")
    m = tmp_path / "projects.yaml"
    m.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": str(ws)},
                "projects": {"a": {"tags": ["mine"]}},
                "commands": {
                    "mycheck": {
                        "type": "query",
                        "columns": ["name"],
                        "grouped_columns": {
                            "status": {
                                "mode": "all",
                                "columns": ["has_readme", "has_license"],
                                "on_pass": "mark-good",
                                "on_fail": "mark-bad",
                                "on_error": "mark-warn",
                                "on_na": "mark-ignored",
                            }
                        },
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
            "mycheck",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "1/2" in r.output
    # has_readme passes (shown), has_license fails (shown).
    assert "has_readme" in r.output
    assert "has_license" in r.output


def test_user_override_of_mark(tmp_path: Path) -> None:
    """Redefining mark-bad in the manifest changes the rendered prefix."""
    m = _ws_with_files(tmp_path)
    data = yaml.safe_load(m.read_text())
    data["marks"] = {"mark-bad": {"prefix": "BAD: ", "color": "red"}}
    m.write_text(yaml.safe_dump(data))
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "audit",
            "--format",
            "json",
        ],
    )
    assert r.exit_code == 0, r.output
    parsed = json.loads(r.output)
    by_name = {row["name"]: row for row in parsed}
    line = by_name["bad"]["audit"]["lines"][0]
    assert line["mark"]["prefix"] == "BAD: "
