from pathlib import Path

import pytest

from proj.errors import UnknownProjectError
from proj.manifest import Manifest, ProjectEntry
from proj.projects import ProjectRegistry


def make_manifest(tmp_path: Path, projects: dict[str, ProjectEntry]) -> Manifest:
    return Manifest(
        workspace_root=tmp_path,
        projects=projects,
        columns={},
        settings={},
    )


def test_default_path_is_workspace_slash_name(tmp_path):
    m = make_manifest(
        tmp_path,
        {"foo": ProjectEntry(name="foo", tags=["mine"], path_override=None, vars={})},
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.get("foo").path == tmp_path / "foo"
    assert reg.get("foo").name == "foo"


def test_path_override_relative(tmp_path):
    m = make_manifest(
        tmp_path,
        {"foo": ProjectEntry(name="foo", tags=[], path_override="other", vars={})},
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.get("foo").path == tmp_path / "other"


def test_vars_preserved(tmp_path):
    m = make_manifest(
        tmp_path,
        {
            "foo": ProjectEntry(
                name="foo", tags=[], path_override=None,
                vars={"host": "server1.tld"},
            )
        },
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.get("foo").vars == {"host": "server1.tld"}


def test_unknown_project_raises(tmp_path):
    reg = ProjectRegistry.from_manifest(make_manifest(tmp_path, {}))
    with pytest.raises(UnknownProjectError):
        reg.get("nonexistent")


def test_names_returns_all(tmp_path):
    m = make_manifest(
        tmp_path,
        {
            "a": ProjectEntry(name="a", tags=[], path_override=None, vars={}),
            "b": ProjectEntry(name="b", tags=[], path_override=None, vars={}),
        },
    )
    reg = ProjectRegistry.from_manifest(m)
    assert sorted(reg.names()) == ["a", "b"]


def test_all_tags_collects_unique_normalized(tmp_path):
    m = make_manifest(
        tmp_path,
        {
            "a": ProjectEntry(name="a", tags=["oss", "mine"], path_override=None, vars={}),
            "b": ProjectEntry(name="b", tags=["oss", "rust"], path_override=None, vars={}),
        },
    )
    reg = ProjectRegistry.from_manifest(m)
    assert reg.all_tags() == {"mine", "oss", "rust"}
