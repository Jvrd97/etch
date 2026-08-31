"""day_plan: авторство llm/fallback и код причины запасного пути

Кем собран план — часть состояния дня. До этой ревизии `ck_day_plan_source`
знал три слова, и план, собранный моделью, был неотличим от написанного
руками; скелет, собранный потому что модель молчала, — тоже.

`fallback_reason` заполняется только у `source='fallback'` и хранит код, а не
предложение: `llm_timeout`, `llm_error`, `llm_not_configured`,
`llm_plan_invalid`. Его читает экран дня и сверяет тест.

Revision ID: e5a7c9b1d3f6
Revises: d4f6a8c0e2b5
Create Date: 2026-09-02 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.checks import in_list
from app.models.plan import PLAN_SOURCES

# revision identifiers, used by Alembic.
revision: str = "e5a7c9b1d3f6"
down_revision: Union[str, None] = "d4f6a8c0e2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Словарь авторства до этой ревизии — то, к чему возвращает `downgrade`.
SOURCES_BEFORE: tuple[str, ...] = ("day-open", "import", "manual")


def upgrade() -> None:
    op.add_column(
        "day_plan", sa.Column("fallback_reason", sa.String(length=32), nullable=True)
    )
    op.drop_constraint("ck_day_plan_source", "day_plan", type_="check")
    op.create_check_constraint(
        "ck_day_plan_source", "day_plan", in_list("source", PLAN_SOURCES)
    )


def downgrade() -> None:
    # Планы, собранные моделью и скелетом, вниз не удаляются: это прожитые дни,
    # а не служебные строки. Они возвращаются к `manual` — слову, которое до
    # #148 и означало «собрано не из /day-open»; авторство при этом теряется,
    # и это честная цена отката, а не потеря дня.
    op.execute("UPDATE day_plan SET source = 'manual' WHERE source IN ('llm', 'fallback')")
    op.drop_constraint("ck_day_plan_source", "day_plan", type_="check")
    op.create_check_constraint(
        "ck_day_plan_source", "day_plan", in_list("source", SOURCES_BEFORE)
    )
    op.drop_column("day_plan", "fallback_reason")
