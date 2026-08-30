# [review:need-review] PHASE-03/111
# summary: database access for the chat — the conversation feed, the messages of one dialogue in `seq` order, the next position of a turn taken from the table rather than counted in python, and the append that records what a turn cost
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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    CONVERSATION_KIND_GENERAL,
    MESSAGE_STATUS_COMPLETE,
    ChatConversation,
    ChatMessage,
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
