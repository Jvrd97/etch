# [review:need-review] PHASE-03/111, PHASE-03/116
# summary: the chat router — conversations created, listed and read back with their messages, and one turn answered as text/event-stream; the answer row is opened as `streaming` before generation (it is also the lock that makes a second POST a 409), closed from `finally` on every exit, refused with 502 when the backend dies before the first frame, and unstuck by a reset handle when the worker died with it
"""
Ручки разговора.

**Сессия БД не живёт столько, сколько живёт генерация.** Контекст читается,
сессия отпускается, ответ пишется новой. Иначе соединение из пула занято все сто
двадцать секунд хода, и на двух воркерах разговор выедает пул целиком. Поэтому
ход берёт `get_session_factory`, а не `get_db`.

**503 проверяется до записи.** Отсутствие бэкенда — не сбой хода, а выключенная
функция, и реплика человека при ней не должна оседать в `chat_messages`: иначе
разговор пополняется вопросами, на которые никто никогда не отвечал.

**Ответ записывается и тогда, когда его дослушать не успели.** Строка ответа
заводится до генерации, со статусом `streaming`, и закрывается из `finally`
генератора. Закрытая вкладка оставляет сообщение со статусом `interrupted` и
уже полученным текстом, а не пустоту.

**Эта же строка запирает диалог.** Второй POST, пришедший, пока ход не закрыт,
получает 409 и второго процесса CLI не поднимает. Замок живёт в таблице, а не в
памяти воркера: воркер, умерший вместе с процессом, оставил бы память чистой, а
ответ — пустым и вечно «идущим». Для этого случая есть ручка сброса.

**Отказ бэкенда виден кодом ответа, пока ответ ещё не начался.** Первый кадр
потока вытягивается до того, как отдан заголовок: пришла ошибка — ручка отвечает
502 и ничего не стримит. Сломавшийся на середине ход заголовок уже отдал, и
единственное, что ему остаётся, — событие `error`; поэтому оба пути и существуют.

**Ни одна строка содержимого не попадает в лог.** Наружу и в базу уходит
машинный `error_code`; текст модели живёт ровно в `chat_messages.content`.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionFactory, get_chat_llm_client, get_session_factory
from app.core.database import get_db
from app.core.daytime import now_utc, today_local
from app.crud import chat as chat_crud
from app.llm.chat.client import CHUNK_DELTA, ChatChunk, ChatLLMClient
from app.llm.chat.limits import (
    ERROR_FIRST_DELTA_TIMEOUT,
    ERROR_SLOTS_BUSY,
    ERROR_TURN_TIMEOUT,
    SlotsBusyError,
    TurnSlot,
    acquire_turn_slot,
    guarded_turn,
)
from app.llm.chat.prompt import CHAT_SYSTEM_PROMPT, ChatTurn
from app.llm.client import LLMError
from app.models.chat import (
    CONVERSATION_KINDS,
    MESSAGE_ROLE_USER,
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INTERRUPTED,
    ChatConversation,
)
from app.schemas.chat import (
    FEED_MAX_LIMIT,
    ResetResponse,
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

# Коды, которым соответствует не 502, а свой ответ. Занятый потолок — это не
# сбой бэкенда, а «попробуйте через минуту», и путать их кодом ответа значит
# заставлять фронт разбираться в причине по тексту.
ERROR_CODE_STATUS = {ERROR_SLOTS_BUSY: status.HTTP_429_TOO_MANY_REQUESTS}

MILLISECONDS_PER_SECOND = 1000

# Один кадр потока до того, как он стал текстом SSE: имя события и его данные.
Frame = tuple[str, dict[str, object]]


def _sse(event: str, data: dict[str, object]) -> str:
    """
    Одно событие SSE. Данные — JSON в одну строку.

    Перевод строки внутри текста ответа экранируется JSON'ом, поэтому событие
    остаётся однострочным. Сырой текст в `data:` разорвал бы кадр на первом же
    абзаце ответа.
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _detail(
    conversation: ChatConversation, messages: list[MessageResponse]
) -> ConversationDetail:
    """Разговор с сообщениями — DTO, а не доменная модель наружу."""
    return ConversationDetail(
        **ConversationResponse.model_validate(conversation).model_dump(),
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
    return _detail(
        conversation, [MessageResponse.model_validate(one) for one in messages]
    )


async def _open_turn(
    factory: SessionFactory, conversation_id: int, content: str, model: str | None
) -> tuple[list[ChatTurn], int, int]:
    """
    Записать реплику человека, завести ход и вернуть контекст с ответом.

    Одна транзакция под блокировкой строки разговора: пока она открыта, второй
    POST в этот же диалог ждёт, а дождавшись — видит незакрытый ход и получает
    409. Сессия закрывается здесь же: к началу генерации соединение уже в пуле.
    """
    async with factory() as db:
        conversation = await chat_crud.get_conversation_for_update(db, conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation {conversation_id} not found",
            )
        open_turn = await chat_crud.find_open_turn(db, conversation_id)
        if open_turn is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"turn {open_turn.seq} of conversation {conversation_id} "
                    "is still running"
                ),
            )

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
        answer = await chat_crud.open_turn(
            db, conversation_id=conversation_id, seq=seq + 1, model=model
        )
        await chat_crud.touch_conversation(
            db,
            conversation,
            at=now_utc(),
            title=chat_crud.title_from(content),
        )
        await db.commit()
        answer_id, answer_seq = answer.id, answer.seq

    turns.append(ChatTurn(role=MESSAGE_ROLE_USER, content=content))
    return turns, answer_id, answer_seq


async def _close_turn(
    factory: SessionFactory,
    *,
    conversation_id: int,
    message_id: int,
    text: str,
    status_value: str,
    error_code: str | None,
    usage: ChatChunk | None,
    latency_ms: int,
    client: ChatLLMClient,
) -> None:
    """Дописать заведённый ход новой сессией и отметить разговор."""
    async with factory() as db:
        await chat_crud.close_turn(
            db,
            message_id,
            content=text,
            status=status_value,
            error_code=error_code,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_tokens=usage.cache_read_tokens if usage else None,
            latency_ms=latency_ms,
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


# Коды вотчдога переживают дорогу до базы как есть: «замолчал на старте» и «не
# уложился в срок» — разные поломки. Всё остальное схлопывается в один общий
# код, потому что текст исключения не обязан быть свободным от куска промпта.
WATCHDOG_CODES = frozenset({ERROR_FIRST_DELTA_TIMEOUT, ERROR_TURN_TIMEOUT})


def _machine_code(exc: LLMError) -> str:
    """Машинный код отказа хода — из белого списка либо общий."""
    text = str(exc)
    return text if text in WATCHDOG_CODES else ERROR_CODE_BACKEND


async def _turn_frames(
    *,
    factory: SessionFactory,
    client: ChatLLMClient,
    slot: TurnSlot,
    conversation_id: int,
    message_id: int,
    answer_seq: int,
    turns: list[ChatTurn],
) -> AsyncGenerator[Frame, None]:
    """
    Ход целиком как поток кадров: имя события и его данные.

    Порядок в норме: сколько угодно `delta`, затем `usage`, затем один `done`.
    `error` заменяет два последних.

    Статус по умолчанию — `interrupted`, и это несущее решение: сюда попадает
    выход через закрытие генератора, то есть закрытая вкладка, и статус в этом
    случае никто не выставит явно. `complete` ставится только после того, как
    поток кончился сам; `failed` — по исключению. Закрытие хода стоит в
    `finally`, потому что незакрытая строка `streaming` запирает диалог до
    ручного сброса.
    """
    started = time.monotonic()
    parts: list[str] = []
    usage: ChatChunk | None = None
    status_value = MESSAGE_STATUS_INTERRUPTED
    error_code: str | None = None
    try:
        try:
            async for chunk in guarded_turn(
                client.stream_turn(system_prompt=CHAT_SYSTEM_PROMPT, turns=turns)
            ):
                if chunk.kind == CHUNK_DELTA:
                    parts.append(chunk.text)
                    yield SSE_EVENT_DELTA, {"text": chunk.text}
                else:
                    usage = chunk
                    yield (
                        SSE_EVENT_USAGE,
                        {
                            "input_tokens": chunk.input_tokens,
                            "output_tokens": chunk.output_tokens,
                            "cache_read_tokens": chunk.cache_read_tokens,
                        },
                    )
        except LLMError as exc:
            status_value = MESSAGE_STATUS_FAILED
            error_code = _machine_code(exc)
            yield SSE_EVENT_ERROR, {"code": error_code, "message_id": message_id}
        else:
            status_value = MESSAGE_STATUS_COMPLETE
            yield (
                SSE_EVENT_DONE,
                {
                    "message_id": message_id,
                    "seq": answer_seq,
                    "status": status_value,
                },
            )
    finally:
        latency_ms = int((time.monotonic() - started) * MILLISECONDS_PER_SECOND)
        await _close_turn(
            factory,
            conversation_id=conversation_id,
            message_id=message_id,
            text="".join(parts),
            status_value=status_value,
            error_code=error_code,
            usage=usage,
            latency_ms=latency_ms,
            client=client,
        )
        # Слот отпускается здесь, а не в ручке: ход, упавший на середине, иначе
        # держал бы потолок до перезапуска воркера.
        slot.release()


async def _as_sse(
    first: Frame, rest: AsyncGenerator[Frame, None]
) -> AsyncIterator[str]:
    """
    Кадры в текст SSE. Первый уже вытянут ручкой — он идёт вперёд остальных.

    Внутренний генератор закрывается явно. `async for` его не закрывает: обрыв
    соединения закрыл бы только эту обёртку, а ход остался бы висеть до сборки
    мусора — то есть строка `streaming` дожила бы до неё же, запирая диалог.
    """
    try:
        yield _sse(*first)
        async for frame in rest:
            yield _sse(*frame)
    finally:
        await rest.aclose()


async def _first_frame(frames: AsyncGenerator[Frame, None]) -> Frame | None:
    """Первый кадр хода, либо None — поток кончился, не сказав ничего."""
    async for frame in frames:
        return frame
    return None


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
    чем обошёлся ход, `done` — ход закрыт, `error` — бэкенд сломался уже после
    того, как поток начался.

    Коды отказа: 503 — бэкенда нет и реплика не записывается; 409 — в этом
    диалоге ход ещё не закрыт; 429 — свободного слота не нашлось; 502 — бэкенд
    не смог отдать даже первый кадр.
    """
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chat is disabled: no LLM backend available "
                "(set ANTHROPIC_API_KEY or install the claude CLI)"
            ),
        )

    # Слот занимается до записи реплики: отказ по потолку не должен оставлять в
    # разговоре вопрос, на который никто не собирался отвечать.
    try:
        slot = await acquire_turn_slot()
    except SlotsBusyError as exc:
        # Машинный код и здесь: экран расшифровывает отказ сам, как и `error`
        # в потоке, и разбирать причину по английской фразе ему не нужно.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_SLOTS_BUSY,
        ) from exc

    try:
        turns, message_id, answer_seq = await _open_turn(
            factory, conversation_id, payload.content, client.model
        )
    except BaseException:
        # 404, 409 и всё, что может случиться между занятием слота и началом
        # хода. Дальше слот отпускает генератор, а сюда он не дойдёт.
        slot.release()
        raise

    frames = _turn_frames(
        factory=factory,
        client=client,
        slot=slot,
        conversation_id=conversation_id,
        message_id=message_id,
        answer_seq=answer_seq,
        turns=turns,
    )

    # Первый кадр вытягивается до заголовка ответа. Пока он не отдан, отказ ещё
    # может стать кодом HTTP; после — только событием `error` в уже открытом
    # потоке. Отсюда и берётся обещанный тикетом 502 вместо 500 и пустой ленты.
    first = await _first_frame(frames)
    if first is None or first[0] == SSE_EVENT_ERROR:
        await frames.aclose()
        code = str(first[1].get("code")) if first is not None else ERROR_CODE_BACKEND
        raise HTTPException(
            status_code=ERROR_CODE_STATUS.get(code, status.HTTP_502_BAD_GATEWAY),
            detail=code,
        )

    return StreamingResponse(
        _as_sse(first, frames),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


@router.post("/conversations/{conversation_id}/reset", response_model=ResetResponse)
async def reset_conversation(
    conversation_id: int, db: AsyncSession = Depends(get_db)
) -> ResetResponse:
    """
    Расклинить диалог: незакрытые ходы переводятся в `interrupted`.

    Нужно для одного случая — воркер умер вместе с процессом CLI, и строка
    ответа осталась в `streaming` навсегда. Текст, который успел прийти,
    остаётся на месте: меняется статус, а не содержимое. После сброса диалог
    снова принимает сообщения.
    """
    conversation = await chat_crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id} not found",
        )
    reset = await chat_crud.reset_open_turns(db, conversation_id)
    await db.commit()
    return ResetResponse(reset=reset)
