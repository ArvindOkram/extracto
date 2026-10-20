"""Engine and session setup. Use `factory.begin()` for one transaction per unit of work."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",  # readers (dashboard) don't block the crawler's writes
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=FULL",  # committed writes survive power loss
    "PRAGMA busy_timeout=5000",
)


def _apply_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    for pragma in SQLITE_PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url)
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        return engine
    connect_args: dict[str, Any] = {}
    if url.startswith("postgresql+psycopg"):
        # Disable server-side prepared statements: they break behind PgBouncer-style poolers
        # (e.g. Neon/Supabase pooled connection strings).
        connect_args["prepare_threshold"] = None
    # Hosted Postgres closes idle connections; check before reuse and recycle periodically.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, connect_args=connect_args)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
