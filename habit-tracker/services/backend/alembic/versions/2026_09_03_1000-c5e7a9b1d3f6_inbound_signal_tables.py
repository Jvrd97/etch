"""signal_sources / signal_scopes / inbound_signals / commitments / signal_mirror_ops

Вход в систему появляется впервые: задачи дня рождаются снаружи — в ClickUp, в
почте, в переписке, — а внутри для них не было ни таблицы, ни HTTP-клиента.

Приватность контура выражена **отсутствием колонок** (ADR-0016, D2). Тела писем,
текстов сообщений и вложений здесь негде хранить физически: дамп Postgres лежит
файлом на диске VPS, и колонка под тело сделала бы из бэкапа копию всей личной
переписки. Хранится указатель наружу и хеш содержимого, а не содержимое.

Дедупликация — естественный ключ `(source_id, external_id)` плюс
`ON CONFLICT DO UPDATE`, тем же приёмом, что `uq_health_hour_bucket_natural_key`:
повторно увиденная задача обновляет снимок, а не плодит строку.

Сид: четыре заготовки источников, все выключенные. `clickup/alvion` заводится
именно заготовкой без адаптера — на ней проверяются экранное состояние «не
подключён» и отказ обратной записи у read-источника; без строки в справочнике
оба случая проверялись бы на несуществующем.

Токен в базу не попадает никогда: `credential_ref` — имя переменной окружения.

Обратимость полная: `downgrade()` роняет пять таблиц в обратном порядке FK.

Revision ID: c5e7a9b1d3f6
Revises: b4d6f8a0c2e5
Create Date: 2026-09-03 10:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e7a9b1d3f6"
down_revision: Union[str, None] = "b4d6f8a0c2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Дословный близнец `app.crud.inbox.SEED_SOURCES`: сид живёт дважды — в ревизии
# для рабочей базы и в модуле для тестовой, которую поднимает `create_all`.
# Расхождение ловится тестом, сравнивающим оба списка.
SEED_SOURCES: tuple[tuple[str, str, str, str | None], ...] = (
    ("clickup", "personal", "read_write", "CLICKUP_PERSONAL_TOKEN"),
    ("clickup", "alvion", "read", "CLICKUP_ALVION_TOKEN"),
    ("gmail", "personal", "read", "GMAIL_PERSONAL_CREDENTIALS"),
    ("telegram", "personal", "read", "TELEGRAM_SESSION_PATH"),
)


def upgrade() -> None:
    op.create_table(
        "signal_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("account", sa.String(length=50), nullable=False),
        sa.Column(
            "direction", sa.String(length=16), server_default="read", nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("credential_ref", sa.String(length=100), nullable=True),
        sa.Column("cursor", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "account", name="uq_signal_source_account"),
    )
    op.create_index(
        op.f("ix_signal_sources_id"), "signal_sources", ["id"], unique=False
    )

    op.create_table(
        "signal_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["signal_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "scope_key", name="uq_signal_scope_key"),
    )
    op.create_index(op.f("ix_signal_scopes_id"), "signal_scopes", ["id"], unique=False)
    # Индекс на FK ставится явно: Postgres его сам не создаёт, а каскадное
    # удаление источника без него сканирует таблицу целиком.
    op.create_index(
        op.f("ix_signal_scopes_source_id"), "signal_scopes", ["source_id"], unique=False
    )

    op.create_table(
        "inbound_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("external_url", sa.String(length=500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("counterpart_key", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["source_id"], ["signal_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scope_id"], ["signal_scopes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "external_id", name="uq_inbound_signal_natural_key"
        ),
    )
    op.create_index(
        op.f("ix_inbound_signals_id"), "inbound_signals", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_inbound_signals_source_id"),
        "inbound_signals",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inbound_signals_scope_id"),
        "inbound_signals",
        ["scope_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inbound_signals_local_date"),
        "inbound_signals",
        ["local_date"],
        unique=False,
    )
    # Экран «Входящие» читает именно так: неразобранные, свежие сверху.
    op.create_index(
        "ix_inbound_signal_state_occurred",
        "inbound_signals",
        ["state", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "commitments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="proposed", nullable=False
        ),
        sa.Column("due_local_date", sa.Date(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["signal_id"], ["inbound_signals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commitments_id"), "commitments", ["id"], unique=False)
    op.create_index(
        op.f("ix_commitments_signal_id"), "commitments", ["signal_id"], unique=False
    )
    op.create_index(
        op.f("ix_commitments_due_local_date"),
        "commitments",
        ["due_local_date"],
        unique=False,
    )
    op.create_index(
        "ix_commitment_status_due",
        "commitments",
        ["status", "due_local_date"],
        unique=False,
    )

    op.create_table(
        "signal_mirror_ops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("op", sa.String(length=20), server_default="complete", nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["signal_id"], ["inbound_signals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_signal_mirror_idempotency"),
    )
    op.create_index(
        op.f("ix_signal_mirror_ops_id"), "signal_mirror_ops", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_signal_mirror_ops_signal_id"),
        "signal_mirror_ops",
        ["signal_id"],
        unique=False,
    )

    sources = sa.table(
        "signal_sources",
        sa.column("provider", sa.String),
        sa.column("account", sa.String),
        sa.column("direction", sa.String),
        sa.column("credential_ref", sa.String),
    )
    op.bulk_insert(
        sources,
        [
            {
                "provider": provider,
                "account": account,
                "direction": direction,
                "credential_ref": credential_ref,
            }
            for provider, account, direction, credential_ref in SEED_SOURCES
        ],
    )


def downgrade() -> None:
    op.drop_table("signal_mirror_ops")
    op.drop_table("commitments")
    op.drop_table("inbound_signals")
    op.drop_table("signal_scopes")
    op.drop_table("signal_sources")
