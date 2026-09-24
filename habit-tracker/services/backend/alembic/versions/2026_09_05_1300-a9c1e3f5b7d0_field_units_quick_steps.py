"""field units and quick steps

Revision ID: a9c1e3f5b7d0
Revises: f8b0d2e4a6c9
Create Date: 2026-09-05 13:00:00.000000+00:00
"""

# [review:need-review] #176
# summary: reversible columns for optional field units and ordered quick steps

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a9c1e3f5b7d0"
down_revision: str | None = "f8b0d2e4a6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fields", sa.Column("unit", sa.String(length=50), nullable=True))
    op.add_column("fields", sa.Column("quick_steps", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("fields", "quick_steps")
    op.drop_column("fields", "unit")
