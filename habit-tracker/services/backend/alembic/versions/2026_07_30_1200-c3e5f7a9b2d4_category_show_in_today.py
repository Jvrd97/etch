# [review:need-review] PHASE-01/63-today-card-tap-and-visibility
# summary: reversible migration adding nullable categories.show_in_today (NULL = decide by heuristic)
"""category show_in_today

Revision ID: c3e5f7a9b2d4
Revises: b2d4e6f8a1c3
Create Date: 2026-07-30 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3e5f7a9b2d4"
down_revision: Union[str, None] = "b2d4e6f8a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable without a server_default on purpose: NULL is the meaningful third
    # state ("decide by heuristic"), so every category that predates this column
    # keeps behaving exactly as it did.
    op.add_column(
        "categories",
        sa.Column("show_in_today", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("categories", "show_in_today")
