"""plan tables

Revision ID: d9f1b3c5e7a0
Revises: c8e0a2b4d6f9
Create Date: 2026-08-30 16:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d9f1b3c5e7a0"
down_revision: Union[str, None] = "c8e0a2b4d6f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "day_plan",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # Unique: a day owns at most one plan, and a second `POST` replaces the
        # first rather than adding to it.
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("title_marker", sa.Text(), nullable=True),
        sa.Column("lede", sa.Text(), nullable=True),
        sa.Column("purpose_md", sa.Text(), nullable=True),
        # No foreign key: `quarter_goal` arrives in `#93`. The column exists now
        # because the plan is written now.
        sa.Column("quarter_goal_id", sa.Integer(), nullable=True),
        sa.Column(
            "counters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("condition_tomorrow", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column(
            "source", sa.String(length=16), server_default="day-open", nullable=False
        ),
        # The markdown the plan was born as, kept because the move off files is
        # one-way and the first months will be read back by a human checking
        # whether the parse lost anything.
        sa.Column("raw_md", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["day_date"], ["day.date"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day_date"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'closed')", name="ck_day_plan_status"
        ),
        sa.CheckConstraint(
            "source IN ('day-open', 'import', 'manual')", name="ck_day_plan_source"
        ),
    )

    op.create_table(
        "plan_section",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Assigned by the server from the position in the incoming document; the
        # unique constraint is what makes a repeated `POST` unable to leave two
        # sections claiming the same place.
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["day_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "ord", name="uq_plan_section_plan_ord"),
    )

    op.create_table(
        "plan_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "rigidity", sa.String(length=8), server_default="soft", nullable=False
        ),
        sa.Column("text_md", sa.Text(), nullable=False),
        sa.Column("text_plain", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_comment", sa.Text(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("done_criterion", sa.Text(), nullable=True),
        sa.Column("why_md", sa.Text(), nullable=True),
        sa.Column("plan_md", sa.Text(), nullable=True),
        sa.Column(
            "external_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        # Every other `Подпись :: значение` the live plans use. Six labels earned
        # a column; the remaining nine-odd arrive here whole rather than being
        # dropped for lacking one.
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("quarter_goal_id", sa.Integer(), nullable=True),
        sa.Column("unlinked_reason", sa.Text(), nullable=True),
        sa.Column(
            "carried_from_item_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "carry_count", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column("legacy_key", sa.Text(), nullable=True),
        # Generated and stored: an overlap is then a self-join on `&&` over a
        # GiST index instead of a recomputation on every render, and full-text
        # search needs no second write path to fall out of step with the text.
        # `window` is a reserved word — quoted here and by SQLAlchemy alike.
        sa.Column(
            "window",
            postgresql.TSTZRANGE(),
            sa.Computed("tstzrange(starts_at, ends_at)", persisted=True),
            nullable=True,
        ),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('russian', text_plain)", persisted=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["plan_section.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["plan_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["carried_from_item_id"], ["plan_item.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('bullet', 'step', 'table_row', 'task', 'anchor', "
            "'hard_point', 'minimum')",
            name="ck_plan_item_kind",
        ),
        sa.CheckConstraint(
            "rigidity IN ('hard', 'soft', 'free')", name="ck_plan_item_rigidity"
        ),
        # The canon of 2026-08-28: a work task without a window and a criterion
        # of being done is not a task, it is a wish.
        sa.CheckConstraint(
            "kind <> 'task' OR (starts_at IS NOT NULL AND ends_at IS NOT NULL "
            "AND done_criterion IS NOT NULL)",
            name="ck_plan_item_task_has_window_and_criterion",
        ),
        # "Не перезакручивать", as a constraint: the free evening block is
        # physically impossible to fill with a schedule.
        sa.CheckConstraint(
            "rigidity <> 'free' OR starts_at IS NULL",
            name="ck_plan_item_free_has_no_window",
        ),
        # Somebody else's urgency cannot be written in silently: either the task
        # names a quarter goal or it names the reason it does not.
        sa.CheckConstraint(
            "kind <> 'task' OR quarter_goal_id IS NOT NULL "
            "OR unlinked_reason IS NOT NULL",
            name="ck_plan_item_task_is_linked_or_explained",
        ),
        sa.CheckConstraint(
            "starts_at IS NULL OR ends_at > starts_at",
            name="ck_plan_item_window_is_forward",
        ),
    )
    op.create_index("ix_plan_item_section_ord", "plan_item", ["section_id", "ord"])
    op.create_index(
        "ix_plan_item_window", "plan_item", ["window"], postgresql_using="gist"
    )
    op.create_index(
        "ix_plan_item_search", "plan_item", ["search"], postgresql_using="gin"
    )
    op.create_index("ix_plan_item_carried_from", "plan_item", ["carried_from_item_id"])
    # Partial: most items carry no code, and NULLs would make the constraint
    # vacuous for exactly the rows that need no protection.
    op.create_index(
        "uq_plan_item_section_code",
        "plan_item",
        ["section_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_plan_item_section_code", "plan_item")
    op.drop_index("ix_plan_item_carried_from", "plan_item")
    op.drop_index("ix_plan_item_search", "plan_item")
    op.drop_index("ix_plan_item_window", "plan_item")
    op.drop_index("ix_plan_item_section_ord", "plan_item")
    op.drop_table("plan_item")
    op.drop_table("plan_section")
    op.drop_table("day_plan")
