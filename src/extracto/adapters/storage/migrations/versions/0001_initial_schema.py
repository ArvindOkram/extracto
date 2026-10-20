"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-20 12:59:16.102811
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum CHECK constraints are declared once, explicitly, with convention names.
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "completed",
                "failed",
                name="run_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name=op.f("ck_runs_run_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
        sa.UniqueConstraint("name", name=op.f("uq_sites_name")),
    )
    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "removed",
                name="page_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missed_runs", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified", sa.String(length=64), nullable=True),
        sa.CheckConstraint("status IN ('active', 'removed')", name=op.f("ck_pages_page_status")),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_pages_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("site_id", "url_hash", name=op.f("uq_pages_site_id_url_hash")),
    )
    with op.batch_alter_table("pages", schema=None) as batch_op:
        batch_op.create_index("ix_pages_site_status", ["site_id", "status"], unique=False)

    op.create_table(
        "run_sites",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("pages_crawled", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("short_text_pages", sa.Integer(), nullable=False),
        sa.Column(
            "health",
            sa.Enum(
                "ok",
                "degraded",
                "failed",
                "needs_review",
                "skipped",
                name="site_health",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.CheckConstraint(
            "health IN ('ok', 'degraded', 'failed', 'needs_review', 'skipped')",
            name=op.f("ck_run_sites_site_health"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_sites_run_id_runs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_run_sites_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "site_id", name=op.f("pk_run_sites")),
    )
    op.create_table(
        "fetches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "ok",
                "not_modified",
                "http_error",
                "network_error",
                "skipped_robots",
                "skipped_too_large",
                "skipped_not_html",
                "skipped_offsite_redirect",
                name="fetch_outcome",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('ok', 'not_modified', 'http_error', 'network_error', 'skipped_robots', 'skipped_too_large', 'skipped_not_html', 'skipped_offsite_redirect')",
            name=op.f("ck_fetches_fetch_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_fetches_page_id_pages"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_fetches_run_id_runs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_fetches_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fetches")),
    )
    with op.batch_alter_table("fetches", schema=None) as batch_op:
        batch_op.create_index("ix_fetches_page_fetched", ["page_id", "fetched_at"], unique=False)
        batch_op.create_index("ix_fetches_run", ["run_id"], unique=False)

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("raw_path", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_snapshots_page_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_snapshots_run_id_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.create_index(
            "ix_snapshots_page_fetched",
            ["page_id", sa.literal_column("fetched_at DESC")],
            unique=False,
        )

    op.create_table(
        "changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column(
            "change_type",
            sa.Enum(
                "NEW",
                "CHANGED",
                "MINOR",
                "REMOVED",
                name="change_type",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("diff_pct", sa.Double(), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "pricing",
                "product",
                "blog",
                "messaging",
                "other",
                "removed",
                name="change_category",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("before_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("after_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('pricing', 'product', 'blog', 'messaging', 'other', 'removed')",
            name=op.f("ck_changes_change_category"),
        ),
        sa.CheckConstraint(
            "change_type IN ('NEW', 'CHANGED', 'MINOR', 'REMOVED')",
            name=op.f("ck_changes_change_type"),
        ),
        sa.ForeignKeyConstraint(
            ["after_snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_changes_after_snapshot_id_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["before_snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_changes_before_snapshot_id_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_changes_page_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_changes_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changes")),
    )
    with op.batch_alter_table("changes", schema=None) as batch_op:
        batch_op.create_index("ix_changes_run", ["run_id"], unique=False)

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_id", sa.Integer(), nullable=False),
        sa.Column(
            "label",
            sa.Enum(
                "useful",
                "noise",
                name="feedback_label",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("label IN ('useful', 'noise')", name=op.f("ck_feedback_feedback_label")),
        sa.ForeignKeyConstraint(
            ["change_id"],
            ["changes.id"],
            name=op.f("fk_feedback_change_id_changes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # Enum CHECK constraints are declared once, explicitly, with convention names.
    op.drop_table("feedback")
    with op.batch_alter_table("changes", schema=None) as batch_op:
        batch_op.drop_index("ix_changes_run")

    op.drop_table("changes")
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_snapshots_page_fetched")

    op.drop_table("snapshots")
    with op.batch_alter_table("fetches", schema=None) as batch_op:
        batch_op.drop_index("ix_fetches_run")
        batch_op.drop_index("ix_fetches_page_fetched")

    op.drop_table("fetches")
    op.drop_table("run_sites")
    with op.batch_alter_table("pages", schema=None) as batch_op:
        batch_op.drop_index("ix_pages_site_status")

    op.drop_table("pages")
    op.drop_table("sites")
    op.drop_table("runs")
    # ### end Alembic commands ###
