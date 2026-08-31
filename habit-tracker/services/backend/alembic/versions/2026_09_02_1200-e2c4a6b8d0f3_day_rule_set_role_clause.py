"""day_rule_set += role_clause_enabled/role_clause_roles — клауз роли в вердикте дня

Клауз добавляется двумя полями строки канона, а не четвёртой таблицей правил
(как описывал ADR-0020): версионированный канон дня уже существует как
`day_rule_set` с интервалом `[valid_from, valid_to)`, и двух версионированных
критериев в одной базе быть не должно. Смысл ADR сохранён целиком — день
навсегда оценён правилами своего времени, смена критерия остаётся новой строкой.

Данные: действующая строка получает клауз включённым, историческая (`legacy`,
`valid_to IS NOT NULL`) — выключенным. Причина: в момент действия легаси-правила
роли не измерялись вовсе — таблиц `role_time_block` и `role_act` не было, —
и день июля, объявленный проигранным за отсутствие акта, был бы объявлен
проигранным за то, чего в тот день нельзя было ни сделать, ни записать.

Revision ID: e2c4a6b8d0f3
Revises: f7c9e1a3b5d8
Create Date: 2026-09-02 12:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c4a6b8d0f3"
down_revision: Union[str, None] = "f7c9e1a3b5d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Те же значения, что у колонок в `app.models.day`. Продублированы намеренно:
# миграция обязана читаться через год без импорта кода, который к тому времени
# уже переписан.
DEFAULT_ROLE_CLAUSE_ROLES = "cto,architect"


def upgrade() -> None:
    op.add_column(
        "day_rule_set",
        sa.Column(
            "role_clause_enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )
    op.add_column(
        "day_rule_set",
        sa.Column(
            "role_clause_roles",
            sa.String(length=100),
            server_default=DEFAULT_ROLE_CLAUSE_ROLES,
            nullable=False,
        ),
    )
    # Закрытая строка канона — это правило, под которым уже прожили дни. Роли в
    # те дни не измерялись, поэтому клауз на них выключается: иначе первый же
    # пересчёт истории объявил бы проигранным каждый импортированный день.
    op.execute(
        "UPDATE day_rule_set SET role_clause_enabled = false "
        "WHERE valid_to IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("day_rule_set", "role_clause_roles")
    op.drop_column("day_rule_set", "role_clause_enabled")
