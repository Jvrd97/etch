# [review:need-review] PHASE-03/111, PHASE-03/117
# summary: database access for the chat — the conversation feed, the messages of one dialogue in `seq` order, the next position of a turn taken from the table rather than counted in python, and the append that records what a turn cost
# summary: PHASE-03/117 adds the delete that takes the four tables and the CLI session file with it, and the usage rollup that sums a conversation's tokens without reading one `content`
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

**Удаление разговора — одна транзакция и один запрос.** Строки `chat_messages`,
`chat_plans` и `chat_retrievals` уносит `ON DELETE CASCADE` из миграции `#111`,
а не три отдельных `DELETE` в питоне: три запроса можно оборвать посередине и
оставить разговор наполовину удалённым. Файл сессии CLI сносится **после**
коммита и никогда не мешает удалению строк — состояние диска не имеет права
оставить кнопку удаления враньём наполовину.

**Расход считает база, а не питон.** `usage_by_conversation` суммирует токены
и берёт медиану задержки одним запросом с `GROUP BY`, не выбирая `content`:
лента из пятидесяти разговоров иначе тянула бы через сеть весь их текст ради
трёх чисел в шапке.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.chat.session_files import (
    OUTCOME_ABSENT,
    OUTCOME_NO_SESSION,
    OUTCOME_REMOVED,
    remove_session_file,
)
from app.models.chat import (
    CONVERSATION_KIND_GENERAL,
    MESSAGE_STATUS_COMPLETE,
    ChatConversation,
    ChatMessage,
)

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class ConversationUsage:
    """
    Чем обошёлся разговор целиком.

    Медиана, а не среднее: один ход с длинным ответом сдвигает среднее так, что
    «сколько обычно ждать» по нему прочитать нельзя. `latency_ms_median` пуст,
    пока в разговоре нет ни одного хода с замеренной задержкой.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    message_count: int
    latency_ms_median: int | None


# Расход пустого разговора. Ноль, а не None: разговор без сообщений стоил
# ровно ничего, и шапке нечего скрывать.
EMPTY_USAGE = ConversationUsage(
    input_tokens=0,
    output_tokens=0,
    cache_read_tokens=0,
    message_count=0,
    latency_ms_median=None,
)

# Квантиль медианы. Именованная константа, потому что 0.5 внутри `percentile_cont`
# читается как магическое число ровно до того момента, когда кто-то захочет P95.
MEDIAN_QUANTILE = 0.5


async def usage_by_conversation(
    db: AsyncSession, conversation_ids: Iterable[int]
) -> dict[int, ConversationUsage]:
    """
    Свёртка расхода по нескольким разговорам одним запросом.

    В ответе только те разговоры, у которых есть хоть одно сообщение; пустые
    вызывающий берёт из `EMPTY_USAGE`. `content` в запрос не входит: шапке
    нужны три числа, а не текст разговора.
    """
    ids = list(conversation_ids)
    if not ids:
        return {}

    result = await db.execute(usage_statement(ids))
    return {
        row[0]: ConversationUsage(
            input_tokens=int(row[1]),
            output_tokens=int(row[2]),
            cache_read_tokens=int(row[3]),
            message_count=int(row[4]),
            latency_ms_median=None if row[5] is None else round(float(row[5])),
        )
        for row in result.all()
    }


def usage_statement(conversation_ids: Sequence[int]) -> Select[Any]:
    """
    Запрос свёртки — отдельно от выполнения, чтобы тест мог его прочитать.

    Утверждение «`content` в свёртку не входит» проверяется по этому запросу, а
    не по чтению кода: колонку легко дописать, а лента из пятидесяти разговоров
    после этого тянет весь их текст ради трёх чисел.
    """
    return (
        select(
            ChatMessage.conversation_id,
            func.coalesce(func.sum(ChatMessage.input_tokens), 0),
            func.coalesce(func.sum(ChatMessage.output_tokens), 0),
            func.coalesce(func.sum(ChatMessage.cache_read_tokens), 0),
            func.count(ChatMessage.id),
            # `within_group` приходит из SQLAlchemy без аннотаций — упорядоченные
            # агрегаты стабами не покрыты, и mypy зовёт вызов нетипизированным.
            # Замена — та же агрегация строкой `text()`, которая не проверяется
            # вообще ничем.
            func.percentile_cont(MEDIAN_QUANTILE).within_group(  # type: ignore[no-untyped-call]
                ChatMessage.latency_ms.asc()
            ),
        )
        .where(ChatMessage.conversation_id.in_(list(conversation_ids)))
        .group_by(ChatMessage.conversation_id)
    )


async def usage_of(db: AsyncSession, conversation_id: int) -> ConversationUsage:
    """Расход одного разговора; у разговора без сообщений — нули."""
    rollup = await usage_by_conversation(db, [conversation_id])
    return rollup.get(conversation_id, EMPTY_USAGE)


async def delete_conversation(db: AsyncSession, conversation: ChatConversation) -> str:
    """
    Снести разговор целиком и вернуть машинный код исхода по файлу сессии.

    Строки — одной транзакцией: каскад миграции `#111` уносит `chat_messages`,
    а за ними `chat_plans` и `chat_retrievals`. Файл сессии сносится после
    коммита, и любой его исход остаётся кодом в логе: разговора в базе уже нет,
    а осиротевший `.jsonl` — мусор, на который некому сослаться.
    """
    session_id = conversation.cli_session_id
    cwd = conversation.cli_cwd
    conversation_id = conversation.id

    await db.execute(
        delete(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    await db.commit()

    outcome = remove_session_file(
        config_dir=settings.CHAT_CLAUDE_CONFIG_DIR,
        cwd=cwd,
        session_id=session_id,
    )
    if outcome in (OUTCOME_REMOVED, OUTCOME_ABSENT, OUTCOME_NO_SESSION):
        logger.info(
            "chat session file after delete: %s (conversation %s)",
            outcome,
            conversation_id,
        )
    else:
        # `outside_config_dir` и `remove_failed` — то, ради чего исход вообще
        # возвращается наружу. Ни имени файла, ни `cli_session_id` в логе нет:
        # значение пришло из базы, и подделанное оно испортило бы строку лога.
        logger.warning(
            "chat session file after delete: %s (conversation %s)",
            outcome,
            conversation_id,
        )
    return outcome
