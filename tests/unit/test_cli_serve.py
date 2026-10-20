from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from extracto.cli import app

runner = CliRunner()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    monkeypatch.chdir(tmp_path)  # don't read the developer's real .env
    monkeypatch.delenv("PORT", raising=False)
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: recorded.append({"app": app, **kw}))
    monkeypatch.delenv("EXTRACTO_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    return recorded


def test_serve_defaults_to_localhost(calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 8000
    assert "http://127.0.0.1:8000/docs" in result.output


def test_serve_custom_port(calls: list[dict[str, Any]]) -> None:
    assert runner.invoke(app, ["serve", "--port", "9001"]).exit_code == 0
    assert calls[0]["port"] == 9001


def test_public_bind_requires_api_key(calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    assert "EXTRACTO_API_KEY" in result.output
    assert calls == []


def test_public_bind_allowed_with_api_key(
    calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXTRACTO_API_KEY", "s3cret")
    assert runner.invoke(app, ["serve", "--host", "0.0.0.0"]).exit_code == 0


def test_serve_uses_port_env_var(
    calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORT", "10000")  # Render sets this
    assert runner.invoke(app, ["serve"]).exit_code == 0
    assert calls[0]["port"] == 10000
