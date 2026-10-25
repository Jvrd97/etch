"""activity interval names its plan item

Revision ID: c3e5a7b9d1f4
Revises: a9c1e3f5b7d0
Create Date: 2026-10-25 17:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/159
# summary: reversible nullable activity_interval.plan_item_id (uuid, FK plan_item ON DELETE SET NULL) with a partial index, so a timer started on a task of the day can name it

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e5a7b9d1f4"
down_revision: str | None = "a9c1e3f5b7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMN = "plan_item_id"
FK_NAME = "fk_activity_interval_plan_item_id"
INDEX_NAME = "ix_activity_interval_plan_item"


def upgrade() -> None:
    op.add_column(
        "activity_interval",
        sa.Column(COLUMN, postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        FK_NAME,
        "activity_interval",
        "plan_item",
        [COLUMN],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        INDEX_NAME,
        "activity_interval",
        [COLUMN],
        postgresql_where=sa.text("plan_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="activity_interval")
    op.drop_constraint(FK_NAME, "activity_interval", type_="foreignkey")
    op.drop_column("activity_interval", COLUMN)
