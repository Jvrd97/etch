"""work intervals — the measured time of a day, manual entry first

Revision ID: e7c9a1b3d5f0
Revises: d5a7c9e1f3b6
Create Date: 2026-09-01 15:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e7c9a1b3d5f0"
down_revision: Union[str, None] = "d5a7c9e1f3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_interval",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # The day of `started_at`, as app.core.daytime.local_date() reads it.
        # Stored rather than derived: the boundary hour is versioned canon, and
        # an interval already filed must not move when the canon changes.
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        # NULL means the interval is running right now.
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source", sa.String(length=16), server_default="manual", nullable=False
        ),
        sa.Column("mode", sa.String(length=16), server_default="work", nullable=False),
        # What the agent proposed before a person moved it; NULL on a row nobody
        # corrected, including every row a person typed in the first place.
        sa.Column("auto_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_ended_at", sa.DateTime(timezone=True), nullable=True),
        # Reverse-DNS application id at most. There is deliberately no column for
        # a window title: its text is the content of a chat, a document and a
        # medical record at once, and a table without the column cannot leak it.
        sa.Column("app_bundle_id", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
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
        # An interval that ends before it starts is a typo, not a short
        # interval. Refused by the database because the agent, an import and a
        # psql session all write here and none of them sees the validator.
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_work_interval_ends_after_start",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'agent', 'corrected')",
            name="ck_work_interval_source",
        ),
        sa.CheckConstraint("mode IN ('work', 'off')", name="ck_work_interval_mode"),
    )
    op.create_index(
        "ix_work_interval_day_started", "work_interval", ["day_date", "started_at"]
    )
    # An open interval becomes an unbounded upper end, which is exactly what
    # "идёт прямо сейчас" means; GiST over the range is what makes "какие
    # интервалы накрывают этот момент" a lookup rather than a scan of the year.
    op.execute(
        "CREATE INDEX ix_work_interval_range ON work_interval "
        "USING gist (tstzrange(started_at, ended_at))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_work_interval_range")
    op.drop_index("ix_work_interval_day_started", "work_interval")
    op.drop_table("work_interval")
