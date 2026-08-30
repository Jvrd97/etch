# [review:need-review] PHASE-03/111, PHASE-03/112
# summary: the chat router — conversations created, listed and read back with their messages and with whether the next turn continues a CLI session, and one turn answered as text/event-stream whose answer is written by a session opened after generation, never by the one that read the context
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

**Ни одна строка содержимого не попадает в лог.** Наружу и в базу уходит
машинный `error_code`; текст модели живёт ровно в `chat_messages.content`.

**Стратегию хода выбирает транспорт, а не ручка.** Отсюда уходит подсказка из
таблицы (`ResumeHint`), обратно приезжает id сессии; продолжать её или собирать
разговор заново — решает `app/llm/chat`. Ручка знает ровно одно решение сама:
устаревшую версию контекста она обнуляет до хода, чтобы таблица не показывала
сессию, которой уже нельзя пользоваться.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionFactory, get_chat_llm_client, get_session_factory
from app.core.database import get_db
from app.core.daytime import now_utc, today_local
from app.crud import chat as chat_crud
from app.llm.chat.client import CHUNK_DELTA, ChatChunk, ChatLLMClient
from app.llm.chat.prompt import CHAT_CONTEXT_VERSION, CHAT_SYSTEM_PROMPT, ChatTurn
from app.llm.chat.session import ResumeHint
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
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
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


def _hint(conversation: ChatConversation) -> ResumeHint:
    """Что таблица помнит о сессии прошлого хода этого разговора."""
    return ResumeHint(
        session_id=conversation.cli_session_id,
        cwd=conversation.cli_cwd,
        context_version=conversation.context_version,
    )


def _detail(
    conversation: ChatConversation,
    messages: list[MessageResponse],
    *,
    client: ChatLLMClient | None,
) -> ConversationDetail:
    """
    Разговор с сообщениями — DTO, а не доменная модель наружу.

    `resume_ready` считает транспорт, а не эта функция: условий продолжения
    четыре, и второе их описание разошлось бы с первым молча. Выключенный чат
    (`client is None`) продолжать нечего, и флаг у него ложный.
    """
    return ConversationDetail(
        **ConversationResponse.model_validate(conversation).model_dump(),
        messages=messages,
        resume_ready=client is not None and client.resumes(_hint(conversation)),
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate | None = None,
    db: AsyncSession = Depends(get_db),
) -> ChatConversation:
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
    return await chat_crud.create_conversation(
        db,
        started_on=request.started_on or today_local(),
        kind=request.kind,
        title=request.title,
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    limit: int = Query(default=chat_crud.DEFAULT_FEED_LIMIT, ge=1, le=FEED_MAX_LIMIT),
    archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[ChatConversation]:
    """Лента разговоров, свежие сверху."""
    return list(await chat_crud.list_conversations(db, limit=limit, archived=archived))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    client: ChatLLMClient | None = Depends(get_chat_llm_client),
) -> ConversationDetail:
    """
    Разговор целиком: сообщения в порядке `seq`, а не по времени записи.

    `resume_ready` отвечает на вопрос «следующий ход продолжит сессию или
    пересоберёт разговор». Без него разница в цене хода не видна нигде: счётчики
    в `chat_messages` рассказывают про ход прошлый, а не про следующий.
    """
    conversation = await chat_crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id} not found",
        )
    messages = await chat_crud.list_messages(db, conversation_id)
    return _detail(
        conversation,
        [MessageResponse.model_validate(one) for one in messages],
        client=client,
    )


async def _record_question(
    factory: SessionFactory, conversation_id: int, content: str
) -> tuple[list[ChatTurn], int, ResumeHint]:
    """
    Записать реплику человека и вернуть контекст хода, позицию ответа и подсказку.

    Сессия открывается и закрывается здесь целиком: к моменту, когда начнётся
    генерация, соединение уже возвращено в пул.

    Устаревшая версия контекста обнуляет `cli_session_id` здесь, до хода. Так
    таблица и подсказка расходятся ровно ноль времени: наружу уходит уже
    вычищенный `ResumeHint`, а не тот, что заставил бы транспорт проверять
    версию второй раз и надеяться на тот же ответ.

    История читается `list_messages`, то есть в порядке `seq`. Порядок по
    `created_at` переставил бы местами два сообщения одной секунды, и разговор
    реплеился бы задом наперёд.
    """
    async with factory() as db:
        conversation = await chat_crud.get_conversation(db, conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation {conversation_id} not found",
            )
        await chat_crud.drop_stale_session(
            db, conversation, context_version=CHAT_CONTEXT_VERSION
        )
        hint = _hint(conversation)

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
    return turns, seq + 1, hint


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
                context_version=CHAT_CONTEXT_VERSION,
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
    resume: ResumeHint,
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
                system_prompt=CHAT_SYSTEM_PROMPT, turns=turns, resume=resume
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

    turns, answer_seq, resume = await _record_question(
        factory, conversation_id, payload.content
    )

    return StreamingResponse(
        _turn_events(
            factory=factory,
            client=client,
            conversation_id=conversation_id,
            answer_seq=answer_seq,
            turns=turns,
            resume=resume,
        ),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )
