"""Tests for `proj new` templates."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from proj.cli import main
from proj.templates import (
    Template,
    parse_templates,
    render_template_cmds,
    run_template,
)

# ---------- parser ----------


def test_parse_templates_basic() -> None:
    parsed = parse_templates({"py": {"tags": ["mine", "lang_python"], "cmds": ["mkdir {{name}}"]}})
    assert parsed["py"] == Template(
        name="py", tags=["mine", "lang_python"], cmds=["mkdir {{name}}"]
    )


def test_parse_templates_empty_returns_empty() -> None:
    assert parse_templates(None) == {}
    assert parse_templates({}) == {}


def test_parse_templates_empty_cmds_errors() -> None:
    with pytest.raises(ValueError, match="cmds"):
        parse_templates({"x": {"tags": [], "cmds": []}})


def test_parse_templates_bad_tags_errors() -> None:
    with pytest.raises(ValueError, match="tags"):
        parse_templates({"x": {"tags": "not-a-list", "cmds": ["echo"]}})


# ---------- renderer ----------


def test_render_template_cmds_interpolates(tmp_path: Path) -> None:
    rendered = render_template_cmds(
        ["mkdir {{name}}", "cd {{workspace_root}}", "echo {{date}}"],
        "myproj",
        tmp_path,
    )
    assert rendered[0] == "mkdir myproj"
    assert rendered[1] == f"cd {tmp_path}"
    import re

    assert re.match(r"^echo \d{4}-\d{2}-\d{2}$", rendered[2])


def test_run_template_success(tmp_path: Path) -> None:
    tmpl = Template(name="t", tags=["a"], cmds=["mkdir {{name}}", "touch {{name}}/marker"])
    failing_idx, results = run_template(tmpl, "newdir", tmp_path)
    assert failing_idx == -1
    assert (tmp_path / "newdir" / "marker").exists()
    assert all(r.returncode == 0 for r in results)


def test_run_template_stops_on_failure(tmp_path: Path) -> None:
    tmpl = Template(name="t", tags=[], cmds=["false", "touch should-not-exist"])
    failing_idx, results = run_template(tmpl, "x", tmp_path)
    assert failing_idx == 0
    assert len(results) == 1
    assert not (tmp_path / "should-not-exist").exists()


def test_run_template_dry_run_executes_nothing(tmp_path: Path) -> None:
    tmpl = Template(name="t", tags=[], cmds=["mkdir foo"])
    failing_idx, results = run_template(tmpl, "x", tmp_path, dry_run=True)
    assert failing_idx == -1
    assert not (tmp_path / "foo").exists()
    assert results[0].cmd == "mkdir foo"


# ---------- end-to-end CLI ----------


def _ws(tmp_path: Path, templates: dict | None = None, projects: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    m = tmp_path / "projects.yaml"
    data: dict = {"workspace": {"root": str(ws)}, "projects": projects or {}}
    if templates is not None:
        data["templates"] = templates
    m.write_text(yaml.safe_dump(data))
    return m


def test_proj_new_creates_project(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        templates={
            "minimal": {
                "tags": ["mine", "lang_python"],
                "cmds": ["mkdir {{name}}", "touch {{name}}/README.md"],
            }
        },
    )
    r = CliRunner().invoke(main, ["--manifest", str(m), "new", "minimal", "exp1"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ws" / "exp1" / "README.md").exists()
    data = yaml.safe_load(m.read_text())
    assert "exp1" in data["projects"]
    assert data["projects"]["exp1"]["tags"] == ["mine", "lang_python"]


def test_proj_new_unknown_template_errors(tmp_path: Path) -> None:
    m = _ws(tmp_path, templates={"foo": {"tags": [], "cmds": ["true"]}})
    r = CliRunner().invoke(main, ["--manifest", str(m), "new", "bar", "x"])
    assert r.exit_code != 0
    assert "bar" in r.output


def test_proj_new_rejects_existing_project(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        templates={"t": {"tags": [], "cmds": ["true"]}},
        projects={"existing": {"tags": []}},
    )
    r = CliRunner().invoke(main, ["--manifest", str(m), "new", "t", "existing"])
    assert r.exit_code != 0
    assert "already declared" in r.output.lower()


def test_proj_new_failure_leaves_partial_state(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        templates={
            "broken": {
                "tags": [],
                "cmds": ["mkdir {{name}}", "false", "touch {{name}}/should-not-exist"],
            }
        },
    )
    r = CliRunner().invoke(main, ["--manifest", str(m), "new", "broken", "halfdone"])
    assert r.exit_code != 0
    # First step ran (dir exists); third step didn't (no marker).
    assert (tmp_path / "ws" / "halfdone").exists()
    assert not (tmp_path / "ws" / "halfdone" / "should-not-exist").exists()
    # Not added to manifest.
    data = yaml.safe_load(m.read_text())
    assert "halfdone" not in (data.get("projects") or {})


def test_proj_new_dry_run_does_not_execute(tmp_path: Path) -> None:
    m = _ws(tmp_path, templates={"t": {"tags": [], "cmds": ["mkdir {{name}}"]}})
    r = CliRunner().invoke(main, ["--manifest", str(m), "new", "t", "dryproj", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "mkdir dryproj" in r.output
    assert not (tmp_path / "ws" / "dryproj").exists()
    data = yaml.safe_load(m.read_text())
    assert "dryproj" not in (data.get("projects") or {})


def test_proj_new_interpolates_date(tmp_path: Path) -> None:
    m = _ws(
        tmp_path,
        templates={
            "dated": {"tags": [], "cmds": ["mkdir {{name}}", "echo {{date}} > {{name}}/d.txt"]}
        },
    )
    r = CliRunner().invoke(main, ["--manifest", str(m), "new", "dated", "stamp"])
    assert r.exit_code == 0, r.output
    import re

    contents = (tmp_path / "ws" / "stamp" / "d.txt").read_text().strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", contents)
