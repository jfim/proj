import os
import subprocess
from pathlib import Path

import pytest

from proj.builtins import (
    eval_clean_target,
    eval_file_exists,
    eval_git,
    eval_git_ahead,
    eval_git_behind,
    eval_git_branch,
    eval_git_dirty,
    eval_git_last_commit,
    eval_lang_check,
    eval_last_modified,
    eval_size,
    register_cheap_builtins,
    register_expensive_builtins,
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


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "file").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_size_returns_int(tmp_path):
    (tmp_path / "f.bin").write_bytes(b"a" * 1024)
    result = eval_size("", tmp_path)
    assert isinstance(result, int)
    assert result > 0


def test_size_missing_dir_returns_none(tmp_path):
    assert eval_size("", tmp_path / "missing") is None


def test_dirty_returns_false_on_clean_repo(tmp_path):
    _git_init(tmp_path)
    assert eval_git_dirty("", tmp_path) == "false"


def test_dirty_returns_true_when_modified(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "file").write_text("changed")
    assert eval_git_dirty("", tmp_path) == "true"


def test_branch_returns_current(tmp_path):
    _git_init(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=tmp_path, check=True)
    assert eval_git_branch("", tmp_path) == "feature"


def test_ahead_and_behind_zero_on_no_upstream(tmp_path):
    _git_init(tmp_path)
    assert eval_git_ahead("", tmp_path) == 0
    assert eval_git_behind("", tmp_path) == 0


def test_last_commit_returns_timestamp(tmp_path):
    _git_init(tmp_path)
    ts = eval_git_last_commit("", tmp_path)
    assert isinstance(ts, int)
    assert ts > 0


def test_clean_target_for_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("clean:\n\trm -rf build\n")
    assert eval_clean_target("", tmp_path) == "make clean"


def test_clean_target_for_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("")
    assert eval_clean_target("", tmp_path) == "cargo clean"


def test_clean_target_for_justfile(tmp_path):
    (tmp_path / "justfile").write_text("clean:\n  echo cleaning\n")
    assert eval_clean_target("", tmp_path) == "just clean"


def test_clean_target_for_npm(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"clean":"rm -rf dist"}}')
    assert eval_clean_target("", tmp_path) == "npm run clean"


def test_clean_target_none(tmp_path):
    assert eval_clean_target("", tmp_path) is None


def test_register_expensive_adds_columns():
    reg = ColumnRegistry()
    register_expensive_builtins(reg)
    expected = {"size", "dirty", "branch", "ahead", "behind", "last_commit", "clean_target"}
    assert expected.issubset(set(reg.names()))
