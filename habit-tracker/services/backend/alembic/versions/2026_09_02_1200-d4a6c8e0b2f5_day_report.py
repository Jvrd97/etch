"""day_report

Revision ID: d4a6c8e0b2f5
Revises: f7c9e1a3b5d8
Create Date: 2026-09-02 12:00:00.000000+00:00

Отчёт дня переезжает из файла `plans/**/<дата>.report.md` в строку с ревизиями.
`down_revision` вписан по фактическому `alembic heads` этой ветки на момент
реализации, а не взят из текста тикета.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4a6c8e0b2f5"
down_revision: Union[str, None] = "f7c9e1a3b5d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Словарь поводов сборки, написанный здесь целиком. Миграция обязана значить то
# же, что значила в день прогона: импорт `app.models.day_report` дал бы пятому
# поводу право переписать этот CHECK задним числом.
REPORT_TRIGGERS = ("close", "button", "nightly", "api")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "day_report",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["day_date"], ["day.date"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            _in_list("trigger", REPORT_TRIGGERS), name="ck_day_report_trigger"
        ),
        sa.UniqueConstraint("day_date", "revision", name="uq_day_report_revision"),
    )
    op.create_index("ix_day_report_day_date", "day_report", ["day_date"])


def downgrade() -> None:
    op.drop_index("ix_day_report_day_date", table_name="day_report")
    op.drop_table("day_report")
