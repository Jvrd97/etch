"""category primary field

Revision ID: e7a9c1b3d5f8
Revises: d6f8a0c2e4b7
Create Date: 2026-09-04 12:00:00.000000+00:00

"""

# [review:need-review] 175
# summary: add the optional category primary field foreign key with SET NULL deletion

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a9c1b3d5f8"
down_revision: Union[str, None] = "d6f8a0c2e4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FOREIGN_KEY_NAME = "fk_categories_primary_field_id_fields"


def upgrade() -> None:
    op.add_column(
        "categories", sa.Column("primary_field_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        FOREIGN_KEY_NAME,
        "categories",
        "fields",
        ["primary_field_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(FOREIGN_KEY_NAME, "categories", type_="foreignkey")
    op.drop_column("categories", "primary_field_id")
