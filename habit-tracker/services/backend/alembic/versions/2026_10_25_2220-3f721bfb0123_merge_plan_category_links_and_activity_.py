"""merge plan category links and activity plan item heads

Revision ID: 3f721bfb0123
Revises: c4e6a8b0d2f3, c3e5a7b9d1f4
Create Date: 2026-10-25 22:20:22.220391+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f721bfb0123'
down_revision: Union[str, None] = ('c4e6a8b0d2f3', 'c3e5a7b9d1f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
