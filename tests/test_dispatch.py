import pytest

from proj.cache import Cache
from proj.columns import ColumnRegistry, ColumnSpec, make_shell_evaluator
from proj.dispatch import Dispatcher
from proj.projects import Project, ProjectRegistry


@pytest.fixture
def project(tmp_path) -> Project:
    return Project(name="foo", path=tmp_path, tags=["mine"], vars={"host": "h1.tld"})


@pytest.fixture
def projects(project) -> ProjectRegistry:
    return ProjectRegistry({project.name: project}, project.path.parent)


@pytest.fixture
def cache(tmp_path) -> Cache:
    return Cache(tmp_path / "cache.db")


def test_get_value_uncached_column(projects, cache):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="foo",
            type="text",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="echo bar",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "foo") == "bar"


def test_get_value_caches_when_cache_true(projects, cache, tmp_path):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="counter",
            type="integer",
            applies_to=None,
            applies_when=None,
            cache=True,
            value_from_template="echo 1 > {{path}}/n && wc -l < {{path}}/n",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    v1 = d.get_value("foo", "counter")
    v2 = d.get_value("foo", "counter")
    assert v1 == v2  # second call hits cache


def test_applies_when_false_returns_none(projects, cache):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="needs_lock",
            type="text",
            applies_to=None,
            applies_when="test -f impossible-marker",
            cache=False,
            value_from_template="echo present",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "needs_lock") is None


def test_applies_when_true_runs_value_from(projects, cache, tmp_path):
    (tmp_path / "marker").write_text("")
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="x",
            type="text",
            applies_to=None,
            applies_when="test -f marker",
            cache=False,
            value_from_template="echo present",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "x") == "present"


def test_interpolation_of_project_vars(projects, cache):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="hostname",
            type="text",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="echo {{host}}",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "hostname") == "h1.tld"


def test_get_applies_returns_1_with_no_applies_when(projects, cache):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="x",
            type="text",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="echo ok",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_applies("foo", "x") == 1


def test_get_applies_returns_0_when_shell_fails(projects, cache):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="x",
            type="text",
            applies_to=None,
            applies_when="false",
            cache=False,
            value_from_template="echo ok",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_applies("foo", "x") == 0


def test_get_applies_caches(projects, cache, tmp_path):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="x",
            type="text",
            applies_to=None,
            applies_when="true",
            cache=False,
            value_from_template="echo ok",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    a1 = d.get_applies("foo", "x")
    a2 = d.get_applies("foo", "x")
    assert a1 == a2 == 1


def test_type_coercion_applied(projects, cache):
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="n",
            type="integer",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="echo 42",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "n") == 42


def test_project_var_shadows_auto_injected(tmp_path, cache):
    """A project-declared var (e.g. host) with the same name as an auto-injected
    var (e.g. path) overrides the auto-injected one."""
    proj_dir = tmp_path / "real-path"
    proj_dir.mkdir()
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    p = Project(name="foo", path=proj_dir, tags=[], vars={"path": str(custom_dir)})
    projects = ProjectRegistry({p.name: p}, tmp_path)
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="echo_path",
            type="text",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="echo {{path}}",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    # Project's own `path` var should win over the auto-injected one
    assert d.get_value("foo", "echo_path") == str(custom_dir)


def test_missing_var_in_applies_when_returns_zero(tmp_path, cache, projects):
    """A column whose applies-when references a missing var should return 0, not crash."""
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="x",
            type="text",
            applies_to=None,
            applies_when="test -n {{nonexistent_var}}",
            cache=False,
            value_from_template="echo ok",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_applies("foo", "x") == 0


def test_missing_var_in_value_from_returns_none(tmp_path, cache, projects):
    """A column whose value-from references a missing var should return None, not crash."""
    reg = ColumnRegistry()
    reg.register(
        ColumnSpec(
            name="x",
            type="text",
            applies_to=None,
            applies_when=None,
            cache=False,
            value_from_template="echo {{nonexistent_var}}",
            evaluator=make_shell_evaluator(),
        )
    )
    d = Dispatcher(reg, projects, cache)
    assert d.get_value("foo", "x") is None
