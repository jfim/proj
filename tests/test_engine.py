from pathlib import Path

import pytest

from proj.builtins import register_cheap_builtins
from proj.cache import Cache
from proj.columns import ColumnRegistry
from proj.dispatch import Dispatcher
from proj.engine import build_engine, build_query
from proj.projects import Project, ProjectRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "rust-proj").mkdir()
    (tmp_path / "rust-proj" / "Cargo.toml").write_text("")
    (tmp_path / "py-proj").mkdir()
    (tmp_path / "py-proj" / "pyproject.toml").write_text("")
    return tmp_path


@pytest.fixture
def projects(workspace) -> ProjectRegistry:
    return ProjectRegistry(
        {
            "rust-proj": Project("rust-proj", workspace / "rust-proj", ["mine", "library"], {}),
            "py-proj":   Project("py-proj",   workspace / "py-proj",   ["mine"], {}),
        },
        workspace,
    )


@pytest.fixture
def columns() -> ColumnRegistry:
    reg = ColumnRegistry()
    register_cheap_builtins(reg)
    return reg


@pytest.fixture
def engine(projects, columns, tmp_path):
    cache = Cache(tmp_path / "cache.db")
    dispatcher = Dispatcher(columns, projects, cache)
    return build_engine(projects, columns, dispatcher)


def test_engine_has_projects_table(engine):
    rows = engine.execute("SELECT name FROM projects ORDER BY name").fetchall()
    assert [r[0] for r in rows] == ["py-proj", "rust-proj"]


def test_tag_columns_populated(engine):
    rows = engine.execute("SELECT name, mine, library FROM projects ORDER BY name").fetchall()
    rows = {r[0]: (r[1], r[2]) for r in rows}
    assert rows["rust-proj"] == (1, 1)
    assert rows["py-proj"]   == (1, 0)


def test_language_columns_via_virtual_dispatch(engine):
    rows = engine.execute(
        "SELECT name, lang_rust, lang_python FROM projects ORDER BY name"
    ).fetchall()
    assert {r[0]: (r[1], r[2]) for r in rows} == {
        "py-proj":   (0, 1),
        "rust-proj": (1, 0),
    }


def test_applies_partner_present_for_cheap_columns(engine):
    rows = engine.execute("SELECT lang_rust_applies FROM projects").fetchall()
    # No applies-to/applies-when on lang_rust → always 1
    assert all(r[0] == 1 for r in rows)


def test_sql_funcs_available(engine):
    row = engine.execute("SELECT gb(1), mb(50), kb(1)").fetchone()
    assert row == (1024**3, 50 * 1024**2, 1024)


def test_filter_by_tag(engine):
    row = engine.execute("SELECT count(*) FROM projects WHERE mine").fetchone()
    assert row[0] == 2
    row = engine.execute("SELECT count(*) FROM projects WHERE library").fetchone()
    assert row[0] == 1


def test_build_query_bare_cols():
    assert build_query("name, size") == "SELECT name, size FROM projects"


def test_build_query_with_where():
    assert build_query("name", where="mine") == "SELECT name FROM projects WHERE mine"


def test_build_query_with_order():
    assert build_query("name", order_by="size") == "SELECT name FROM projects ORDER BY size"


def test_build_query_with_limit():
    assert build_query("name", limit=5) == "SELECT name FROM projects LIMIT 5"


def test_build_query_with_group_by():
    assert build_query("lang, count(*)", group_by="lang") == \
        "SELECT lang, count(*) FROM projects GROUP BY lang"


def test_build_query_all_clauses():
    sql = build_query("name, size", where="mine", group_by=None, order_by="size desc", limit=10)
    assert sql == "SELECT name, size FROM projects WHERE mine ORDER BY size desc LIMIT 10"


def test_build_query_full_select_passes_through():
    sql = build_query("select name from projects where mine")
    assert sql == "select name from projects where mine"


def test_build_query_full_select_with_extra_clauses_raises():
    with pytest.raises(ValueError, match="full SELECT"):
        build_query("select name from projects", where="mine")
