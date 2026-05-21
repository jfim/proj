from pathlib import Path

import pytest
import yaml

from proj.errors import ManifestError, ReservedNameError
from proj.manifest import (
    load_manifest,
    normalize_identifier,
)


def write(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "projects.yaml"
    p.write_text(yaml.safe_dump(content))
    return p


def test_normalize_identifier_colon_to_underscore():
    assert normalize_identifier("lang:elixir") == "lang_elixir"
    assert normalize_identifier("plain") == "plain"
    assert normalize_identifier("has-readme") == "has-readme"  # hyphens preserved


def test_loads_minimal_manifest(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {"foo": {"tags": ["mine"]}},
        },
    )
    m = load_manifest(p)
    assert m.workspace_root == Path(str(tmp_path)).resolve()
    assert "foo" in m.projects
    assert m.projects["foo"].tags == ["mine"]


def test_normalizes_tags_with_colons(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {"foo": {"tags": ["lang:rust", "mine"]}},
        },
    )
    m = load_manifest(p)
    assert m.projects["foo"].tags == ["lang_rust", "mine"]


def test_project_vars_captured(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {
                "foo": {"tags": ["mine"], "host": "server1.tld", "deploy-path": "/var/foo"},
            },
        },
    )
    m = load_manifest(p)
    assert m.projects["foo"].vars == {"host": "server1.tld", "deploy-path": "/var/foo"}
    assert m.projects["foo"].path_override is None


def test_project_path_override_captured(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {"foo": {"tags": [], "path": "elsewhere"}},
        },
    )
    m = load_manifest(p)
    assert m.projects["foo"].path_override == "elsewhere"


def test_column_definition_required_type(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {},
            "columns": {
                "has_readme": {
                    "value-from": "test -f README.md && echo true || echo false",
                    "type": "boolean",
                }
            },
        },
    )
    m = load_manifest(p)
    col = m.columns["has_readme"]
    assert col.value_from == "test -f README.md && echo true || echo false"
    assert col.type == "boolean"
    assert col.applies_to is None
    assert col.applies_when is None
    assert col.cache is False


def test_column_missing_type_errors(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {},
            "columns": {"has_readme": {"value-from": "test -f README.md"}},
        },
    )
    with pytest.raises(ManifestError, match="type"):
        load_manifest(p)


def test_column_with_applies_to_and_when(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {},
            "columns": {
                "otp_version": {
                    "applies-to": "lang_elixir",
                    "applies-when": "test -f .tool-versions",
                    "value-from": "grep otp .tool-versions",
                    "type": "text",
                    "cache": True,
                }
            },
        },
    )
    m = load_manifest(p)
    col = m.columns["otp_version"]
    assert col.applies_to == "lang_elixir"
    assert col.applies_when == "test -f .tool-versions"
    assert col.cache is True


def test_reserved_applies_suffix_rejected(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {},
            "columns": {"foo_applies": {"value-from": "echo 1", "type": "boolean"}},
        },
    )
    with pytest.raises(ReservedNameError):
        load_manifest(p)


def test_missing_workspace_root_errors(tmp_path):
    p = write(tmp_path, {"projects": {}})
    with pytest.raises(ManifestError, match="workspace.root"):
        load_manifest(p)


def test_unknown_column_type_errors(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {},
            "columns": {"foo": {"value-from": "x", "type": "bogus"}},
        },
    )
    with pytest.raises(ManifestError, match="type"):
        load_manifest(p)


def test_projects_as_non_dict_errors(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": ["foo", "bar"],
        },
    )
    with pytest.raises(ManifestError, match="projects"):
        load_manifest(p)


def test_columns_as_non_dict_errors(tmp_path):
    p = write(
        tmp_path,
        {
            "workspace": {"root": str(tmp_path)},
            "projects": {},
            "columns": ["foo", "bar"],
        },
    )
    with pytest.raises(ManifestError, match="columns"):
        load_manifest(p)
