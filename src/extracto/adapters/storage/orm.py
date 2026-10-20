"""SQLAlchemy ORM models. Schema follows tech doc B§5, plus a `fetches` crawl log."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from extracto.domain.models import (
    ChangeCategory,
    ChangeType,
    FeedbackLabel,
    FetchOutcome,
    PageStatus,
    RunStatus,
    SiteHealth,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(sa.TypeDecorator[datetime]):
    """Stores UTC; always returns timezone-aware datetimes. Rejects naive input."""

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware UTC")
        value = value.astimezone(UTC)
        # SQLite has no timezone support, so store naive UTC there.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _enum(cls: type[StrEnum], name: str) -> sa.Enum:
    """String column with a CHECK constraint (portable across SQLite and Postgres)."""
    return sa.Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: dict[Any, Any] = {datetime: UTCDateTime}


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200), unique=True)
    domain: Mapped[str] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        sa.UniqueConstraint("site_id", "url_hash"),
        sa.Index("ix_pages_site_status", "site_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(sa.ForeignKey("sites.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(sa.Text)
    url_hash: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[PageStatus] = mapped_column(
        _enum(PageStatus, "page_status"), default=PageStatus.ACTIVE
    )
    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)
    missed_runs: Mapped[int] = mapped_column(default=0)
    # Validators for conditional requests (If-None-Match / If-Modified-Since).
    etag: Mapped[str | None] = mapped_column(sa.String(255))
    last_modified: Mapped[str | None] = mapped_column(sa.String(64))


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), default=RunStatus.RUNNING
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(sa.ForeignKey("pages.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id"))
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    title: Mapped[str | None] = mapped_column(sa.Text)
    text: Mapped[str] = mapped_column(sa.Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column("meta_json", sa.JSON)
    raw_path: Mapped[str | None] = mapped_column(sa.Text)


sa.Index("ix_snapshots_page_fetched", Snapshot.page_id, Snapshot.fetched_at.desc())


class RunSite(Base):
    __tablename__ = "run_sites"

    run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    site_id: Mapped[int] = mapped_column(
        sa.ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    pages_crawled: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    short_text_pages: Mapped[int] = mapped_column(default=0)
    health: Mapped[SiteHealth] = mapped_column(_enum(SiteHealth, "site_health"))
    duration_s: Mapped[float | None]


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (sa.Index("ix_changes_run", "run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"))
    page_id: Mapped[int] = mapped_column(sa.ForeignKey("pages.id", ondelete="CASCADE"))
    change_type: Mapped[ChangeType] = mapped_column(_enum(ChangeType, "change_type"))
    diff_pct: Mapped[float | None]
    category: Mapped[ChangeCategory | None] = mapped_column(
        _enum(ChangeCategory, "change_category")
    )
    summary: Mapped[str | None] = mapped_column(sa.Text)
    # NEW has no before snapshot, REMOVED has no after snapshot.
    before_snapshot_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    after_snapshot_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(sa.ForeignKey("changes.id", ondelete="CASCADE"))
    label: Mapped[FeedbackLabel] = mapped_column(_enum(FeedbackLabel, "feedback_label"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Fetch(Base):
    """One row per request, including skips and failures, for crawl history."""

    __tablename__ = "fetches"
    __table_args__ = (
        sa.Index("ix_fetches_run", "run_id"),
        sa.Index("ix_fetches_page_fetched", "page_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"))
    site_id: Mapped[int] = mapped_column(sa.ForeignKey("sites.id", ondelete="CASCADE"))
    # Null when the URL was skipped before a page row existed (e.g. robots.txt).
    page_id: Mapped[int | None] = mapped_column(sa.ForeignKey("pages.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(sa.Text)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
    outcome: Mapped[FetchOutcome] = mapped_column(_enum(FetchOutcome, "fetch_outcome"))
    status_code: Mapped[int | None]
    duration_ms: Mapped[int | None]
    bytes: Mapped[int | None]
    content_hash: Mapped[str | None] = mapped_column(sa.String(64))
    error: Mapped[str | None] = mapped_column(sa.Text)
