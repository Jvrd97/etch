"""challenge.origin и статус proposed — кто предложил обязательство

Две вещи, а не одна. Колонка `origin` отвечает на вопрос «кто это предложил»,
на правила расчёта источник не влияет. И словарь статусов расширяется: у
`challenges` стоит `ck_challenge_status`, перечисляющий четыре слова, поэтому
`proposed` без правки этого CHECK база просто не примет — что тесты на
`create_all` не заметили бы, а прод заметил бы сразу.

Существующие строки получают `human`. Другого пути завести челлендж до #129 не
было, так что это не догадка, а факт о прошлом.

Revision ID: d4f6a8c0e2b5
Revises: f7c9e1a3b5d8
Create Date: 2026-09-02 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.challenge import CHALLENGE_ORIGINS, CHALLENGE_STATUSES
from app.models.checks import in_list

# revision identifiers, used by Alembic.
revision: str = "d4f6a8c0e2b5"
down_revision: Union[str, None] = "a7f9c1e3b5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Словарь статусов до этой ревизии — то, к чему возвращает `downgrade`.
STATUSES_BEFORE: tuple[str, ...] = ("active", "won", "failed", "abandoned")


def upgrade() -> None:
    op.add_column(
        "challenges",
        sa.Column(
            "origin",
            sa.String(length=6),
            nullable=False,
            server_default="human",
        ),
    )
    op.create_check_constraint(
        "ck_challenge_origin", "challenges", in_list("origin", CHALLENGE_ORIGINS)
    )
    op.drop_constraint("ck_challenge_status", "challenges", type_="check")
    op.create_check_constraint(
        "ck_challenge_status", "challenges", in_list("status", CHALLENGE_STATUSES)
    )


def downgrade() -> None:
    # Предложенные челленджи вместе с колонкой теряют признак «это предложение»
    # и стали бы неотличимы от взятых на себя обязательств. Поэтому вниз они
    # уезжают целиком: строка, которой человек не говорил «да», не должна
    # остаться в базе как обещание. Удалять их приходится до сужения CHECK —
    # иначе он не наложится на собственные данные таблицы.
    op.execute("DELETE FROM challenges WHERE status = 'proposed'")
    op.drop_constraint("ck_challenge_status", "challenges", type_="check")
    op.create_check_constraint(
        "ck_challenge_status", "challenges", in_list("status", STATUSES_BEFORE)
    )
    op.drop_constraint("ck_challenge_origin", "challenges", type_="check")
    op.drop_column("challenges", "origin")
