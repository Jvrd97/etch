"""day_rule_profile / day_rule_activation / overtime_debt — потолок работы дышит

Потолок константой в строке правила не описывает живую работу: в неделю сдачи
релиза десять часов норма, в спокойную — уже перебор. Три таблицы делают потолок
функцией ситуации, не теряя того, ради чего правило заведено.

Опасность названа прямо: потолок, который сам растёт под дедлайн, отменяет
правило. Поэтому подъём не бесплатен — он создаёт долг в `overtime_debt`, и
считается долг от **базового** потолка, а не от поднятого. Иначе долг всегда ноль
и весь механизм — украшение.

Активация обязана иметь `valid_to`: поднятый потолок, который некому выключить,
и есть тот способ, которым такие послабления перестают быть послаблениями.
Активация без `confirmed_at` не действует ни на один день — решение человека
2026-08-30: система предлагает, человек подтверждает.

Сиды: три профиля. `baseline` (480/540 по `config.md`) — по умолчанию, `deadline`
(720/720) — двенадцать часов под сдачу, `recovery` (360/420) — неделя после.

Обратимость полная: `downgrade()` роняет три таблицы в обратном порядке.

Revision ID: b4d6f8a0c2e5
Revises: a3c5e7b9d1f4
Create Date: 2026-09-02 16:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d6f8a0c2e5"
down_revision: Union[str, None] = "a3c5e7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Дословный близнец `app.crud.day_profile.SEED_PROFILES`: сид живёт дважды —
# в ревизии для рабочей базы и в модуле для тестовой, которую `create_all`
# собирает мимо Alembic. Тот же приём, что у `seed_roles`.
SEED_PROFILES: tuple[tuple[str, str, int, int, bool], ...] = (
    ("baseline", "Обычная неделя", 480, 540, True),
    ("deadline", "Неделя сдачи", 720, 720, False),
    ("recovery", "Неделя после сдачи", 360, 420, False),
)


def upgrade() -> None:
    op.create_table(
        "day_rule_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("work_cap_min", sa.Integer(), nullable=False),
        sa.Column("work_hard_cap_min", sa.Integer(), nullable=False),
        sa.Column(
            "required_anchors",
            sa.dialects.postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "code IN ('baseline', 'deadline', 'recovery')",
            name="ck_day_rule_profile_code",
        ),
        sa.CheckConstraint(
            "work_cap_min > 0 AND work_hard_cap_min >= work_cap_min",
            name="ck_day_rule_profile_caps",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_day_rule_profile_id", "day_rule_profile", ["id"])
    op.create_index(
        "ix_day_rule_profile_code", "day_rule_profile", ["code"], unique=True
    )
    op.create_index(
        "uq_day_rule_profile_default",
        "day_rule_profile",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "day_rule_activation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(length=10), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_signal_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "valid_to >= valid_from", name="ck_day_rule_activation_range"
        ),
        sa.CheckConstraint(
            "confirmed_by IN ('human') OR confirmed_by IS NULL",
            name="ck_day_rule_activation_confirmed_by",
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR confirmed_by IS NOT NULL",
            name="ck_day_rule_activation_confirmed_pair",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["day_rule_profile.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_day_rule_activation_id", "day_rule_activation", ["id"])
    op.create_index(
        "ix_day_rule_activation_profile_id", "day_rule_activation", ["profile_id"]
    )
    op.create_index(
        "ix_day_rule_activation_range",
        "day_rule_activation",
        ["valid_from", "valid_to"],
    )

    op.create_table(
        "overtime_debt",
        sa.Column("incurred_on", sa.Date(), nullable=False),
        sa.Column("minutes_over", sa.Integer(), nullable=False),
        sa.Column("repaid_on", sa.Date(), nullable=True),
        sa.Column("repaid_by_day", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("minutes_over > 0", name="ck_overtime_debt_positive"),
        sa.CheckConstraint(
            "(repaid_on IS NULL) = (repaid_by_day IS NULL)",
            name="ck_overtime_debt_repaid_pair",
        ),
        sa.ForeignKeyConstraint(
            ["repaid_by_day"],
            ["day.date"],
            name="fk_overtime_debt_repaid_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("incurred_on"),
    )
    op.create_index(
        "ix_overtime_debt_open",
        "overtime_debt",
        ["incurred_on"],
        postgresql_where=sa.text("repaid_on IS NULL"),
    )

    profiles = sa.table(
        "day_rule_profile",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("work_cap_min", sa.Integer),
        sa.column("work_hard_cap_min", sa.Integer),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(
        profiles,
        [
            {
                "code": code,
                "title": title,
                "work_cap_min": cap,
                "work_hard_cap_min": hard_cap,
                "is_default": is_default,
            }
            for code, title, cap, hard_cap, is_default in SEED_PROFILES
        ],
    )


def downgrade() -> None:
    op.drop_table("overtime_debt")
    op.drop_table("day_rule_activation")
    op.drop_table("day_rule_profile")
