"""agent_setting — рубильник сбора заголовков и интервал семплирования

`agent_heartbeat.titles_enabled` — то, что агент **сообщает о себе**, и на роль
рубильника оно не годится: агент перезаписывал бы его на каждом ударе сердца, и
выключенный из веба сбор заголовков включался бы обратно через пять секунд.

Поэтому решение живёт отдельной строкой на стороне сервера, а `GET
/api/v1/agent/config` отдаёт её агенту. Одна строка на всю систему (`id = 1`) —
пользователь один, а таблица на одну строку читается лучше, чем колонка в
чужой таблице или ключ-значение без типов.

Строка заводится сидом: конфиг, который может не существовать, — это ветка «а
если строки нет» в каждом читателе.

`titles_enabled` по умолчанию **true**: политика заголовков и так default deny
(`title_rule` начинается с запретов, `tracked_app.title_policy = 'drop'`), и
второй запрет поверх неё означал бы, что разрешающие правила молча не работают.
Рубильник — это «выключить всё разом», а не второй слой умолчания.

Обратимость полная: `downgrade()` роняет таблицу вместе с сидом.

Revision ID: f2e4a6c8b0d1
Revises: e1d3f5a7c9b0
Create Date: 2026-09-02 14:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2e4a6c8b0d1"
down_revision: Union[str, None] = "e1d3f5a7c9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Дословный близнец `app.models.activity.SETTINGS_ROW_ID`.
SETTINGS_ROW_ID = 1

# Значения по умолчанию: сбор заголовков включён, опрос раз в пять секунд —
# то же, что и `agent_heartbeat.sampling_seconds` по умолчанию.
DEFAULT_TITLES_ENABLED = True
DEFAULT_SAMPLING_SECONDS = 5


def upgrade() -> None:
    op.create_table(
        "agent_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "titles_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "sampling_seconds", sa.Integer(), server_default="5", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_agent_setting_single_row"),
        sa.CheckConstraint(
            "sampling_seconds BETWEEN 1 AND 600", name="ck_agent_setting_sampling"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    settings = sa.table(
        "agent_setting",
        sa.column("id", sa.Integer),
        sa.column("titles_enabled", sa.Boolean),
        sa.column("sampling_seconds", sa.Integer),
    )
    op.bulk_insert(
        settings,
        [
            {
                "id": SETTINGS_ROW_ID,
                "titles_enabled": DEFAULT_TITLES_ENABLED,
                "sampling_seconds": DEFAULT_SAMPLING_SECONDS,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("agent_setting")
