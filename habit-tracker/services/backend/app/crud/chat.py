# [review:need-review] PHASE-03/111, PHASE-03/115
# summary: database access for the chat — the conversation feed, the messages of one dialogue in `seq` order, the next position of a turn taken from the table rather than counted in python, the append that records what a turn cost, and the plans persisted beside the message they were proposed in
"""
Доступ к таблицам разговора.

**Позицию хода выдаёт таблица, а не счётчик в памяти.** `next_seq` спрашивает
`MAX(seq) + 1` внутри той же транзакции, в которой сообщение и записывается, а
`uq_chat_message_seq` ловит гонку, если два хода всё же пришли одновременно.
Счётчик, посчитанный в питоне до записи, был бы вторым источником истины про
порядок диалога.

**Заголовок ставит сервер по первой реплике человека.** Просить его у модели —
это лишний ход, который к тому же не состоится ровно тогда, когда ход не удался,
и лента останется без имени именно у сломанных разговоров.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applied_daily_summary import AppliedDailySummary
from app.schemas.chat import ChatPlan as SchemaChatPlan
from app.schemas.chat import ChatPlanApply
from app.schemas.daily_summary import DailySummaryApplyRequest
from app.models.chat import (
    CONVERSATION_KIND_GENERAL,
    MESSAGE_STATUS_COMPLETE,
    PLAN_STATUS_PROPOSED,
    PLAN_STATUS_STALE,
    ChatConversation,
    ChatMessage,
    ChatPlan,
)

# Длина колонки `title`. Заголовок режется по ней здесь, а не полагается на
# отказ базы: обрезанная лента лучше, чем ход, упавший на длинном первом вопросе.
TITLE_MAX_CHARS = 200

# Сколько разговоров отдаётся ленте по умолчанию.
DEFAULT_FEED_LIMIT = 50

# Первый ход диалога.
FIRST_SEQ = 1


def title_from(text: str) -> str:
    """
    Заголовок ленты по первой реплике: первая строка, обрезанная по колонке.

    Многострочный вопрос в заголовке ленты нечитаем, поэтому берётся первая
    непустая строка, а не первые двести символов всего сообщения.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:TITLE_MAX_CHARS]
    return text.strip()[:TITLE_MAX_CHARS]


async def create_conversation(
    db: AsyncSession,
    *,
    started_on: date,
    kind: str = CONVERSATION_KIND_GENERAL,
    title: str | None = None,
) -> ChatConversation:
    """Завести разговор. Сообщений у него пока нет, и это нормальное состояние."""
    conversation = ChatConversation(
        started_on=started_on,
        kind=kind,
        title=title,
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_conversation(
    db: AsyncSession, conversation_id: int
) -> ChatConversation | None:
    """Один разговор по id, либо None."""
    result = await db.execute(
        select(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_FEED_LIMIT,
    archived: bool = False,
) -> Sequence[ChatConversation]:
    """
    Лента разговоров, свежие сверху.

    Сортировка по `last_message_at`, а `id` — тай-брейк: у только что заведённого
    разговора отметки времени ещё нет, и без второго ключа порядок пустых
    разговоров зависел бы от плана запроса.
    """
    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.archived == archived)
        .order_by(
            ChatConversation.last_message_at.desc().nullslast(),
            ChatConversation.id.desc(),
        )
        .limit(limit)
    )
    return result.scalars().all()


async def list_messages(
    db: AsyncSession, conversation_id: int
) -> Sequence[ChatMessage]:
    """Сообщения разговора в порядке `seq` — том самом, в каком его и реплеить."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.seq)
    )
    return result.scalars().all()


async def next_seq(db: AsyncSession, conversation_id: int) -> int:
    """Позиция следующего хода: `MAX(seq) + 1`, у пустого разговора — первая."""
    result = await db.execute(
        select(func.max(ChatMessage.seq)).where(
            ChatMessage.conversation_id == conversation_id
        )
    )
    highest = result.scalar_one_or_none()
    return FIRST_SEQ if highest is None else highest + 1


async def add_message(
    db: AsyncSession,
    *,
    conversation_id: int,
    seq: int,
    role: str,
    content: str,
    status: str = MESSAGE_STATUS_COMPLETE,
    error_code: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    latency_ms: int | None = None,
    model: str | None = None,
) -> ChatMessage:
    """Дописать сообщение в разговор вместе с тем, чем этот ход обошёлся."""
    message = ChatMessage(
        conversation_id=conversation_id,
        seq=seq,
        role=role,
        content=content,
        status=status,
        error_code=error_code,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        latency_ms=latency_ms,
        model=model,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def touch_conversation(
    db: AsyncSession,
    conversation: ChatConversation,
    *,
    at: datetime,
    title: str | None = None,
    llm_backend: str | None = None,
    cli_session_id: str | None = None,
    cli_cwd: str | None = None,
) -> ChatConversation:
    """
    Отметить разговор ходом: время последнего сообщения и подсказки о сессии.

    Заголовок ставится один раз — первой репликой человека. Переписывать его на
    каждом ходу значило бы менять имя разговора в ленте по ходу разговора.
    """
    conversation.last_message_at = at
    if title is not None and conversation.title is None:
        conversation.title = title
    if llm_backend is not None:
        conversation.llm_backend = llm_backend
    if cli_session_id is not None:
        conversation.cli_session_id = cli_session_id
    if cli_cwd is not None:
        conversation.cli_cwd = cli_cwd
    await db.flush()
    return conversation


async def save_plan(
    db: AsyncSession, *, message_id: int, entry_date: date, plan: dict[str, Any]
) -> ChatPlan:
    """
    Записать предложение рядом с сообщением, в котором оно прозвучало.

    План персистится, а не живёт в ответе одного запроса, по двум причинам. В
    многоходовом разговоре реплика «вернись к тому, что ты предлагал два хода
    назад» — обычная, и возвращаться должно быть к чему. И без записи нельзя
    доказать, что применено ровно то, что было показано: применение сверяется с
    этой строкой.
    """
    row = ChatPlan(message_id=message_id, entry_date=entry_date, plan=plan)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_plan(db: AsyncSession, plan_id: int) -> ChatPlan | None:
    """Один план по идентификатору."""
    result = await db.execute(select(ChatPlan).where(ChatPlan.id == plan_id))
    return result.scalar_one_or_none()


async def plans_for_messages(
    db: AsyncSession, message_ids: Sequence[int]
) -> dict[int, ChatPlan]:
    """
    Планы лентой: по одному запросу на весь экран, а не на сообщение.

    Ключ — `message_id`, потому что уникальность в таблице стоит на нём: одно
    сообщение несёт максимум одно предложение.
    """
    if not message_ids:
        return {}
    result = await db.execute(
        select(ChatPlan).where(ChatPlan.message_id.in_(message_ids))
    )
    return {row.message_id: row for row in result.scalars().all()}


async def mark_stale_for_date(
    db: AsyncSession, entry_date: date, *, except_plan_id: int
) -> int:
    """
    Погасить остальные предложения на ту же дату.

    План на дату, по которой уже применён другой план чата, помечается `stale`,
    и плашка становится неактивной. Иначе два предложения на один день
    оставались бы одинаково живыми, и второе применение дописало бы день второй
    раз — с кнопкой, которая обещала «применить показанное».
    """
    result = await db.execute(
        update(ChatPlan)
        .where(
            ChatPlan.entry_date == entry_date,
            ChatPlan.id != except_plan_id,
            ChatPlan.status == PLAN_STATUS_PROPOSED,
        )
        .values(status=PLAN_STATUS_STALE)
    )
    return int(result.rowcount or 0)


class PlanSelectionRejected(Exception):
    """Человек прислал операцию, которой в показанном плане не было."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


NOT_IN_PLAN = (
    "операция {kind} по категории {category_id} и полю {field_id} не входит в "
    "показанный план: применить можно только то, что было показано"
)
JOURNAL_NOT_IN_PLAN = (
    "текст дня не совпадает с показанным в плане: применить можно только то, "
    "что было показано"
)


def narrow_to_plan(
    stored: SchemaChatPlan, chosen: ChatPlanApply
) -> DailySummaryApplyRequest:
    """
    Свести выбор человека к сохранённому плану — или отказать.

    Плашка присылает подмножество показанного: снятая галочка не должна
    записаться, а дописанная в обход экрана — тем более. Проверяется это
    сверкой с `chat_plans.plan`, а не доверием к телу запроса; иначе плашка
    была бы просто ещё одним путём записи в базу, а строка плана ничего бы не
    доказывала.

    Дата берётся из плана, а не из тела: она — часть того, что человек видел,
    когда нажимал.
    """
    allowed_metrics = {(op.category_id, op.field_id, op.value) for op in stored.metrics}
    for op in chosen.metrics:
        if (op.category_id, op.field_id, op.value) not in allowed_metrics:
            raise PlanSelectionRejected(
                NOT_IN_PLAN.format(
                    kind="log_metric",
                    category_id=op.category_id,
                    field_id=op.field_id,
                )
            )

    allowed_checks = {(op.category_id, op.field_id) for op in stored.checklist}
    for check in chosen.checklist:
        if (check.category_id, check.field_id) not in allowed_checks:
            raise PlanSelectionRejected(
                NOT_IN_PLAN.format(
                    kind="check",
                    category_id=check.category_id,
                    field_id=check.field_id,
                )
            )

    if chosen.journal is not None:
        if stored.journal is None or stored.journal.content != chosen.journal.content:
            raise PlanSelectionRejected(JOURNAL_NOT_IN_PLAN)

    return DailySummaryApplyRequest(
        entry_date=stored.entry_date,
        metrics=chosen.metrics,
        checklist=chosen.checklist,
        journal=chosen.journal,
    )


async def receipt_id_for(db: AsyncSession, idempotency_key: str) -> int | None:
    """
    Идентификатор квитанции применения по её ключу.

    Читается здесь, а не возвращается из `apply_daily_summary`: тот путь общий с
    экраном разбора дня, и добавлять в его ответ поле ради одного потребителя
    значило бы менять контракт, которым пользуется не этот тикет.

    Ссылка на квитанцию хранится в `chat_plans` без внешнего ключа — намеренно:
    удаление квитанции не должно стирать факт, что план применяли.
    """
    result = await db.execute(
        select(AppliedDailySummary.id).where(
            AppliedDailySummary.idempotency_key == idempotency_key
        )
    )
    return result.scalar_one_or_none()
