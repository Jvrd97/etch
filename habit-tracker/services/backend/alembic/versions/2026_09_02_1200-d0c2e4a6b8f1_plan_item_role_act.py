"""plan_item.act_kind / plan_item.role_id / plan_section.role_id — план как источник ролей

`feedback.md` формулирует это одной строкой: «минимум без своей галочки не
работает». Акт роли, который заводят отдельной формой на отдельном экране, не
заводится: счётчик «написано с нуля 0/3» простоял шесть недель именно так. Акт
должен закрываться там, где человек и так отмечает день, — в плане.

Отсюда три колонки. Пункт плана несёт намерение на акт (`act_kind` + `role_id`):
отметка пункта выполненным закрывает `role_act` с `source='plan'` и
`external_ref = plan_item.id`. Секция плана несёт роль (`role_id`): её окна
становятся минутами `role_time_block` с `source='plan'`, вытесняя автоматику
агента за те же часы.

`ON DELETE SET NULL` у обеих ссылок на `role`: роль убирают из справочника, а
прожитый день остаётся. Пункт без роли — обычный пункт, а не строка, роняющая
чтение дня. Строка `RESTRICT`, как у `role_rule`, запретила бы правку
справочника из-за плана трёхмесячной давности.

`act_kind` — обычная строка без CHECK, как и в `role_act`: словарь видов акта
живёт в `app/schemas/role.py` и растёт правкой схемы, а не миграцией.

Обратимость полная: `downgrade()` снимает три колонки и обе внешние ссылки,
планы и роли не трогаются.

Revision ID: d0c2e4a6b8f1
Revises: f7c9e1a3b5d8
Create Date: 2026-09-02 12:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0c2e4a6b8f1"
down_revision: Union[str, None] = "e2c4a6b8d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Длина словарного поля, та же, что у `role_act.act_kind`: одно значение
# описывается одним типом в обеих таблицах, иначе вид акта, влезший в план,
# однажды не влезет в акт.
ACT_KIND_LENGTH = 40


def upgrade() -> None:
    op.add_column(
        "plan_item",
        sa.Column("act_kind", sa.String(length=ACT_KIND_LENGTH), nullable=True),
    )
    op.add_column("plan_item", sa.Column("role_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_plan_item_role_id",
        "plan_item",
        "role",
        ["role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Частичный: роль называет меньшинство пунктов, а выборка «какие пункты дня
    # несут намерение на акт» ходит по плану и обязана быть дешёвой.
    op.create_index(
        "ix_plan_item_role_id",
        "plan_item",
        ["role_id"],
        postgresql_where=sa.text("role_id IS NOT NULL"),
    )

    op.add_column("plan_section", sa.Column("role_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_plan_section_role_id",
        "plan_section",
        "role",
        ["role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_plan_section_role_id",
        "plan_section",
        ["role_id"],
        postgresql_where=sa.text("role_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_plan_section_role_id", table_name="plan_section")
    op.drop_constraint("fk_plan_section_role_id", "plan_section", type_="foreignkey")
    op.drop_column("plan_section", "role_id")

    op.drop_index("ix_plan_item_role_id", table_name="plan_item")
    op.drop_constraint("fk_plan_item_role_id", "plan_item", type_="foreignkey")
    op.drop_column("plan_item", "role_id")
    op.drop_column("plan_item", "act_kind")
