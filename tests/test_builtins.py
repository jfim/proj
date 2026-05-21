from pathlib import Path

import pytest

from proj.builtins import (
    eval_file_exists,
    eval_git,
    eval_lang_check,
    eval_last_modified,
    register_cheap_builtins,
)
from proj.columns import ColumnRegistry


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_register_cheap_adds_expected_columns():
    reg = ColumnRegistry()
    register_cheap_builtins(reg)
    expected = {
        "last_modified",
        "git",
        "has_makefile", "has_justfile", "has_readme", "has_license",
        "lang_rust", "lang_python", "lang_elixir", "lang_scala", "lang_r",
        "lang_js", "lang_ts", "lang_go", "lang_java", "lang_kotlin",
    }
    assert expected.issubset(set(reg.names()))


def test_last_modified_returns_max_mtime(tmp_path):
    f1 = tmp_path / "a.txt"
    f1.write_text("x")
    import os
    os.utime(f1, (1700000000, 1700000000))
    f2 = tmp_path / "b.txt"
    f2.write_text("y")
    os.utime(f2, (1800000000, 1800000000))
    assert eval_last_modified("", tmp_path) == 1800000000


def test_last_modified_missing_dir_returns_none(tmp_path):
    assert eval_last_modified("", tmp_path / "does-not-exist") is None


def test_lang_check_detects_file(tmp_path):
    # Marker "Cargo.toml" exists
    (tmp_path / "Cargo.toml").write_text("")
    assert eval_lang_check("Cargo.toml", tmp_path) == "true"


def test_lang_check_missing_file(tmp_path):
    assert eval_lang_check("Cargo.toml", tmp_path) == "false"


def test_lang_python_detects_any_marker(tmp_path):
    # Python is detected via any of pyproject.toml / setup.py / requirements.txt
    reg = ColumnRegistry()
    register_cheap_builtins(reg)
    spec = reg.get("lang_python")
    (tmp_path / "requirements.txt").write_text("")
    assert spec.evaluator(spec.value_from_template, tmp_path) == "true"


def test_git_present(tmp_path):
    (tmp_path / ".git").mkdir()
    assert eval_git("", tmp_path) == "true"


def test_git_absent(tmp_path):
    assert eval_git("", tmp_path) == "false"


def test_has_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("")
    assert eval_file_exists("Makefile", tmp_path) == "true"
    assert eval_file_exists("NopeFile", tmp_path) == "false"
