import os
from pathlib import Path

import pytest

from proj.builtins import eval_last_modified, register_builtins
from proj.columns import ColumnRegistry


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_register_builtins_adds_last_modified():
    reg = ColumnRegistry()
    register_builtins(reg)
    assert "last_modified" in reg.names()
    spec = reg.get("last_modified")
    assert spec.type == "integer"


def test_last_modified_returns_max_mtime(tmp_path):
    f1 = tmp_path / "a.txt"
    f1.write_text("x")
    os.utime(f1, (1700000000, 1700000000))
    f2 = tmp_path / "b.txt"
    f2.write_text("y")
    os.utime(f2, (1800000000, 1800000000))
    assert eval_last_modified("", tmp_path) == 1800000000


def test_last_modified_empty_dir_falls_back_to_dir_mtime(tmp_path):
    os.utime(tmp_path, (1700000000, 1700000000))
    assert eval_last_modified("", tmp_path) == 1700000000


def test_last_modified_missing_dir_returns_none(tmp_path):
    assert eval_last_modified("", tmp_path / "does-not-exist") is None
