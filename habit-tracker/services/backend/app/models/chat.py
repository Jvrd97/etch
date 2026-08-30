# [review:need-review] PHASE-03/111
# summary: the four chat tables of ADR-0017 — `chat_conversations` with the CLI-session hint that is only ever a hint, `chat_messages` whose `seq` (not `created_at`) is the order a dialogue replays in, `chat_plans` and `chat_retrievals`; the vocabularies are flat strings, so a new kind costs code and not a migration
"""
Таблицы диалога с Claude.

**История в Postgres — источник истины, CLI-сессия — подсказка.**
`chat_messages` хранит весь разговор, поэтому чат переживает перезапуск
контейнера, потерю jsonl-файла сессии и переключение `LLM_BACKEND` на API.
`chat_conversations.cli_session_id` вместе с `cli_cwd` и `context_version` —
только оптимизация: `--resume` ключуется рабочим каталогом и ломается, если
системный промпт сменился. Поля заводятся здесь, включает их `#112`.

**Порядок хода несёт `seq`, а не `created_at`.** Два сообщения одной секунды
переставляются местами при реплее, и разговор при этом читается задом наперёд.
`uq_chat_message_seq` делает дубль позиции ошибкой базы, а не гонкой, которую
заметят через месяц.

**Словари — плоские строки без PG-enum и без CHECK.** `role`, `status`, `kind` и
`query_name` живут по образцу `display_mode`/`streak_mode`: пятое значение
стоит правки кода, а не миграции. Ограничение осознанное — цену платит тот, кто
опечатается в имени статуса.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# Зачем начат разговор. `day_open` и `day_close` — те самые части `/day-open` и
# `/day-close`, ради которых чат и строится; `general` — всё остальное.
CONVERSATION_KIND_GENERAL = "general"
CONVERSATION_KIND_DAY_OPEN = "day_open"
CONVERSATION_KIND_DAY_CLOSE = "day_close"
CONVERSATION_KINDS: tuple[str, ...] = (
    CONVERSATION_KIND_GENERAL,
    CONVERSATION_KIND_DAY_OPEN,
    CONVERSATION_KIND_DAY_CLOSE,
)

MESSAGE_ROLE_USER = "user"
MESSAGE_ROLE_ASSISTANT = "assistant"
# Реплика сервера, а не модели: «сессия оборвалась», «выборка отклонена».
MESSAGE_ROLE_SYSTEM_NOTE = "system_note"
MESSAGE_ROLES: tuple[str, ...] = (
    MESSAGE_ROLE_USER,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_SYSTEM_NOTE,
)

# `streaming` — ход идёт прямо сейчас; `interrupted` — соединение оборвалось, и
# в `content` лежит то, что успело прийти. Разница между ними и `failed` в том,
# есть ли у сообщения текст: у оборванного он есть, у упавшего нет.
MESSAGE_STATUS_STREAMING = "streaming"
MESSAGE_STATUS_COMPLETE = "complete"
MESSAGE_STATUS_INTERRUPTED = "interrupted"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUSES: tuple[str, ...] = (
    MESSAGE_STATUS_STREAMING,
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_INTERRUPTED,
    MESSAGE_STATUS_FAILED,
)

PLAN_STATUS_PROPOSED = "proposed"
PLAN_STATUS_APPLIED = "applied"
PLAN_STATUS_DISMISSED = "dismissed"
PLAN_STATUS_STALE = "stale"
PLAN_STATUSES: tuple[str, ...] = (
    PLAN_STATUS_PROPOSED,
    PLAN_STATUS_APPLIED,
    PLAN_STATUS_DISMISSED,
    PLAN_STATUS_STALE,
)

# Первая версия системного промпта живёт здесь, потому что её пишет строка
# таблицы, а меняет `app.llm.chat.prompt`. Смена версии обнуляет `cli_session_id`
# — возобновлять сессию, собранную под другой системный промпт, нельзя.
DEFAULT_CONTEXT_VERSION = 1


class ChatConversation(Base):
    """
    Один разговор: лента сообщений плюс подсказки о том, чем на него отвечали.

    `title` ставит сервер по первому сообщению человека, не модель: заголовок,
    придуманный моделью, стоил бы лишнего хода и врал бы ровно там, где ход не
    удался.

    `llm_backend`, `cli_session_id` и `cli_cwd` описывают не разговор, а способ
    его продолжить. Ни одно из трёх не обязано быть заполнено, и разговор
    работает, когда все три пусты, — это и есть свойство «история в таблице
    первична».
    """

    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # День, к которому привязан разговор. Считается `app.core.daytime`, а не
    # календарём браузера: разговор в 00:30 относится к вчерашнему дню.
    started_on: Mapped[date_type] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(
        String(20), server_default=CONVERSATION_KIND_GENERAL
    )

    llm_backend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cli_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cli_cwd: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context_version: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_CONTEXT_VERSION)
    )

    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ChatConversation(id={self.id}, started_on={self.started_on})>"


class ChatMessage(Base):
    """
    Одно сообщение диалога.

    `content` не пишется в логи никогда — ни целиком, ни куском, ни в тексте
    исключения. Машинная причина отказа живёт в `error_code`, и это отдельная
    колонка именно затем, чтобы текст модели не подмешивался в диагностику.

    Счётчики токенов лежат рядом с сообщением, а не в отдельной таблице расхода:
    вопрос «сколько стоил этот ход» задаётся про ход.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_chat_message_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)

    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), server_default=MESSAGE_STATUS_COMPLETE
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<ChatMessage(id={self.id}, conversation_id={self.conversation_id}, "
            f"seq={self.seq}, role={self.role!r})>"
        )


class ChatPlan(Base):
    """
    Предложение модели, рядом с сообщением, в котором оно прозвучало.

    Уникальность по `message_id` — одно сообщение, максимум один план: две
    записи означали бы, что «применить» относится непонятно к чему.

    `applied_summary_id` намеренно без внешнего ключа: удаление квитанции
    `applied_daily_summaries` не должно стирать факт, что план применяли. Та же
    причина, что у `journal_entry_id`.
    """

    __tablename__ = "chat_plans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), unique=True, index=True
    )
    entry_date: Mapped[date_type] = mapped_column(Date, index=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), server_default=PLAN_STATUS_PROPOSED)
    applied_summary_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ChatPlan(id={self.id}, message_id={self.message_id}, status={self.status!r})>"


class ChatRetrieval(Base):
    """
    След одной именованной выборки: что модель попросила и сколько получила.

    Без этой строки утверждение «данные выходят одной точкой и это легко
    аудитить» перестаёт быть правдой для чата: контекст динамический, и без
    журнала нельзя ответить, какие данные и когда покинули сервер. Сами данные
    здесь не хранятся — только имя, параметры и размер.
    """

    __tablename__ = "chat_retrievals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    query_name: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    row_count: Mapped[int] = mapped_column(Integer)
    chars: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ChatRetrieval(id={self.id}, query_name={self.query_name!r})>"
