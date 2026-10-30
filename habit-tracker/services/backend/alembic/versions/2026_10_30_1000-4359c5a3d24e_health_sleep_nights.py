"""health sleep nights and the sleep catalogue row

Revision ID: 4359c5a3d24e
Revises: f1b3d5a7c9e2
Create Date: 2026-10-30 10:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/238
# summary: reversible — `health_sleep_nights` (one row per wake date: bedtime, wake time, device offset, minutes per stage) and the `HKCategoryTypeIdentifierSleepAnalysis` catalogue row; downgrade drops both and nothing else

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4359c5a3d24e"
down_revision: str | None = "f1b3d5a7c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot, not an import of `app.health.catalog`: a migration must not change
# when the runtime catalogue does.
SLEEP_ROW = {
    "identifier": "HKCategoryTypeIdentifierSleepAnalysis",
    "kind": "sleep",
    "canonical_unit": "min",
    "display_name": "Сон",
    "group": "sleep",
}

MINUTE_COLUMNS = (
    "in_bed_min",
    "asleep_min",
    "awake_min",
    "core_min",
    "deep_min",
    "rem_min",
    "unspecified_min",
)


def _metrics() -> sa.TableClause:
    return sa.table(
        "health_metrics",
        sa.column("identifier", sa.String),
        sa.column("kind", sa.String),
        sa.column("canonical_unit", sa.String),
        sa.column("display_name", sa.String),
        sa.column("group", sa.String),
    )


def upgrade() -> None:
    op.create_table(
        "health_sleep_nights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wake_date", sa.Date(), nullable=False),
        sa.Column("bedtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wake_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("utc_offset_minutes", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.Float(), nullable=False) for name in MINUTE_COLUMNS),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_health_sleep_nights_wake_date",
        "health_sleep_nights",
        ["wake_date"],
        unique=True,
    )
    op.execute(_metrics().insert().values([SLEEP_ROW]))


def downgrade() -> None:
    metrics = _metrics()
    op.execute(
        metrics.delete().where(metrics.c.identifier == SLEEP_ROW["identifier"])
    )
    op.drop_index("ix_health_sleep_nights_wake_date", table_name="health_sleep_nights")
    op.drop_table("health_sleep_nights")
