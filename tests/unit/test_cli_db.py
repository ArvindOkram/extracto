from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from typer.testing import CliRunner

from extracto.cli import app

runner = CliRunner()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)  # isolate from any real .env
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_init_db_creates_tables_and_is_safe_twice(data_dir: Path) -> None:
    for _ in range(2):
        result = runner.invoke(app, ["init-db"])
        assert result.exit_code == 0, result.output

    engine = create_engine(f"sqlite:///{(data_dir / 'monitor.db').as_posix()}")
    assert "pages" in inspect(engine).get_table_names()
    engine.dispose()


def test_backup_command(data_dir: Path) -> None:
    runner.invoke(app, ["init-db"])
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0, result.output
    assert len(list((data_dir / "backups").glob("monitor-*.db.gz"))) == 1


def test_backup_without_db_fails_cleanly(data_dir: Path) -> None:
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 1
    assert "init-db" in result.output
