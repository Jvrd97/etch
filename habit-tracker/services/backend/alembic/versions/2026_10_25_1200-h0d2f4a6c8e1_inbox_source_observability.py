"""signal_sources: время последней ошибки и число сигналов последнего прогона

Экран источников обязан отвечать на вопрос «пусто, потому что ничего не пришло,
или потому что сломалось». Для этого рядом с `last_polled_at` (последний
успешный прогон) нужны две вещи: когда случился последний отказ и сколько новых
сигналов принёс последний удачный прогон.

`last_error_code` остаётся как был: класс отказа (`auth_expired`, `needs_login`…)
выводится из кода в `app/inbox/errors.py` и отдельной колонки не получает.

Обратимость полная.

Revision ID: h0d2f4a6c8e1
Revises: a9c1e3f5b7d0
Create Date: 2026-10-25 12:00:00.000000+00:00

"""

# [review:need-review] PHASE-03/105
# summary: adds signal_sources.last_error_at and last_ingested for the sources screen

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h0d2f4a6c8e1"
down_revision: Union[str, None] = "a9c1e3f5b7d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "signal_sources",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "signal_sources", sa.Column("last_ingested", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("signal_sources", "last_ingested")
    op.drop_column("signal_sources", "last_error_at")
