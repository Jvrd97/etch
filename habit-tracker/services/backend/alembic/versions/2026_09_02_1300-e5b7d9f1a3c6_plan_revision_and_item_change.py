"""plan_revision and plan_item_change

Revision ID: e5b7d9f1a3c6
Revises: d4a6c8e0b2f5
Create Date: 2026-09-02 13:00:00.000000+00:00

`down_revision` вписан по фактическому `alembic heads` этой ветки на момент
реализации (`d4a6c8e0b2f5`, `day_report` из `#145`), а не взят из текста тикета.

`plan_revision.job_id` заводится без внешнего ключа: таблицы задач (`day_job`,
`#95`/`#149`) в этой ветке ещё нет. Внешний ключ на `day_report` настоящий —
таблица приехала предыдущей ревизией.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5b7d9f1a3c6"
down_revision: Union[str, None] = "d4a6c8e0b2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Два словаря, написанные здесь целиком. Миграция обязана значить то же, что
# значила в день прогона: импорт `app.models.plan_revision` дал бы пятому автору
# право переписать этот CHECK задним числом.
REVISION_AUTHORS = ("ai", "fallback", "human", "skill")
CHANGE_FIELDS = ("window_start", "window_end", "text", "ord", "section_id", "status")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "plan_revision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(length=8), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["day_report.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            _in_list("author", REVISION_AUTHORS), name="ck_plan_revision_author"
        ),
        sa.UniqueConstraint("day_date", "revision", name="uq_plan_revision_number"),
    )
    op.create_index("ix_plan_revision_day_date", "plan_revision", ["day_date"])

    op.create_table(
        "plan_item_change",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("field", sa.String(length=16), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=8), nullable=False),
        sa.Column("revision_from", sa.Integer(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_item_id"], ["plan_item.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            _in_list("field", CHANGE_FIELDS), name="ck_plan_item_change_field"
        ),
        sa.CheckConstraint(
            _in_list("author", REVISION_AUTHORS), name="ck_plan_item_change_author"
        ),
    )
    op.create_index(
        "ix_plan_item_change_plan_item_id", "plan_item_change", ["plan_item_id"]
    )
    op.create_index(
        "ix_plan_item_change_day", "plan_item_change", ["day_date", "changed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_plan_item_change_day", table_name="plan_item_change")
    op.drop_index("ix_plan_item_change_plan_item_id", table_name="plan_item_change")
    op.drop_table("plan_item_change")
    op.drop_index("ix_plan_revision_day_date", table_name="plan_revision")
    op.drop_table("plan_revision")
