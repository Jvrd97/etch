# [review:need-review] PHASE-03/111, PHASE-03/117, PHASE-03/113
# summary: the chat router — conversations created, listed and read back with their messages, and one turn answered as text/event-stream whose answer is written by a session opened after generation, never by the one that read the context
# summary: PHASE-03/117 adds DELETE /conversations/{id} (204, cascade plus the CLI session file) and hangs the usage rollup on both the feed and the detail
# summary: PHASE-03/113 builds the day card in the same session that records the question, sends it in the system prompt, and shows it back through GET /conversations/{id}/context
"""
Ручки разговора.

**Сессия БД не живёт столько, сколько живёт генерация.** Контекст читается,
сессия отпускается, ответ пишется новой. Иначе соединение из пула занято все сто
двадцать секунд хода, и на двух воркерах разговор выедает пул целиком. Поэтому
ход берёт `get_session_factory`, а не `get_db`.

**503 проверяется до записи.** Отсутствие бэкенда — не сбой хода, а выключенная
функция, и реплика человека при ней не должна оседать в `chat_messages`: иначе
разговор пополняется вопросами, на которые никто никогда не отвечал.

**Ответ записывается и тогда, когда его дослушать не успели.** Запись идёт из
`finally` генератора, так что закрытая вкладка оставляет сообщение со статусом
`interrupted` и уже полученным текстом, а не пустоту.

**Карточка дня строится той же сессией, что записывает вопрос.** Второй заход
в базу ради контекста означал бы, что вопрос и карточка читают день в разные
моменты, и ответ мог бы противоречить тому, что человек только что отметил.

**`/context` строит карточку той же функцией, а не хранит её копию.** Карточка —
это функция дня, и второй её экземпляр рядом с сообщением устаревал бы молча.

**Ни одна строка содержимого не попадает в лог.** Наружу и в базу уходит
машинный `error_code`; текст модели живёт ровно в `chat_messages.content`.

**Удаление отвечает 204 и тогда, когда файла сессии на диске нет.** Исход по
файлу — машинный код в логе, а не статус ответа: разговор либо удалён целиком,
либо не удалён вовсе, и третьего состояния у кнопки нет.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionFactory, get_chat_llm_client, get_session_factory
from app.core.database import get_db
from app.core.daytime import now_utc, today_local
from app.crud import chat as chat_crud
from app.llm.chat.client import CHUNK_DELTA, ChatChunk, ChatLLMClient
from app.llm.chat.context import build_day_card
from app.llm.chat.prompt import (
    CHAT_CONTEXT_VERSION,
    ChatTurn,
    compose_system_prompt,
)
from app.llm.client import LLMError
from app.models.chat import (
    CONVERSATION_KINDS,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INTERRUPTED,
    ChatConversation,
)
from app.schemas.chat import (
    FEED_MAX_LIMIT,
    SSE_EVENT_DELTA,
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_USAGE,
    ConversationContext,
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    ConversationUsage,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_MEDIA_TYPE = "text/event-stream"

# Заголовки потока. `X-Accel-Buffering: no` — не суеверие: прокси, копящий
# ответ в буфере, превращает поток кусков в один ответ в конце, то есть ровно
# в то, ради отказа от чего SSE и берётся.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Машинный код отказа, когда бэкенд не смог ответить. Расшифровку человек
# читает на экране, в базе лежит код.
ERROR_CODE_BACKEND = "backend_failed"

MILLISECONDS_PER_SECOND = 1000


def _sse(event: str, data: dict[str, object]) -> str:
    """
    Одно событие SSE. Данные — JSON в одну строку.

    Перевод строки внутри текста ответа экранируется JSON'ом, поэтому событие
    остаётся однострочным. Сырой текст в `data:` разорвал бы кадр на первом же
    абзаце ответа.
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _feed_item(
    conversation: ChatConversation, usage: chat_crud.ConversationUsage
) -> ConversationResponse:
    """Строка ленты — DTO, а не доменная модель наружу."""
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        started_on=conversation.started_on,
        kind=conversation.kind,
        llm_backend=conversation.llm_backend,
        context_version=conversation.context_version,
        last_message_at=conversation.last_message_at,
        archived=conversation.archived,
        created_at=conversation.created_at,
        usage=ConversationUsage.model_validate(usage),
    )


def _detail(
    conversation: ChatConversation,
    messages: list[MessageResponse],
    usage: chat_crud.ConversationUsage,
) -> ConversationDetail:
    """Разговор с сообщениями и расходом — DTO, а не доменная модель наружу."""
    return ConversationDetail(
        **_feed_item(conversation, usage).model_dump(),
        messages=messages,
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate | None = None,
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """
    Завести разговор.

    - **started_on**: день разговора; по умолчанию сегодняшний по границе суток
      приложения (`app/core/daytime.py`), а не по календарю браузера
    - **kind**: `general` | `day_open` | `day_close`
    """
    request = payload if payload is not None else ConversationCreate()
    if request.kind not in CONVERSATION_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of {', '.join(CONVERSATION_KINDS)}",
        )
    conversation = await chat_crud.create_conversation(
        db,
        started_on=request.started_on or today_local(),
        kind=request.kind,
        title=request.title,
    )
    # Расход нового разговора — нули, и спрашивать их у базы нечего.
    return _feed_item(conversation, chat_crud.EMPTY_USAGE)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    limit: int = Query(default=chat_crud.DEFAULT_FEED_LIMIT, ge=1, le=FEED_MAX_LIMIT),
    archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    """
    Лента разговоров, свежие сверху, каждый со своим расходом.

    Расход собирается одним запросом на всю ленту, а не запросом на строку:
    пятьдесят разговоров — это пятьдесят обращений к базе ради трёх чисел.
    """
    conversations = await chat_crud.list_conversations(
        db, limit=limit, archived=archived
    )
    rollup = await chat_crud.usage_by_conversation(
        db, [one.id for one in conversations]
    )
    return [
        _feed_item(one, rollup.get(one.id, chat_crud.EMPTY_USAGE))
        for one in conversations
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int, db: AsyncSession = Depends(get_db)
) -> ConversationDetail:
    """Разговор целиком: сообщения в порядке `seq`, а не по времени записи."""
    conversation = await chat_crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id} not found",
        )
    messages = await chat_crud.list_messages(db, conversation_id)
    usage = await chat_crud.usage_of(db, conversation_id)
    return _detail(
        conversation,
        [MessageResponse.model_validate(one) for one in messages],
        usage,
    )


@router.get(
    "/conversations/{conversation_id}/context", response_model=ConversationContext
)
async def get_conversation_context(
    conversation_id: int, db: AsyncSession = Depends(get_db)
) -> ConversationContext:
    """
    Что чат видит: карточка дня тем же текстом, каким она уходит в промпт.

    Карточка собирается той же `build_day_card` по тому же дню разговора, а не
    достаётся из копии рядом с сообщением: копия устаревала бы молча, и
    раскрывашка показывала бы вчерашнюю правду сегодняшним ходом.
    """
    conversation = await chat_crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id} not found",
        )
    card = await build_day_card(db, conversation.started_on)
    return ConversationContext(
        conversation_id=conversation_id,
        entry_date=card.entry_date,
        text=card.text,
        chars=card.chars,
        max_chars=card.max_chars,
        truncated=card.truncated,
        dropped_sections=list(card.dropped_sections),
    )


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(
    conversation_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    """
    Удалить разговор целиком: строки четырёх таблиц и файл сессии CLI.

    Отвечает 204, и 404 — только на разговор, которого нет. Отсутствие файла
    сессии на диске отказом не считается: у разговора по API-бэкенду его не
    было никогда, у разговора после пересоздания тома — уже нет.

    Записи, сделанные применением плана (квитанция дня, запись в журнале),
    остаются: у `chat_plans.applied_summary_id` внешнего ключа нет намеренно —
    удаление разговора стирает разговор, а не сделанную по нему работу.
    """
    conversation = await chat_crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id} not found",
        )
    await chat_crud.delete_conversation(db, conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@dataclass(frozen=True)
class _TurnContext:
    """Всё, что ход берёт из базы до того, как соединение вернётся в пул."""

    turns: list[ChatTurn]
    answer_seq: int
    system_prompt: str


async def _record_question(
    factory: SessionFactory, conversation_id: int, content: str
) -> _TurnContext:
    """
    Записать реплику человека и вернуть контекст хода вместе с позицией ответа.

    Сессия открывается и закрывается здесь целиком: к моменту, когда начнётся
    генерация, соединение уже возвращено в пул.

    Здесь же разговор приводится к текущей версии контекста: системный промпт с
    карточкой — не тот, под которым собиралась прежняя сессия CLI, и продолжать
    её было бы продолжением разговора с другой моделью поведения.
    """
    async with factory() as db:
        conversation = await chat_crud.get_conversation(db, conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation {conversation_id} not found",
            )
        await chat_crud.reset_stale_context(
            db, conversation, version=CHAT_CONTEXT_VERSION
        )
        card = await build_day_card(db, conversation.started_on)
        history = await chat_crud.list_messages(db, conversation_id)
        turns = [ChatTurn(role=one.role, content=one.content) for one in history]

        seq = await chat_crud.next_seq(db, conversation_id)
        await chat_crud.add_message(
            db,
            conversation_id=conversation_id,
            seq=seq,
            role=MESSAGE_ROLE_USER,
            content=content,
        )
        await chat_crud.touch_conversation(
            db,
            conversation,
            at=now_utc(),
            title=chat_crud.title_from(content),
        )
        await db.commit()

    turns.append(ChatTurn(role=MESSAGE_ROLE_USER, content=content))
    return _TurnContext(
        turns=turns,
        answer_seq=seq + 1,
        system_prompt=compose_system_prompt(card.text),
    )


async def _record_answer(
    factory: SessionFactory,
    *,
    conversation_id: int,
    seq: int,
    text: str,
    status_value: str,
    error_code: str | None,
    usage: ChatChunk | None,
    latency_ms: int,
    client: ChatLLMClient,
) -> int:
    """Записать ответ новой сессией и вернуть id сообщения."""
    async with factory() as db:
        message = await chat_crud.add_message(
            db,
            conversation_id=conversation_id,
            seq=seq,
            role=MESSAGE_ROLE_ASSISTANT,
            content=text,
            status=status_value,
            error_code=error_code,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_tokens=usage.cache_read_tokens if usage else None,
            latency_ms=latency_ms,
            model=client.model,
        )
        conversation = await chat_crud.get_conversation(db, conversation_id)
        if conversation is not None:
            await chat_crud.touch_conversation(
                db,
                conversation,
                at=now_utc(),
                llm_backend=client.backend,
                cli_session_id=usage.session_id if usage else None,
                cli_cwd=client.cwd,
            )
        await db.commit()
        return message.id


async def _turn_events(
    *,
    factory: SessionFactory,
    client: ChatLLMClient,
    conversation_id: int,
    answer_seq: int,
    turns: list[ChatTurn],
    system_prompt: str,
) -> AsyncIterator[str]:
    """
    Ход целиком как поток событий SSE.

    Порядок в норме: сколько угодно `delta`, затем `usage`, затем один `done`.
    `error` заменяет два последних, и сообщение при этом всё равно пишется — со
    статусом `failed` и машинным кодом, чтобы обрыв и отказ различались в ленте.
    """
    started = time.monotonic()
    parts: list[str] = []
    usage: ChatChunk | None = None
    status_value = MESSAGE_STATUS_COMPLETE
    error_code: str | None = None
    written = False

    try:
        try:
            async for chunk in client.stream_turn(
                system_prompt=system_prompt, turns=turns
            ):
                if chunk.kind == CHUNK_DELTA:
                    parts.append(chunk.text)
                    yield _sse(SSE_EVENT_DELTA, {"text": chunk.text})
                else:
                    usage = chunk
                    yield _sse(
                        SSE_EVENT_USAGE,
                        {
                            "input_tokens": chunk.input_tokens,
                            "output_tokens": chunk.output_tokens,
                            "cache_read_tokens": chunk.cache_read_tokens,
                        },
                    )
        except LLMError:
            # Текст исключения не пересылается наружу: у него нет обязательства
            # не содержать куска промпта. Наружу идёт код.
            status_value = MESSAGE_STATUS_FAILED
            error_code = ERROR_CODE_BACKEND

        latency_ms = int((time.monotonic() - started) * MILLISECONDS_PER_SECOND)
        message_id = await _record_answer(
            factory,
            conversation_id=conversation_id,
            seq=answer_seq,
            text="".join(parts),
            status_value=status_value,
            error_code=error_code,
            usage=usage,
            latency_ms=latency_ms,
            client=client,
        )
        written = True

        if error_code is not None:
            yield _sse(SSE_EVENT_ERROR, {"code": error_code, "message_id": message_id})
        else:
            yield _sse(
                SSE_EVENT_DONE,
                {"message_id": message_id, "seq": answer_seq, "status": status_value},
            )
    finally:
        if not written:
            # Сюда попадает обрыв соединения: генератор закрывают, куски уже
            # получены, и терять их нельзя. Отдавать событие в закрытый поток
            # нельзя тоже — потому запись есть, а `done` нет.
            latency_ms = int((time.monotonic() - started) * MILLISECONDS_PER_SECOND)
            await _record_answer(
                factory,
                conversation_id=conversation_id,
                seq=answer_seq,
                text="".join(parts),
                status_value=MESSAGE_STATUS_INTERRUPTED,
                error_code=None,
                usage=usage,
                latency_ms=latency_ms,
                client=client,
            )


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: int,
    payload: MessageCreate,
    factory: SessionFactory = Depends(get_session_factory),
    client: ChatLLMClient | None = Depends(get_chat_llm_client),
) -> StreamingResponse:
    """
    Ход разговора: реплика человека внутрь, ответ модели потоком наружу.

    Отвечает `text/event-stream`. События: `delta` — кусок текста, `usage` —
    чем обошёлся ход, `done` — ход закрыт, `error` — бэкенд не смог.
    503 — бэкенда нет; реплика в этом случае не записывается.
    """
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chat is disabled: no LLM backend available "
                "(set ANTHROPIC_API_KEY or install the claude CLI)"
            ),
        )

    context = await _record_question(factory, conversation_id, payload.content)

    return StreamingResponse(
        _turn_events(
            factory=factory,
            client=client,
            conversation_id=conversation_id,
            answer_seq=context.answer_seq,
            turns=context.turns,
            system_prompt=context.system_prompt,
        ),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )
