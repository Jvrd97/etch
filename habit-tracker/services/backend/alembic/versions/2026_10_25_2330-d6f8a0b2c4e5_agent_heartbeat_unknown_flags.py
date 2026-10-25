"""agent heartbeat flags may be unknown

Revision ID: d6f8a0b2c4e5
Revises: 3f721bfb0123
Create Date: 2026-10-25 23:30:00.000000+00:00
"""

# [review:need-review] PHASE-03/164
# summary: reversible — agent_heartbeat.accessibility_granted and titles_enabled become nullable (null = the agent does not know yet) and lose their «false» default, so an unknown flag is not drawn as a withheld permission or a switched-off setting

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6f8a0b2c4e5"
down_revision: str | None = "3f721bfb0123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_heartbeat"
FLAGS = ("accessibility_granted", "titles_enabled")


def upgrade() -> None:
    for flag in FLAGS:
        op.alter_column(
            TABLE,
            flag,
            existing_type=sa.Boolean(),
            nullable=True,
            server_default=None,
        )


def downgrade() -> None:
    for flag in FLAGS:
        # Unknown becomes «no» before the column refuses null again.
        op.execute(f"UPDATE {TABLE} SET {flag}=false WHERE {flag} IS NULL")
        op.alter_column(
            TABLE,
            flag,
            existing_type=sa.Boolean(),
            nullable=False,
            server_default="false",
        )
