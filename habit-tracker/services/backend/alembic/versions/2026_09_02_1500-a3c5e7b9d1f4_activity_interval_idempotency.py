"""activity_interval.idempotency_key — ключ ручной записи интервала

Естественный ключ `(source, started_at, app_id)` ручную запись не ловит: у неё
`app_id IS NULL`, а NULL в уникальном ключе Postgres различны. Это правильно —
человек вправе записать два дела в одно окно времени, и схлопывать их нельзя.
Но тогда повторный `POST` после обрыва связи создаёт второй интервал, и день
растёт на ровном месте.

Идемпотентность ручной записи даёт заголовок `Idempotency-Key`, как у
`entries.idempotency_key`. Индекс частичный: ключ есть только у ручных записей,
и NULL у остальных не должны мешать друг другу.

Обратимость полная: `downgrade()` снимает колонку и индекс.

Revision ID: a3c5e7b9d1f4
Revises: f2e4a6c8b0d1
Create Date: 2026-09-02 15:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c5e7b9d1f4"
down_revision: Union[str, None] = "f2e4a6c8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Длина ключа. Та же, что у `entries.idempotency_key`: клиент присылает uuid, а
# два разных потолка на одно и то же значение — это два места, где оно однажды
# обрежется по-разному.
KEY_LENGTH = 100


def upgrade() -> None:
    op.add_column(
        "activity_interval",
        sa.Column("idempotency_key", sa.String(length=KEY_LENGTH), nullable=True),
    )
    op.create_index(
        "uq_activity_interval_idempotency",
        "activity_interval",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_activity_interval_idempotency", table_name="activity_interval")
    op.drop_column("activity_interval", "idempotency_key")
