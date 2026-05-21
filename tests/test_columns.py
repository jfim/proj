import pytest

from proj.columns import ColumnRegistry, ColumnSpec, coerce_to_type
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


@pytest.mark.parametrize(
    "raw,ctype,expected",
    [
        ("42", "integer", 42),
        ("  17 ", "integer", 17),
        ("3.14", "real", 3.14),
        ("hello", "text", "hello"),
        ("  hi ", "text", "hi"),
        ("true", "boolean", 1),
        ("True", "boolean", 1),
        ("yes", "boolean", 1),
        ("1", "boolean", 1),
        ("false", "boolean", 0),
        ("0", "boolean", 0),
        ("no", "boolean", 0),
        ("", "boolean", 0),
        ("nonsense", "boolean", None),
        ("notanint", "integer", None),
        ("notafloat", "real", None),
    ],
)
def test_coerce_to_type(raw, ctype, expected):
    assert coerce_to_type(raw, ctype) == expected


def test_coerce_none_input_returns_none():
    assert coerce_to_type(None, "text") is None
    assert coerce_to_type(None, "integer") is None
    assert coerce_to_type(None, "boolean") is None


def test_shell_evaluator_captures_stdout(tmp_path):
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator()
    out = ev("echo hello", tmp_path)
    assert out == "hello"


def test_shell_evaluator_returns_none_on_nonzero(tmp_path):
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator()
    out = ev("false", tmp_path)
    assert out is None


def test_shell_evaluator_uses_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("data")
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator()
    out = ev("cat marker.txt", tmp_path)
    assert out == "data"


def test_shell_evaluator_timeout_returns_none(tmp_path):
    from proj.columns import make_shell_evaluator
    ev = make_shell_evaluator(timeout=0.1)
    out = ev("sleep 1", tmp_path)
    assert out is None
