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
    # Orphans first, the constraint after. `quarter_goal_id` has been a plain
    # integer since `d9f1b3c5e7a0` — no foreign key guarded it, and `quarter_goal`
    # itself only arrives in `b3e5a7c9d1f4`. So a database with history holds ids
    # that point at no goal: rows written before the goals table existed, and rows
    # whose goal was deleted while nothing stopped the delete. On an empty
    # database both statements below touch zero rows.
    #
    # The dangling reference is cleared, not backfilled, and the plan row is kept:
    #
    # * the goal cannot be reconstructed — its quarter, its text and its position
    #   are gone, and `uq_quarter_goal_quarter_ord` with `ck_quarter_goal_ord`
    #   caps a quarter at five goals, so inventing parents would either collide
    #   with real goals or fabricate ones a person never set;
    # * deleting the children would delete days a person actually lived through.
    #
    # A `plan_item` of kind `task` may not end up with neither a goal nor a reason
    # (`ck_plan_item_task_is_linked_or_explained`), so the lost id moves into
    # `unlinked_reason` in the same statement — it stays readable in the plan and
    # in the personal-os export instead of vanishing. An existing reason is left
    # alone. `day_plan` has no such column: there the id is simply dropped.
    op.execute(
        """
        UPDATE plan_item
        SET unlinked_reason = COALESCE(
                unlinked_reason,
                'ссылка на цель квартала ' || quarter_goal_id
                || ' потеряна: цели с таким id нет'
            ),
            quarter_goal_id = NULL
        WHERE quarter_goal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM quarter_goal g WHERE g.id = plan_item.quarter_goal_id
          )
        """
    )
    op.execute(
        """
        UPDATE day_plan
        SET quarter_goal_id = NULL
        WHERE quarter_goal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM quarter_goal g WHERE g.id = day_plan.quarter_goal_id
          )
        """
    )

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
    # Only the constraints come off. The cleared ids are not restored: they were
    # already pointing at nothing, and the reason written into `unlinked_reason`
    # says so in plain words — putting the broken numbers back would be the
    # regression, not the rollback.
    op.drop_constraint("fk_day_plan_quarter_goal_id", "day_plan", type_="foreignkey")
    op.drop_constraint("fk_plan_item_quarter_goal_id", "plan_item", type_="foreignkey")
