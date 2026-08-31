"""quick-mark directory, its journal, and the index the tap path reads through

Revision ID: a3b5d7f9c1e2
Revises: f2a4c6e8b0d1
Create Date: 2026-09-01 16:00:00.000000+00:00

Reversible in full: `downgrade` drops both new tables and the index on
`entries`, and touches no data. There is nothing to backfill — the directory is
entered by hand, and an empty one is a valid state.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3b5d7f9c1e2"
down_revision: Union[str, None] = "f2a4c6e8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quick_marks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        # increment|check|set_value|relapse as String(20) with a CHECK rather
        # than a PG enum: the project has one enum type and extending it costs a
        # migration with an autocommit block.
        sa.Column("kind", sa.String(length=20), nullable=False),
        # Nullable: a tick has nothing to put here. That `increment`/`set_value`
        # do need it is the validator's rule, not the column's.
        sa.Column("step", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("unit_label", sa.String(length=20), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("hotkey", sa.String(length=1), nullable=True),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "show_in_agent", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('increment', 'check', 'set_value', 'relapse')",
            name="ck_quick_mark_kind",
        ),
    )
    op.create_index("ix_quick_marks_id", "quick_marks", ["id"])
    op.create_index("ix_quick_marks_category_id", "quick_marks", ["category_id"])
    op.create_index("ix_quick_marks_order", "quick_marks", ["order", "id"])
    # Named the way ADR-0018 names it, and partial because the hotkey is
    # optional. Postgres has no partial UNIQUE constraint, so the object is an
    # index; growing it to (user_id, hotkey) for a second user stays a drop and
    # a create of one object either way.
    op.create_index(
        "uq_quick_mark_hotkey",
        "quick_marks",
        ["hotkey"],
        unique=True,
        postgresql_where=sa.text("hotkey IS NOT NULL"),
    )

    op.create_table(
        "quick_mark_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quick_mark_id", sa.Integer(), nullable=False),
        # SET NULL, not CASCADE: an entry deleted in the editor must not take
        # the record that the tap happened with it.
        sa.Column("entry_id", sa.Integer(), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "utc_offset_minutes", sa.Integer(), server_default="0", nullable=False
        ),
        # Exactly one of the two is filled: a number button has no boolean and a
        # tick has no delta.
        sa.Column("delta", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("bool_value", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="web", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        # Written by #124; the column ships here so undo needs no migration.
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["quick_mark_id"], ["quick_marks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint(
            "source IN ('web', 'ios', 'agent', 'plan')",
            name="ck_quick_mark_event_source",
        ),
    )
    op.create_index("ix_quick_mark_events_id", "quick_mark_events", ["id"])
    op.create_index(
        "ix_quick_mark_events_mark_date",
        "quick_mark_events",
        ["quick_mark_id", "entry_date"],
    )
    op.create_index("ix_quick_mark_events_date", "quick_mark_events", ["entry_date"])

    # The hot path of the new contract: every tap reads the day's entry of one
    # category. Two single-column indexes made that a bitmap merge; this makes
    # it one lookup.
    op.create_index("ix_entries_category_date", "entries", ["category_id", "entry_date"])


def downgrade() -> None:
    op.drop_index("ix_entries_category_date", table_name="entries")

    op.drop_index("ix_quick_mark_events_date", table_name="quick_mark_events")
    op.drop_index("ix_quick_mark_events_mark_date", table_name="quick_mark_events")
    op.drop_index("ix_quick_mark_events_id", table_name="quick_mark_events")
    op.drop_table("quick_mark_events")

    op.drop_index("uq_quick_mark_hotkey", table_name="quick_marks")
    op.drop_index("ix_quick_marks_order", table_name="quick_marks")
    op.drop_index("ix_quick_marks_category_id", table_name="quick_marks")
    op.drop_index("ix_quick_marks_id", table_name="quick_marks")
    op.drop_table("quick_marks")
