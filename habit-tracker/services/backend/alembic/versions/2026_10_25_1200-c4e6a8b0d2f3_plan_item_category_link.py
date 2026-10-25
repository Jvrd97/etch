"""plan_item.category_id/field_id/target_value and entries.plan_item_id

Строка плана «Отжимания, 300» называет категорию, её поле и цель, а введённое
в плане «сделал 300» становится обычной записью этой категории (`#200`,
ADR-0023). Отдельной истории измерений нет: факт лежит в `entries` и
`entry_values`, там же, где его читают история категории, итоги и стрики.

Ссылка пункта на категорию и поле — `ON DELETE SET NULL`, как у
`quick_mark_id`: категорию и поле удаляют, а прожитый день остаётся, и пункт
без категории — это обычный пункт.

`entries.plan_item_id` внешнего ключа не имеет намеренно: план заменяется
целиком, его строки удаляются и вставляются заново под тем же id, и каскад
либо стёр бы историю категории, либо обнулял бы связь на каждой правке плана.

Обратимость полная: колонки и индексы удаляются, записи категорий остаются.

Revision ID: c4e6a8b0d2f3
Revises: a9c1e3f5b7d0
Create Date: 2026-10-25 12:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/200
# summary: reversible link of a plan line to a category, its field and a target, plus the plan line a category entry was typed into

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e6a8b0d2f3"
down_revision: str | None = "a9c1e3f5b7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Та же форма числа, что у `quick_marks.step` (ADR-0018).
TARGET_PRECISION = 12
TARGET_SCALE = 3


def upgrade() -> None:
    op.add_column("plan_item", sa.Column("category_id", sa.Integer(), nullable=True))
    op.add_column("plan_item", sa.Column("field_id", sa.Integer(), nullable=True))
    op.add_column(
        "plan_item",
        sa.Column(
            "target_value",
            sa.Numeric(TARGET_PRECISION, TARGET_SCALE),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_plan_item_category_id",
        "plan_item",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_plan_item_field_id",
        "plan_item",
        "fields",
        ["field_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Частичный: категорию называет меньшинство пунктов, а удаление категории
    # обязано найти свои пункты без прохода по всему плану.
    op.create_index(
        "ix_plan_item_category_id",
        "plan_item",
        ["category_id"],
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )

    op.add_column(
        "entries",
        sa.Column("plan_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_entries_plan_item_id",
        "entries",
        ["plan_item_id"],
        postgresql_where=sa.text("plan_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_entries_plan_item_id", table_name="entries")
    op.drop_column("entries", "plan_item_id")

    op.drop_index("ix_plan_item_category_id", table_name="plan_item")
    op.drop_constraint("fk_plan_item_field_id", "plan_item", type_="foreignkey")
    op.drop_constraint("fk_plan_item_category_id", "plan_item", type_="foreignkey")
    op.drop_column("plan_item", "target_value")
    op.drop_column("plan_item", "field_id")
    op.drop_column("plan_item", "category_id")
