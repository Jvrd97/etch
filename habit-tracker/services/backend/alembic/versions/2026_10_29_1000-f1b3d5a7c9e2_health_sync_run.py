"""health sync run journal

Revision ID: f1b3d5a7c9e2
Revises: e7a9c1b3d5f7
Create Date: 2026-10-29 10:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/132
# summary: reversible — `health_sync_run` (one row per pump run: kind, status, failure class, counters, device) with indexes on started_at DESC and (kind, started_at DESC); the hourly buckets are untouched

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1b3d5a7c9e2"
down_revision: str | None = "e7a9c1b3d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "health_sync_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_run_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("range_from", sa.Date(), nullable=True),
        sa.Column("range_to", sa.Date(), nullable=True),
        sa.Column("samples_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buckets_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_total", sa.Integer(), nullable=True),
        sa.Column(
            "chunks_seen",
            sa.ARRAY(sa.Integer()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_health_sync_run_started_at",
        "health_sync_run",
        [sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_health_sync_run_kind_started_at",
        "health_sync_run",
        ["kind", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_health_sync_run_kind_started_at", table_name="health_sync_run")
    op.drop_index("ix_health_sync_run_started_at", table_name="health_sync_run")
    op.drop_table("health_sync_run")
