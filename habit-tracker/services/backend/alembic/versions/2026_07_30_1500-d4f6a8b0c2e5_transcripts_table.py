# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: reversible migration creating transcripts (id, source, text, created_at)
"""transcripts table

Revision ID: d4f6a8b0c2e5
Revises: c3e5f7a9b2d4
Create Date: 2026-07-30 15:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f6a8b0c2e5"
down_revision: Union[str, None] = "c3e5f7a9b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), nullable=False),
        # Which feature produced the text; a plain string so a new feature adds
        # a value without widening an enum type.
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transcripts_id"), "transcripts", ["id"], unique=False)
    op.create_index(
        op.f("ix_transcripts_source"), "transcripts", ["source"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_transcripts_source"), table_name="transcripts")
    op.drop_index(op.f("ix_transcripts_id"), table_name="transcripts")
    op.drop_table("transcripts")
