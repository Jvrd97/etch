"""day_summary: stage of closing and one idempotency key per touch

Revision ID: b9e1d3f5a7c2
Revises: c3e5a7b9d1f2
Create Date: 2026-09-02 10:00:00.000000+00:00

Закрытие дня идёт в два касания — около 15:40 факт по рабочим задачам, вечером
якоря и вердикт, — и до сих пор в базе это было одно событие. Здесь у строки
итога появляется стадия и по ключу идемпотентности на каждое касание.

ADR-0015 описывал под это отдельную таблицу `day_closing`. Она не заводится:
итог дня уже целиком в `day_summary`, и двух хранилищ одного итога в одной базе
быть не должно.

Обратима полностью. `upgrade` добавляет четыре колонки; существующие строки
получают `stage='closed'` из server_default — они и есть закрытые дни. `reviewed_at`
у них остаётся NULL, то есть день читается как закрытый одним касанием, что
исторической правде и соответствует: второго касания тогда не существовало.
`downgrade` снимает те же четыре колонки и два их ограничения, не трогая ни
вердиктов, ни прозы.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9e1d3f5a7c2"
down_revision: Union[str, None] = "c3e5a7b9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "day_summary",
        # `closed` по умолчанию — так строка, написанная импортом или
        # существовавшая до этой ревизии, читается как закрытый день, каким она
        # и является. `open` колонка принимает ради одного словаря на всю
        # систему: живой блок незакрытого дня отвечает тем же словом.
        sa.Column("stage", sa.Text(), server_default="closed", nullable=False),
    )
    op.add_column(
        "day_summary",
        # NULL — касания 15:40 не было. Отдельной колонки под `review_skipped`
        # нет: она была бы вторым ответом на тот же вопрос.
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "day_summary", sa.Column("review_idempotency_key", sa.Text(), nullable=True)
    )
    op.add_column(
        "day_summary", sa.Column("final_idempotency_key", sa.Text(), nullable=True)
    )

    op.create_check_constraint(
        "ck_day_summary_stage",
        "day_summary",
        "stage IN ('open', 'reviewed', 'closed')",
    )
    # «До `final` вердикта нет»: `verdict = NULL` на стадии `reviewed` значит
    # «рано», а не «проиграл». Правило базы, а не сервиса — вердикт, записанный
    # на полузакрытый день, потом уже не отличить от вечернего.
    op.create_check_constraint(
        "ck_day_summary_verdict_needs_closed",
        "day_summary",
        "stage = 'closed' OR verdict IS NULL",
    )
    # Один ключ закрывает одно касание одного дня. NULL уникальности в postgres
    # не нарушает, так что касаний без ключа может быть сколько угодно.
    op.create_unique_constraint(
        "uq_day_summary_review_idempotency_key",
        "day_summary",
        ["review_idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_day_summary_final_idempotency_key",
        "day_summary",
        ["final_idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_day_summary_final_idempotency_key", "day_summary", type_="unique"
    )
    op.drop_constraint(
        "uq_day_summary_review_idempotency_key", "day_summary", type_="unique"
    )
    op.drop_constraint(
        "ck_day_summary_verdict_needs_closed", "day_summary", type_="check"
    )
    op.drop_constraint("ck_day_summary_stage", "day_summary", type_="check")
    op.drop_column("day_summary", "final_idempotency_key")
    op.drop_column("day_summary", "review_idempotency_key")
    op.drop_column("day_summary", "reviewed_at")
    op.drop_column("day_summary", "stage")
