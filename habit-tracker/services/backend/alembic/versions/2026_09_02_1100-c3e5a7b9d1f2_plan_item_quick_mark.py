"""plan_item.quick_mark_id — the line of the plan that names a button

План дня и есть список того, что сегодня надо отметить, и без этой колонки связь
между ним и справочником кнопок существует только в голове. Ссылка идёт из
`plan_item` в `quick_marks`, а не наоборот: план дня — событие одного дня, а
кнопка живёт месяцами, и складывать id дня в справочник значило бы переписывать
справочник каждое утро.

`ON DELETE SET NULL`, потому что кнопку удаляют, а прожитый день остаётся.
Пункт плана, чья кнопка исчезла из справочника, — это обычный пункт, который
отмечают руками, а не строка, роняющая чтение дня.

Обратимость полная: колонка и её индекс удаляются, данные `#87` не трогаются.

Revision ID: c3e5a7b9d1f2
Revises: a8d0c2e4b6f1
Create Date: 2026-09-02 11:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e5a7b9d1f2"
down_revision: Union[str, None] = "a8d0c2e4b6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plan_item",
        sa.Column("quick_mark_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_plan_item_quick_mark_id",
        "plan_item",
        "quick_marks",
        ["quick_mark_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Частичный: кнопку называет меньшинство пунктов, а выборка «что из плана
    # сегодня отмечается кнопкой» ходит по дню и обязана быть дешёвой.
    op.create_index(
        "ix_plan_item_quick_mark_id",
        "plan_item",
        ["quick_mark_id"],
        postgresql_where=sa.text("quick_mark_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_plan_item_quick_mark_id", table_name="plan_item")
    op.drop_constraint("fk_plan_item_quick_mark_id", "plan_item", type_="foreignkey")
    op.drop_column("plan_item", "quick_mark_id")
