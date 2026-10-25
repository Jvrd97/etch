"""merge inbox observability and passkey login heads

Revision ID: 351c4562b15c
Revises: h0d2f4a6c8e1, b1d3f5a7c9e2
Create Date: 2026-10-25 20:19:27.175339+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '351c4562b15c'
down_revision: Union[str, None] = ('h0d2f4a6c8e1', 'b1d3f5a7c9e2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
