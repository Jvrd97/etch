"""plan item editing — who touched the line, when, and the position nobody may duplicate

Три вещи, которых #87 не завёл, потому что план приезжал документом целиком и
правился только заменой.

`edited_by` и `updated_at` отвечают на вопрос «эту строку правил человек или
машина». Без них #150 нечего журналировать, а асимметрия строгости из #147
(машине нарушение блокирует запись, человеку — нет) не имеет опоры в данных.

`uq_plan_item_position` делает позицию уникальной внутри уровня. Уровень — это
`(section_id, parent_id)`: `ord` в #87 нумерует братьев между собой, а не всю
секцию, поэтому уникальность по `(section_id, ord)` была бы ложной — родитель на
позиции 0 и его ребёнок на позиции 0 живут в одной секции законно. `NULLS NOT
DISTINCT` нужен ровно затем, чтобы правило действовало и для корневых пунктов, у
которых `parent_id` пуст (PostgreSQL 15+). `DEFERRABLE INITIALLY DEFERRED` —
чтобы перестановка внутри одной транзакции проходила через промежуточное
состояние с дублями и падала только на коммите, если дубли остались.

Обратимость полная: ограничение снимается, колонки удаляются, данные #87
остаются как были.

Revision ID: b2d4f6a8c0e3
Revises: c8f0a2b4d6e7
Create Date: 2026-09-02 09:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c0e3"
down_revision: Union[str, None] = "c8f0a2b4d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Кто последним трогал строку. Три значения, а не булев «человек ли»: правка
# скиллом `/day-open` и правка агентом чата — разные источники, и различать их
# придётся раньше, чем кто-нибудь захочет добавить четвёртое.
EDITORS = ("human", "ai", "skill")

# Позиция уникальна внутри уровня. Дословно повторено в `app/models/plan.py`:
# миграция — снимок, и импорт кода приложения сюда сделал бы её зависимой от
# того, как модель выглядит сегодня, а не от того, как выглядела тогда.
POSITION_UNIQUE = (
    "ALTER TABLE plan_item ADD CONSTRAINT uq_plan_item_position "
    "UNIQUE NULLS NOT DISTINCT (section_id, parent_id, ord) "
    "DEFERRABLE INITIALLY DEFERRED"
)


def upgrade() -> None:
    op.add_column(
        "plan_item",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "plan_item",
        sa.Column(
            "edited_by",
            sa.String(length=8),
            server_default="ai",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_plan_item_edited_by",
        "plan_item",
        "edited_by IN ('" + "', '".join(EDITORS) + "')",
    )
    op.execute(POSITION_UNIQUE)


def downgrade() -> None:
    op.drop_constraint("uq_plan_item_position", "plan_item", type_="unique")
    op.drop_constraint("ck_plan_item_edited_by", "plan_item", type_="check")
    op.drop_column("plan_item", "edited_by")
    op.drop_column("plan_item", "updated_at")
