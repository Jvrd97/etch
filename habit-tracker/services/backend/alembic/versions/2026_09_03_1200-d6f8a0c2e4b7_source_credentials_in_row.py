"""signal_sources: зашифрованный секрет и настройки в строке источника

Первый срез контура назвал секрет именем env-переменной. Это стоило человеку
доступа к машине: подключить второй воркспейс ClickUp значило зайти на VPS,
править `.env` и пересобирать контейнер. Источник обязан становиться рабочим из
интерфейса — иначе «добавить рабочий ClickUp» это задача на выкат.

Секрет лежит зашифрованным (`app/inbox/credentials.py`, Fernet, ключ выведен из
`SESSION_SECRET` и в дамп не попадает). Цена названа прямо: сам шифротекст в
дампе будет, и против того, у кого есть и дамп, и машина, это не защищает — у
такого человека есть и `.env`.

`settings` — непрозрачный jsonb под настройки адаптера: у ClickUp это числовой
id воркспейса, у Gmail будут лейблы. Типизированной колонки под них нет по той
же причине, по какой её нет у курсора: две из трёх всегда пустые.

`label` — человеческая подпись источника («Личный», «Alvion»): её вписывает
человек, а не тянет адаптер (ADR-0016, D2).

`poll_interval_s` приезжает сюда же, чтобы воркер `#99` читал расписание из
строки, а не из константы.

Обратимость полная.

Revision ID: d6f8a0c2e4b7
Revises: c5e7a9b1d3f6
Create Date: 2026-09-03 12:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6f8a0c2e4b7"
down_revision: Union[str, None] = "c5e7a9b1d3f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "signal_sources", sa.Column("secret_ciphertext", sa.Text(), nullable=True)
    )
    op.add_column(
        "signal_sources",
        sa.Column("settings", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column("signal_sources", sa.Column("label", sa.String(length=100), nullable=True))
    op.add_column(
        "signal_sources",
        sa.Column(
            "poll_interval_s", sa.Integer(), server_default="900", nullable=False
        ),
    )

    # Подписи заготовкам: экран показывает «Личный ClickUp», а не `clickup/personal`.
    sources = sa.table(
        "signal_sources",
        sa.column("provider", sa.String),
        sa.column("account", sa.String),
        sa.column("label", sa.String),
    )
    for provider, account, label in (
        ("clickup", "personal", "Личный ClickUp"),
        ("clickup", "alvion", "Рабочий ClickUp (Alvion)"),
        ("gmail", "personal", "Личная почта"),
        ("telegram", "personal", "Telegram"),
    ):
        op.execute(
            sources.update()
            .where(sources.c.provider == provider)
            .where(sources.c.account == account)
            .values(label=label)
        )


def downgrade() -> None:
    op.drop_column("signal_sources", "poll_interval_s")
    op.drop_column("signal_sources", "label")
    op.drop_column("signal_sources", "settings")
    op.drop_column("signal_sources", "secret_ciphertext")
