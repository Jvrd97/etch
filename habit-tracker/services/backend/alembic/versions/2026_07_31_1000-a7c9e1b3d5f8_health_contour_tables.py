# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: reversible migration creating the Health contour — metric catalogue (seeded with steps + resting heart rate) and the hourly bucket with its natural key
"""health contour tables

Revision ID: a7c9e1b3d5f8
Revises: f6b8c0d2e4a7
Create Date: 2026-07-31 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c9e1b3d5f8"
down_revision: Union[str, None] = "f6b8c0d2e4a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The seed is spelled out here rather than imported from `app.health.catalog`:
# a migration must keep meaning what it meant on the day it ran, and importing
# application code would let a later edit rewrite history. The two lists are
# expected to agree only at this revision.
SEED_METRICS = [
    {
        "identifier": "HKQuantityTypeIdentifierStepCount",
        "kind": "cumulative",
        "canonical_unit": "count",
        "display_name": "Шаги",
        "group": "movement",
    },
    {
        "identifier": "HKQuantityTypeIdentifierRestingHeartRate",
        "kind": "discrete",
        "canonical_unit": "count/min",
        "display_name": "Пульс покоя",
        "group": "heart",
    },
]


def upgrade() -> None:
    metrics = op.create_table(
        "health_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("canonical_unit", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("group", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_health_metrics_id"), "health_metrics", ["id"])
    op.create_index(
        op.f("ix_health_metrics_identifier"),
        "health_metrics",
        ["identifier"],
        unique=True,
    )
    op.create_index(op.f("ix_health_metrics_group"), "health_metrics", ["group"])

    op.bulk_insert(metrics, SEED_METRICS)

    op.create_table(
        "health_hour_buckets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metric_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("min", sa.Float(), nullable=False),
        sa.Column("max", sa.Float(), nullable=False),
        sa.Column("utc_offset_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["metric_id"], ["health_metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # The natural key: a re-sent chunk updates these rows instead of adding
        # more, which is what makes the whole contour idempotent without an
        # Idempotency-Key.
        sa.UniqueConstraint(
            "metric_id", "local_date", "hour", name="uq_health_hour_bucket_natural_key"
        ),
    )
    op.create_index(op.f("ix_health_hour_buckets_id"), "health_hour_buckets", ["id"])
    op.create_index(
        op.f("ix_health_hour_buckets_metric_id"), "health_hour_buckets", ["metric_id"]
    )
    op.create_index(
        op.f("ix_health_hour_buckets_local_date"), "health_hour_buckets", ["local_date"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_health_hour_buckets_local_date"), "health_hour_buckets")
    op.drop_index(op.f("ix_health_hour_buckets_metric_id"), "health_hour_buckets")
    op.drop_index(op.f("ix_health_hour_buckets_id"), "health_hour_buckets")
    op.drop_table("health_hour_buckets")

    op.drop_index(op.f("ix_health_metrics_group"), "health_metrics")
    op.drop_index(op.f("ix_health_metrics_identifier"), "health_metrics")
    op.drop_index(op.f("ix_health_metrics_id"), "health_metrics")
    op.drop_table("health_metrics")
