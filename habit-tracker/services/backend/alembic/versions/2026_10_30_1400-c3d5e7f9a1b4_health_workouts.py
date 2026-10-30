"""health workouts

Revision ID: c3d5e7f9a1b4
Revises: b55c9394752b
Create Date: 2026-10-30 14:00:00.000000+00:00
"""

# [review:need-review] PHASE-02/70
# summary: reversible — `health_workouts` (one row per HealthKit workout UUID: type, real bounds with the device offset, start-date local_date, duration, energy, distance, average and max heart rate); downgrade drops the table and nothing else

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d5e7f9a1b4"
down_revision: str | None = "b55c9394752b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "health_workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workout_uuid", sa.Uuid(), nullable=False, unique=True),
        sa.Column("activity_type", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("utc_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("duration_min", sa.Float(), nullable=False),
        sa.Column("energy_kcal", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("avg_heart_rate", sa.Float(), nullable=True),
        sa.Column("max_heart_rate", sa.Float(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_health_workouts_local_date", "health_workouts", ["local_date"])


def downgrade() -> None:
    op.drop_index("ix_health_workouts_local_date", table_name="health_workouts")
    op.drop_table("health_workouts")
