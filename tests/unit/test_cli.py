import pytest
from typer.testing import CliRunner

from extracto import __version__
from extracto.cli import app

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init-db", "backup", "run", "report", "health"):
        assert command in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize("command", ["report", "health"])
def test_commands_are_stubs(command: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == 1
    assert "not implemented" in result.output
