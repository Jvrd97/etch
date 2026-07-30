# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: reversible migration creating applied_daily_summaries (unique idempotency_key, entry_date, stored response, created_at)
"""applied daily summaries

Revision ID: e5a7b9c1d3f6
Revises: d4f6a8b0c2e5
Create Date: 2026-07-30 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5a7b9c1d3f6"
down_revision: Union[str, None] = "d4f6a8b0c2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applied_daily_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        # The carrier of idempotency for a whole apply, including one that wrote
        # only the day's text and therefore created no keyed entry.
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        # The response the original apply returned, replayed verbatim.
        sa.Column("entry_ids", sa.JSON(), nullable=False),
        # No foreign key: deleting the journal entry must not erase the fact
        # that the day was applied.
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_applied_daily_summaries_id"),
        "applied_daily_summaries",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_applied_daily_summaries_idempotency_key"),
        "applied_daily_summaries",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_applied_daily_summaries_entry_date"),
        "applied_daily_summaries",
        ["entry_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_applied_daily_summaries_entry_date"),
        table_name="applied_daily_summaries",
    )
    op.drop_index(
        op.f("ix_applied_daily_summaries_idempotency_key"),
        table_name="applied_daily_summaries",
    )
    op.drop_index(
        op.f("ix_applied_daily_summaries_id"), table_name="applied_daily_summaries"
    )
    op.drop_table("applied_daily_summaries")
