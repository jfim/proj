from pathlib import Path

from proj.paths import cache_dir, config_path, resolve_project_path


def test_config_path_is_under_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "proj" / "projects.yaml"


def test_config_path_falls_back_to_home_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_path() == tmp_path / ".config" / "proj" / "projects.yaml"


def test_cache_dir_under_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache_dir() == tmp_path / "proj"


def test_resolve_project_path_default_is_workspace_slash_name(tmp_path):
    assert resolve_project_path("foo", None, tmp_path) == tmp_path / "foo"


def test_resolve_project_path_relative_is_under_workspace(tmp_path):
    assert resolve_project_path("foo", "other-dir", tmp_path) == tmp_path / "other-dir"


def test_resolve_project_path_tilde_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_project_path("foo", "~/elsewhere", tmp_path)
    assert result == tmp_path / "elsewhere"


def test_resolve_project_path_absolute_stays_absolute(tmp_path):
    abs_path = "/opt/projects/foo"
    assert resolve_project_path("foo", abs_path, tmp_path) == Path(abs_path)
