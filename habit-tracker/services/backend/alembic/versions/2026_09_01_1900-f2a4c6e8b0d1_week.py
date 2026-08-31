"""week and week_review_item — the fixed snapshot of a week and its sunday checklist

Revision ID: f2a4c6e8b0d1
Revises: e6b8d0f2a4c7
Create Date: 2026-09-01 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f2a4c6e8b0d1"
down_revision: Union[str, None] = "e6b8d0f2a4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "week",
        # `2026-W35` — the name of the file this replaces, the URL segment and
        # what a person calls the week out loud.
        sa.Column("iso_code", sa.String(length=8), nullable=False),
        # Materialised from the code when the row is written, so a range query
        # over days does not re-derive the ISO calendar in SQL.
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        # The counters, and only they, are rewritten by a recompute.
        sa.Column("won_days", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("total_days", sa.SmallInteger(), server_default="0", nullable=False),
        # NULL when no day of the week was closed — not the same as a streak of 0.
        sa.Column("streak_end", sa.Integer(), nullable=True),
        sa.Column("retro_md", sa.Text(), server_default="", nullable=False),
        sa.Column("blockers_md", sa.Text(), server_default="", nullable=False),
        sa.Column("mgmt_retro_md", sa.Text(), server_default="", nullable=False),
        sa.Column("weekly_number_md", sa.Text(), server_default="", nullable=False),
        # When the counters above were last taken. The whole point of the week
        # being a stored snapshot rather than a view over `day_summary`.
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('russian', "
                "retro_md || ' ' || blockers_md || ' ' || mgmt_retro_md "
                "|| ' ' || weekly_number_md)",
                persisted=True,
            ),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint("iso_code"),
    )
    op.create_index(
        "ix_week_search", "week", ["search"], unique=False, postgresql_using="gin"
    )

    op.create_table(
        "week_review_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_iso", sa.String(length=8), nullable=False),
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        sa.Column("text_md", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["week_iso"], ["week.iso_code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # The list is edited as a list: one line per position, so a replace
        # cannot leave two questions claiming the same place.
        sa.UniqueConstraint("week_iso", "ord", name="uq_week_review_item_week_ord"),
    )
    op.create_index(
        "ix_week_review_item_week_iso", "week_review_item", ["week_iso"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_week_review_item_week_iso", table_name="week_review_item")
    op.drop_table("week_review_item")
    op.drop_index("ix_week_search", table_name="week")
    op.drop_table("week")
