"""supplements and their intake marks

Revision ID: e7a9c1b3d5f7
Revises: d6f8a0b2c4e5
Create Date: 2026-10-27 10:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/223
# summary: reversible — `supplements` (name, dose, unit, planned time, archived_at) and `supplement_intakes` (one mark per supplement per logical day, unique Idempotency-Key, cascade on the supplement)

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a9c1b3d5f7"
down_revision: str | None = "d6f8a0b2c4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("dose", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("intake_time", sa.Time(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_supplements_id", "supplements", ["id"])

    op.create_table(
        "supplement_intakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "supplement_id",
            sa.Integer(),
            sa.ForeignKey("supplements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("intake_date", sa.Date(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.UniqueConstraint(
            "supplement_id", "intake_date", name="uq_supplement_intake_day"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_supplement_intakes_idempotency_key"
        ),
    )
    op.create_index(
        "ix_supplement_intakes_intake_date", "supplement_intakes", ["intake_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_supplement_intakes_intake_date", table_name="supplement_intakes")
    op.drop_table("supplement_intakes")
    op.drop_index("ix_supplements_id", table_name="supplements")
    op.drop_table("supplements")
