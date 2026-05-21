"""Tests for unknown-subdirectory handling and `proj adopt`."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from proj.cli import main
from proj.manifest import load_manifest
from proj.projects import ProjectRegistry, scan_unknown_subdirs

# ---------- scanner ----------


def test_scan_unknown_subdirs_finds_undeclared(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    claimed = {(tmp_path / "a").resolve()}
    assert scan_unknown_subdirs(tmp_path, claimed) == ["b", "c"]


def test_scan_unknown_subdirs_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / ".hidden").mkdir()
    assert scan_unknown_subdirs(tmp_path, set()) == ["a"]


def test_scan_unknown_subdirs_skips_archive_dir(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "_archive").mkdir()
    assert scan_unknown_subdirs(tmp_path, set(), archive_dir="_archive") == ["a"]


# ---------- registry integration ----------


def _manifest(tmp_path: Path, declared: dict[str, dict], settings: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    for name in declared:
        (ws / name).mkdir()
    m = tmp_path / "projects.yaml"
    data = {"workspace": {"root": str(ws)}, "projects": declared}
    if settings:
        data["settings"] = settings
    m.write_text(yaml.safe_dump(data))
    return m


def test_registry_auto_inserts_unknowns(tmp_path: Path) -> None:
    m_path = _manifest(tmp_path, {"declared": {"tags": []}})
    (tmp_path / "ws" / "stranger").mkdir()
    manifest = load_manifest(m_path)
    reg = ProjectRegistry.from_manifest(manifest, include_unknown=True)
    assert "declared" in reg.names()
    assert "stranger" in reg.names()
    assert reg.get("stranger").unknown is True
    assert reg.get("declared").unknown is False


def test_registry_can_skip_unknowns(tmp_path: Path) -> None:
    m_path = _manifest(tmp_path, {"declared": {"tags": []}})
    (tmp_path / "ws" / "stranger").mkdir()
    manifest = load_manifest(m_path)
    reg = ProjectRegistry.from_manifest(manifest, include_unknown=False)
    assert "stranger" not in reg.names()


# ---------- end-to-end via CLI ----------


def test_unknown_appears_in_ls_by_default(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"declared": {"tags": []}})
    (tmp_path / "ws" / "stranger").mkdir()
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "ls", "--format", "plain"],
    )
    assert r.exit_code == 0, r.output
    names = {line.split("\t", 1)[0] for line in r.output.strip().splitlines()}
    assert names == {"declared", "stranger"}


def test_unknown_query_filter(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"declared": {"tags": []}})
    (tmp_path / "ws" / "stranger").mkdir()
    r = CliRunner().invoke(
        main,
        [
            "--manifest",
            str(m),
            "--cache-dir",
            str(tmp_path),
            "query",
            "name",
            "--where",
            "unknown",
            "--format",
            "plain",
        ],
    )
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "stranger"


def test_ignore_setting_excludes_unknowns(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"declared": {"tags": []}}, settings={"unknown_handling": "ignore"})
    (tmp_path / "ws" / "stranger").mkdir()
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "ls", "--format", "plain"],
    )
    assert r.exit_code == 0, r.output
    names = {line.split("\t", 1)[0] for line in r.output.strip().splitlines()}
    assert names == {"declared"}


def test_warn_setting_emits_stderr_footer(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"declared": {"tags": []}}, settings={"unknown_handling": "warn"})
    (tmp_path / "ws" / "stranger").mkdir()
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "--cache-dir", str(tmp_path), "ls", "--format", "plain"],
    )
    assert r.exit_code == 0, r.output
    # Click's default CliRunner merges stderr into output; ensure the warning shows up.
    combined = r.output + (r.stderr if hasattr(r, "stderr") and r.stderr else "")
    assert "warning:" in combined
    assert "1 unknown" in combined


# ---------- adopt ----------


def test_adopt_list_shows_unknowns(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {})
    (tmp_path / "ws" / "a").mkdir()
    (tmp_path / "ws" / "b").mkdir()
    r = CliRunner().invoke(main, ["--manifest", str(m), "adopt", "--list"])
    assert r.exit_code == 0, r.output
    assert "a" in r.output
    assert "b" in r.output


def test_adopt_with_subdir_and_tags(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {})
    (tmp_path / "ws" / "newproj").mkdir()
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "adopt", "newproj", "--tags", "mine,library"],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(m.read_text())
    assert "newproj" in data["projects"]
    assert data["projects"]["newproj"]["tags"] == ["mine", "library"]


def test_adopt_rejects_already_declared(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"declared": {"tags": []}})
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "adopt", "declared", "--tags", ""],
    )
    assert r.exit_code != 0
    # "declared" is not in the unknowns list — should error
    assert "not an unknown" in r.output.lower() or "already declared" in r.output.lower()


def test_adopt_empty_tags(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {})
    (tmp_path / "ws" / "newproj").mkdir()
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "adopt", "newproj", "--tags", ""],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(m.read_text())
    assert data["projects"]["newproj"]["tags"] == []


def test_adopt_no_unknowns_message(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"declared": {"tags": []}})
    r = CliRunner().invoke(main, ["--manifest", str(m), "adopt", "--list"])
    assert r.exit_code == 0, r.output
    assert "no unknown" in r.output.lower()


def test_adopt_interactive_pick_by_number(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {})
    (tmp_path / "ws" / "alpha").mkdir()
    (tmp_path / "ws" / "beta").mkdir()
    # Input: "2" picks beta, then "lib" for tags.
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "adopt"],
        input="2\nlib\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(m.read_text())
    assert "beta" in data["projects"]
    assert data["projects"]["beta"]["tags"] == ["lib"]


def test_adopt_preserves_comments(tmp_path: Path) -> None:
    """ruamel.yaml round-trip should preserve top-of-file comments."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "newproj").mkdir()
    m = tmp_path / "projects.yaml"
    m.write_text(
        "# my workspace manifest\n"
        f"workspace:\n  root: {ws}\n"
        "projects:\n"
        "  existing:\n"
        "    tags: [mine]\n"
    )
    r = CliRunner().invoke(
        main,
        ["--manifest", str(m), "adopt", "newproj", "--tags", "library"],
    )
    assert r.exit_code == 0, r.output
    after = m.read_text()
    assert "# my workspace manifest" in after
    assert "newproj" in after
    assert "existing" in after
