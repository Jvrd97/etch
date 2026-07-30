# [review:need-review] PHASE-01/75-daily-summary-checklist
# summary: reversible migration adding applied_daily_summaries.metric_pairs — the (category_id, field_id) pairs an apply actually wrote
"""applied daily summaries metric pairs

Revision ID: f6b8c0d2e4a7
Revises: e5a7b9c1d3f6
Create Date: 2026-07-30 22:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6b8c0d2e4a7"
down_revision: Union[str, None] = "e5a7b9c1d3f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rows written before this column existed get "[]": their metrics cannot be
    # reconstructed, because an apply may reuse an entry it did not create. An
    # empty list makes a replay of such a key with metrics answer 409 ("use a
    # new key") instead of 200 — the direction that loses nothing.
    op.add_column(
        "applied_daily_summaries",
        sa.Column(
            "metric_pairs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("applied_daily_summaries", "metric_pairs")
