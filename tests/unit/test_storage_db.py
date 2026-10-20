from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from extracto.adapters.storage.migrate import upgrade_to_head
from extracto.adapters.storage.orm import Base
from tests.conftest import sqlite_only

EXPECTED_TABLES = {
    "sites",
    "pages",
    "snapshots",
    "runs",
    "run_sites",
    "changes",
    "feedback",
    "fetches",
}


@sqlite_only
def test_sqlite_pragmas(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 2  # FULL
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000


def test_migration_creates_all_tables(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES


def test_upgrade_is_idempotent(db_url: str) -> None:
    upgrade_to_head(db_url)  # second run is a no-op


def test_upgrade_creates_missing_data_dir(tmp_path: Path) -> None:
    db_file = tmp_path / "nested" / "dir" / "monitor.db"
    upgrade_to_head(f"sqlite:///{db_file.as_posix()}")
    assert db_file.exists()


def test_migrations_match_models(engine: Engine) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
