"""goal_level, milestone, milestone_dep, quarter_goal — the goals of goal.md

Revision ID: b3e5a7c9d1f4
Revises: a2d4f6b8c0e3
Create Date: 2026-09-01 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3e5a7c9d1f4"
down_revision: Union[str, None] = "a2d4f6b8c0e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goal_level",
        # The level is the key: `goal.md` has one block per level, and the number
        # is what both the file and the screen order by.
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), server_default="", nullable=False),
        # The `⚠ подтверди` lines, kept as questions rather than folded into the
        # prose they were marked out of.
        sa.Column(
            "open_questions",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("level"),
        sa.CheckConstraint("level BETWEEN 0 AND 5", name="ck_goal_level_level"),
    )

    op.create_table(
        "milestone",
        # `M1`…`M10` — what the quarter goals, the dependency graph and a person
        # all name a milestone by.
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("done_criterion", sa.Text(), nullable=True),
        # «сейчас», «после M2+M3», «~2032, тебе 32». Text, because `goal.md` says
        # outright that these are landmarks and not dates.
        sa.Column("when_text", sa.Text(), nullable=True),
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        # The two columns the import of `goal.md` does not own: whether a
        # milestone is done is a fact a person establishes, and the file does not
        # record it.
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("done_on", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
        sa.CheckConstraint(
            "status IN ('open', 'in-progress', 'done', 'dropped')",
            name="ck_milestone_status",
        ),
    )

    op.create_table(
        "milestone_dep",
        # The «Открывается чем» column as edges: M10 waits for M9 and for M8, and
        # two answers do not fit in a cell.
        sa.Column("milestone_code", sa.String(length=16), nullable=False),
        sa.Column("depends_on_code", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["milestone_code"], ["milestone.code"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_code"], ["milestone.code"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("milestone_code", "depends_on_code"),
    )

    op.create_table(
        "quarter_goal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # `2026-Q3`: sortable, and the shape `week.iso_code` already uses.
        sa.Column("quarter", sa.String(length=16), nullable=False),
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        sa.Column("text_md", sa.Text(), nullable=False),
        sa.Column("milestone_code", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.ForeignKeyConstraint(
            ["milestone_code"], ["milestone.code"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        # «Больше пяти — цель размазана». Neither constraint is the ceiling on its
        # own: the CHECK alone lets five rows claim position 3, the UNIQUE alone
        # lets a sixth goal call itself number 6.
        sa.CheckConstraint("ord BETWEEN 1 AND 5", name="ck_quarter_goal_ord"),
        sa.UniqueConstraint("quarter", "ord", name="uq_quarter_goal_quarter_ord"),
    )


def downgrade() -> None:
    op.drop_table("quarter_goal")
    op.drop_table("milestone_dep")
    op.drop_table("milestone")
    op.drop_table("goal_level")
