"""plan marks and the append-only log of their changes

Revision ID: e0b2d4f6a8c1
Revises: d9f1b3c5e7a0
Create Date: 2026-08-30 20:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e0b2d4f6a8c1"
down_revision: Union[str, None] = "d9f1b3c5e7a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_mark",
        # The primary key is the item: one mark per item, no surrogate id for
        # anything to disagree about. Until now the key was the item's position
        # in the DOM, so inserting a line shifted every mark below it.
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        # "как прошло" — the sentence next to the tick, and half the value of a
        # closed day.
        sa.Column("note", sa.Text(), nullable=True),
        # Moves with the state; `updated_at` moves with any write, including an
        # edit of the note alone.
        sa.Column(
            "marked_at",
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
        sa.Column(
            "source", sa.String(length=16), server_default="web", nullable=False
        ),
        sa.ForeignKeyConstraint(["item_id"], ["plan_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
        sa.CheckConstraint(
            "state IN ('done', 'failed', 'skipped')", name="ck_plan_mark_state"
        ),
        sa.CheckConstraint(
            "source IN ('web', 'agent', 'import', 'llm')", name="ck_plan_mark_source"
        ),
    )

    op.create_table(
        "plan_mark_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # No foreign key on purpose: an item deleted from a plan takes its
        # `plan_mark` with it, and that is right, but an append-only log that
        # forgets what was once ticked is not a log. `day_date` is what the log
        # is read by once the item it points at is gone.
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        # NULL on either side is `pending`: NULL -> 'done' is the first tick,
        # 'failed' -> NULL the third click that takes the mark off again.
        sa.Column("from_state", sa.String(length=16), nullable=True),
        sa.Column("to_state", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "source", sa.String(length=16), server_default="web", nullable=False
        ),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "from_state IS NULL OR from_state IN ('done', 'failed', 'skipped')",
            name="ck_plan_mark_event_from_state",
        ),
        sa.CheckConstraint(
            "to_state IS NULL OR to_state IN ('done', 'failed', 'skipped')",
            name="ck_plan_mark_event_to_state",
        ),
        # A row that records no change is not an event; `IS DISTINCT FROM` says
        # so across NULLs, which a plain `<>` would let through.
        sa.CheckConstraint(
            "from_state IS DISTINCT FROM to_state",
            name="ck_plan_mark_event_is_a_change",
        ),
        sa.CheckConstraint(
            "source IN ('web', 'agent', 'import', 'llm')",
            name="ck_plan_mark_event_source",
        ),
    )
    op.create_index("ix_plan_mark_event_item_at", "plan_mark_event", ["item_id", "at"])
    op.create_index("ix_plan_mark_event_day_at", "plan_mark_event", ["day_date", "at"])


def downgrade() -> None:
    op.drop_index("ix_plan_mark_event_day_at", "plan_mark_event")
    op.drop_index("ix_plan_mark_event_item_at", "plan_mark_event")
    op.drop_table("plan_mark_event")
    op.drop_table("plan_mark")
