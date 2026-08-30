"""chat conversation tables — the whole theme in one revision

Четыре таблицы темы заводятся сразу, а не по одной на тикет: цепочка Alembic
остаётся линейной, а тикеты, которые пишут планы и выборки, пишут код, а не
миграции. Обратимость достижима без оговорок — таблицы новые, ни одна
существующая не меняется, переносить нечего.

Revision ID: e6b8d0f2a4c7
Revises: e7c9a1b3d5f0
Create Date: 2026-09-01 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6b8d0f2a4c7"
down_revision: Union[str, None] = "e7c9a1b3d5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column(
            "kind", sa.String(length=20), server_default="general", nullable=False
        ),
        # Чем отвечали. NULL до первого ответа: разговор существует раньше, чем
        # становится известно, какой бэкенд оказался доступен.
        sa.Column("llm_backend", sa.String(length=20), nullable=True),
        # Подсказка для `--resume`, а не память диалога. Память — chat_messages.
        sa.Column("cli_session_id", sa.String(length=36), nullable=True),
        sa.Column("cli_cwd", sa.String(length=500), nullable=True),
        sa.Column(
            "context_version", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archived", sa.Boolean(), server_default="false", nullable=False
        ),
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
    )
    op.create_index("ix_chat_conversations_id", "chat_conversations", ["id"])
    op.create_index(
        "ix_chat_conversations_started_on", "chat_conversations", ["started_on"]
    )
    op.create_index(
        "ix_chat_conversations_last_message_at",
        "chat_conversations",
        ["last_message_at"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        # Порядок хода. Не created_at: два сообщения одной секунды иначе
        # переставляются местами при реплее диалога в промпт.
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        # Тело сообщения. В логи не попадает никогда — ни целиком, ни куском.
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="complete", nullable=False
        ),
        # Машинный код отказа. Текст модели сюда не пишется: диагностика не
        # должна становиться вторым местом хранения содержимого разговора.
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
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
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_chat_message_seq"),
    )
    op.create_index("ix_chat_messages_id", "chat_messages", ["id"])
    op.create_index(
        "ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"]
    )

    op.create_table(
        "chat_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        # sa.JSON, а не PG-специфичный тип: та же форма, что у
        # applied_daily_summaries, и тестовая база строится create_all.
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="proposed", nullable=False
        ),
        # Без внешнего ключа намеренно: удаление квитанции не должно стирать
        # факт применения плана.
        sa.Column("applied_summary_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
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
            ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_plans_id", "chat_plans", ["id"])
    op.create_index("ix_chat_plans_message_id", "chat_plans", ["message_id"], unique=True)
    op.create_index("ix_chat_plans_entry_date", "chat_plans", ["entry_date"])

    op.create_table(
        "chat_retrievals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("query_name", sa.String(length=50), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        # Размер, а не содержимое: журнал отвечает на вопрос «какие данные и
        # когда покинули сервер», не храня их второй раз.
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_retrievals_id", "chat_retrievals", ["id"])
    op.create_index(
        "ix_chat_retrievals_message_id", "chat_retrievals", ["message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_retrievals_message_id", "chat_retrievals")
    op.drop_index("ix_chat_retrievals_id", "chat_retrievals")
    op.drop_table("chat_retrievals")

    op.drop_index("ix_chat_plans_entry_date", "chat_plans")
    op.drop_index("ix_chat_plans_message_id", "chat_plans")
    op.drop_index("ix_chat_plans_id", "chat_plans")
    op.drop_table("chat_plans")

    op.drop_index("ix_chat_messages_conversation_id", "chat_messages")
    op.drop_index("ix_chat_messages_id", "chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_conversations_last_message_at", "chat_conversations")
    op.drop_index("ix_chat_conversations_started_on", "chat_conversations")
    op.drop_index("ix_chat_conversations_id", "chat_conversations")
    op.drop_table("chat_conversations")
