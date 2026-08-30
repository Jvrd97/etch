"""plan_item.quarter_goal_id and day_plan.quarter_goal_id get their foreign key

Revision ID: c4f6b8d0e2a5
Revises: b3e5a7c9d1f4
Create Date: 2026-09-01 10:10:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4f6b8d0e2a5"
down_revision: Union[str, None] = "b3e5a7c9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `RESTRICT`, not `SET NULL`: a task that named a goal of the quarter must not
    # quietly become somebody else's urgency because the goal was deleted.
    op.create_foreign_key(
        "fk_plan_item_quarter_goal_id",
        "plan_item",
        "quarter_goal",
        ["quarter_goal_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_day_plan_quarter_goal_id",
        "day_plan",
        "quarter_goal",
        ["quarter_goal_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_day_plan_quarter_goal_id", "day_plan", type_="foreignkey")
    op.drop_constraint("fk_plan_item_quarter_goal_id", "plan_item", type_="foreignkey")
