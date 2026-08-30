"""day_summary: the verdict of a day, the counters behind it and its searchable prose

Revision ID: a2d4f6b8c0e3
Revises: f1c3e5a7b9d2
Create Date: 2026-08-31 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a2d4f6b8c0e3"
down_revision: Union[str, None] = "f1c3e5a7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "day_summary",
        # The day is the key: one итог per date, replaced in place. The presence
        # of the row is what "день закрыт" means — no boolean beside it, because
        # two answers to one question eventually disagree.
        sa.Column("day_date", sa.Date(), nullable=False),
        # Stored, not derived: the canon changed on 2026-08-17 and a verdict
        # that does not carry the numbers it was measured against cannot be
        # re-read later.
        sa.Column("rule_set_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("verdict_reason", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "verdict_override",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("verdict_override_note", sa.Text(), nullable=True),
        sa.Column(
            "anchors_done", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "anchors_total", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column("tasks_done", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("tasks_total", sa.SmallInteger(), server_default="0", nullable=False),
        # NULL means "не измерено", never zero: intervals of work arrive with #91.
        sa.Column("work_minutes", sa.Integer(), nullable=True),
        sa.Column("streak_after", sa.Integer(), nullable=True),
        sa.Column("wrote_from_scratch", sa.SmallInteger(), nullable=True),
        sa.Column("education_debt", sa.SmallInteger(), nullable=True),
        sa.Column("reviewed_today", sa.SmallInteger(), nullable=True),
        sa.Column("body_md", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "missing_data",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        # `close` — a day judged here; `import` — a verdict that arrived as prose
        # and is never recomputed.
        sa.Column("source", sa.Text(), server_default="close", nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('russian', body_md)", persisted=True),
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
        sa.PrimaryKeyConstraint("day_date"),
        sa.ForeignKeyConstraint(["day_date"], ["day.date"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["day_rule_set.id"]),
        sa.CheckConstraint("verdict IN ('won', 'lost')", name="ck_day_summary_verdict"),
        sa.CheckConstraint(
            "source IN ('close', 'import')", name="ck_day_summary_source"
        ),
        # The rule, not the message: an override written past the API — a psql
        # session, a migration, the importer — is refused the same way.
        sa.CheckConstraint(
            "NOT verdict_override OR verdict_override_note IS NOT NULL",
            name="ck_day_summary_override_has_note",
        ),
    )
    op.create_index(
        "ix_day_summary_search",
        "day_summary",
        ["search"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_day_summary_search", table_name="day_summary")
    op.drop_table("day_summary")
