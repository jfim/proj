import pytest

from proj.columns import ColumnRegistry, ColumnSpec
from proj.errors import UnknownColumnError


def dummy_eval(rendered: str, cwd) -> str:
    return "ok"


def test_register_and_lookup():
    reg = ColumnRegistry()
    spec = ColumnSpec(
        name="foo",
        type="text",
        applies_to=None,
        applies_when=None,
        cache=False,
        value_from_template="echo foo",
        evaluator=dummy_eval,
    )
    reg.register(spec)
    assert reg.get("foo") is spec


def test_lookup_unknown_raises():
    reg = ColumnRegistry()
    with pytest.raises(UnknownColumnError):
        reg.get("nope")


def test_has_returns_bool():
    reg = ColumnRegistry()
    assert not reg.has("foo")
    reg.register(ColumnSpec(
        name="foo", type="text", applies_to=None, applies_when=None,
        cache=False, value_from_template="x", evaluator=dummy_eval,
    ))
    assert reg.has("foo")


def test_user_columns_can_override_builtins():
    reg = ColumnRegistry()
    builtin = ColumnSpec(
        name="size", type="integer", applies_to=None, applies_when=None,
        cache=True, value_from_template=None, evaluator=dummy_eval,
    )
    reg.register(builtin)
    override = ColumnSpec(
        name="size", type="integer", applies_to=None, applies_when=None,
        cache=True, value_from_template="echo 42", evaluator=dummy_eval,
    )
    reg.register(override)
    assert reg.get("size").value_from_template == "echo 42"


def test_names_returns_registered():
    reg = ColumnRegistry()
    for n in ("a", "b", "c"):
        reg.register(ColumnSpec(
            name=n, type="text", applies_to=None, applies_when=None,
            cache=False, value_from_template="x", evaluator=dummy_eval,
        ))
    assert sorted(reg.names()) == ["a", "b", "c"]
