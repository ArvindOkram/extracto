import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from extracto.adapters.storage.db import make_engine, make_session_factory
from extracto.adapters.storage.migrate import upgrade_to_head
from extracto.settings import normalize_database_url

# Set to a Postgres URL (as CI does) to run the DB tests against Postgres instead of SQLite.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

sqlite_only = pytest.mark.skipif(TEST_DATABASE_URL is not None, reason="SQLite-specific behaviour")


def _reset_postgres(url: str) -> None:
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    if TEST_DATABASE_URL:
        url = normalize_database_url(TEST_DATABASE_URL)
        _reset_postgres(url)
    else:
        url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    upgrade_to_head(url)
    return url


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    engine = make_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)
