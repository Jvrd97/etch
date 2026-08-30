"""quarter_goal.status gets the vocabulary CHECK milestone.status already has

Revision ID: d5a7c9e1f3b6
Revises: c4f6b8d0e2a5
Create Date: 2026-09-01 10:20:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5a7c9e1f3b6"
down_revision: Union[str, None] = "c4f6b8d0e2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The column was free text with a `server_default` and nothing else: the
    # screen draws three words and a fourth spelling would be a goal in no state
    # at all. Rows written before this revision are all `'open'` — the import
    # never writes the column and the API defaulted it — so no backfill is due.
    op.create_check_constraint(
        "ck_quarter_goal_status",
        "quarter_goal",
        "status IN ('open', 'done', 'dropped')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_quarter_goal_status", "quarter_goal", type_="check")
