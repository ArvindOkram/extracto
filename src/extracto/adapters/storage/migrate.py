"""Run Alembic migrations programmatically (used by `extracto init-db`)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Passed via attributes, not set_main_option, so '%' in URLs isn't interpolated.
    cfg.attributes["database_url"] = database_url
    return cfg


def ensure_sqlite_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def upgrade_to_head(database_url: str) -> None:
    ensure_sqlite_dir(database_url)
    command.upgrade(alembic_config(database_url), "head")
