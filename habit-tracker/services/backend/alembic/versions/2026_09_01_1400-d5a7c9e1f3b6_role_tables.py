"""role, role_rule, role_time_block, role_act — роли становятся данными

Четыре таблицы одной ревизией: порознь они бесполезны — правило без справочника
некуда указать, минуты без роли не с чем сложить.

Сид четырёх ролей спеллен здесь заново, а не импортирован из `app/`: миграция,
которая импортирует приложение, ломается в день рефакторинга приложения. Та же
четвёрка живёт в `app/roles/catalog.py` для баз, собранных `create_all` (тесты
миграций не видят), и обе копии идемпотентны.

Revision ID: d5a7c9e1f3b6
Revises: c4f6b8d0e2a5
Create Date: 2026-09-01 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5a7c9e1f3b6"
down_revision: Union[str, None] = "c4f6b8d0e2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Стартовые доли 25/25/50 — гипотеза квартала, не норма дня, ровно в том же
# смысле, в каком подъём 6:00 в `config.md` помечен гипотезой.
SEED_ROLES: tuple[tuple[str, str, str, int | None, int], ...] = (
    (
        "cto",
        "CTO",
        "Стратегия, роадмап, стек, бюджет, найм, отчёт руководству, "
        "партнёры и инвесторы.",
        25,
        1,
    ),
    (
        "architect",
        "Системный архитектор",
        "Микросервисы, событийное взаимодействие, модель данных, "
        "безопасность медданных, ADR.",
        25,
        2,
    ),
    (
        "techlead",
        "Тимлид",
        "Code review, стандарты качества, CI/CD, собственный код на "
        "Python/FastAPI, iOS/Swift и вебе.",
        50,
        3,
    ),
    (
        "unassigned",
        "Не отнесено",
        "Работа, которую не удалось отнести ни к одной роли.",
        None,
        9,
    ),
)


def upgrade() -> None:
    op.create_table(
        "role",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # Код, а не название: на него ссылаются правила, минуты и акты, а
        # название человек перепишет.
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Гипотеза, а не измерение: меняется от квартала к кварталу.
        sa.Column("target_share_pct", sa.SmallInteger(), nullable=True),
        sa.Column("is_work", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("ord", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_role_id"), "role", ["id"])
    op.create_index(op.f("ix_role_code"), "role", ["code"], unique=True)

    op.create_table(
        "role_rule",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("matcher_kind", sa.String(length=30), nullable=False),
        sa.Column("pattern", sa.String(length=500), nullable=False),
        # Меньше — сильнее. Значение по умолчанию посередине, чтобы новое
        # правило можно было сделать и сильнее, и слабее, не перенумеровывая.
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # RESTRICT: удалить роль из-под правил, которые её называют, значит
        # молча превратить разметку в `unassigned`.
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_role_rule_id"), "role_rule", ["id"])
    op.create_index(op.f("ix_role_rule_role_id"), "role_rule", ["role_id"])
    op.create_index(
        "ix_role_rule_source_priority", "role_rule", ["source", "priority"]
    )

    op.create_table(
        "role_time_block",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_day", sa.Date(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        # NULL у ручной записи «полтора часа на найм»: интервал, концов
        # которого никто не засекал.
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column(
            "confidence", sa.String(length=10), server_default="auto", nullable=False
        ),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="RESTRICT"),
        # SET NULL: потерять правило — не повод потерять минуты.
        sa.ForeignKeyConstraint(["rule_id"], ["role_rule.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # Ноль минут отвергает база, а не сервис: через `psql` и через импортёр
        # тоже.
        sa.CheckConstraint("minutes > 0", name="ck_role_time_block_minutes_positive"),
    )
    op.create_index(op.f("ix_role_time_block_id"), "role_time_block", ["id"])
    op.create_index(
        op.f("ix_role_time_block_work_day"), "role_time_block", ["work_day"]
    )
    op.create_index(op.f("ix_role_time_block_role_id"), "role_time_block", ["role_id"])
    # Частичный уникальный: повторная отправка того же коммита или той же задачи
    # ложится на ту же строку, а ручные записи без `external_ref` под ограничение
    # не попадают — две честные записи по 90 минут это две записи.
    op.create_index(
        "ix_role_time_block_external",
        "role_time_block",
        ["source", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_role_time_block_day_role", "role_time_block", ["work_day", "role_id"]
    )

    op.create_table(
        "role_act",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_day", sa.Date(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("act_kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "confidence", sa.String(length=10), server_default="auto", nullable=False
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_role_act_id"), "role_act", ["id"])
    op.create_index(op.f("ix_role_act_work_day"), "role_act", ["work_day"])
    op.create_index(op.f("ix_role_act_role_id"), "role_act", ["role_id"])
    op.create_index(
        "ix_role_act_external",
        "role_act",
        ["source", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_index("ix_role_act_day_role", "role_act", ["work_day", "role_id"])

    _seed_roles()


def _seed_roles() -> None:
    """
    Завести четыре роли, не трогая те, что уже есть.

    `ON CONFLICT DO NOTHING` по коду: миграция должна одинаково отработать и на
    пустой базе, и на той, где справочник уже заполнен человеком.
    """
    role = sa.table(
        "role",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("target_share_pct", sa.SmallInteger),
        sa.column("ord", sa.SmallInteger),
    )
    rows = [
        {
            "code": code,
            "title": title,
            "description": description,
            "target_share_pct": target,
            "ord": ord_,
        }
        for code, title, description, target, ord_ in SEED_ROLES
    ]
    op.execute(
        sa.dialects.postgresql.insert(role).values(rows).on_conflict_do_nothing(
            index_elements=["code"]
        )
    )


def downgrade() -> None:
    # Обратный порядок ссылок: акты и минуты держат роль, минуты держат правило.
    op.drop_index("ix_role_act_day_role", table_name="role_act")
    op.drop_index("ix_role_act_external", table_name="role_act")
    op.drop_index(op.f("ix_role_act_role_id"), table_name="role_act")
    op.drop_index(op.f("ix_role_act_work_day"), table_name="role_act")
    op.drop_index(op.f("ix_role_act_id"), table_name="role_act")
    op.drop_table("role_act")

    op.drop_index("ix_role_time_block_day_role", table_name="role_time_block")
    op.drop_index("ix_role_time_block_external", table_name="role_time_block")
    op.drop_index(op.f("ix_role_time_block_role_id"), table_name="role_time_block")
    op.drop_index(op.f("ix_role_time_block_work_day"), table_name="role_time_block")
    op.drop_index(op.f("ix_role_time_block_id"), table_name="role_time_block")
    op.drop_table("role_time_block")

    op.drop_index("ix_role_rule_source_priority", table_name="role_rule")
    op.drop_index(op.f("ix_role_rule_role_id"), table_name="role_rule")
    op.drop_index(op.f("ix_role_rule_id"), table_name="role_rule")
    op.drop_table("role_rule")

    op.drop_index(op.f("ix_role_code"), table_name="role")
    op.drop_index(op.f("ix_role_id"), table_name="role")
    op.drop_table("role")
