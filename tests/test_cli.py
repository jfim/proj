from click.testing import CliRunner

from proj import __version__
from proj.cli import main


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("list", "run", "status", "audit", "dust", "clean", "archive"):
        assert cmd in result.output
