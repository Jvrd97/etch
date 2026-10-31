"""supplements: the Idempotency-Key of the create

Revision ID: a2c4e6f8b0d3
Revises: c3d5e7f9a1b4
Create Date: 2026-10-31 10:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/259
# summary: reversible — nullable `supplements.idempotency_key` with a unique constraint, so a retried create returns the first supplement; existing rows stay NULL

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c4e6f8b0d3"
down_revision: str | None = "c3d5e7f9a1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY_MAX_LENGTH = 255
CONSTRAINT = "uq_supplements_idempotency_key"


def upgrade() -> None:
    op.add_column(
        "supplements",
        sa.Column("idempotency_key", sa.String(length=KEY_MAX_LENGTH), nullable=True),
    )
    op.create_unique_constraint(CONSTRAINT, "supplements", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "supplements", type_="unique")
    op.drop_column("supplements", "idempotency_key")
