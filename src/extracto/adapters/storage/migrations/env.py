"""Alembic environment. The DB URL comes from `extracto init-db` or settings, never alembic.ini."""

from __future__ import annotations

import logging
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext

from extracto.adapters.storage.db import make_engine
from extracto.adapters.storage.orm import Base, UTCDateTime
from extracto.settings import Settings

config = context.config
target_metadata = Base.metadata

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def _database_url() -> str:
    url = config.attributes.get("database_url") or config.get_main_option("sqlalchemy.url")
    return url or Settings().resolved_database_url


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    # Keep migrations free of app imports: render the custom type as a plain DateTime.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite can't ALTER most things; batch mode recreates tables
            render_item=_render_item,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
