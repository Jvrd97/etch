"""day_plan.needs_review

Revision ID: a7f9c1e3b5d7
Revises: e5b7d9f1a3c6
Create Date: 2026-09-02 14:00:00.000000+00:00

Признак «план собран ночью и человеком не смотрен» (`#151`). `down_revision`
вписан по фактическому `alembic heads` этой ветки на момент реализации.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7f9c1e3b5d7"
down_revision: Union[str, None] = "e5b7d9f1a3c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "day_plan",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("day_plan", "needs_review")
