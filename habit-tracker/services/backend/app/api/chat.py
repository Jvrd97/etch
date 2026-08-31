# [review:need-review] PHASE-03/111, PHASE-03/115
# summary: the chat router — conversations created, listed and read back with their messages and the plans proposed in them, one turn answered as text/event-stream whose answer is written by a session opened after generation, and the apply that goes through the existing transactional `apply_daily_summary` rather than writing anything of its own
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
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionFactory, get_chat_llm_client, get_session_factory
from app.core.database import get_db
from app.core.daytime import now_utc, today_local
from app.crud import category as category_crud
from app.crud import chat as chat_crud
from app.crud import daily_summary as daily_summary_crud
from app.crud.chat import PlanSelectionRejected, narrow_to_plan
from app.crud.daily_summary import DailySummaryApplyError
from app.llm.chat.client import CHUNK_DELTA, ChatChunk, ChatLLMClient
from app.llm.chat.plan import plan_from_answer
from app.llm.chat.prompt import CHAT_SYSTEM_PROMPT, ChatTurn
from app.llm.client import LLMError
from app.schemas.daily_summary import DailySummaryApplyRequest
from app.models.chat import (
    CONVERSATION_KINDS,
    PLAN_STATUS_APPLIED,
    PLAN_STATUS_DISMISSED,
    PLAN_STATUS_PROPOSED,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INTERRUPTED,
    ChatConversation,
)
from app.models.chat import ChatPlan as ChatPlanRow
from app.schemas.chat import ChatPlan as SchemaChatPlan
from app.schemas.chat import (
    FEED_MAX_LIMIT,
    ChatPlanApply,
    ChatPlanApplyResponse,
    ChatPlanResponse,
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
    # Один запрос на все планы ленты: плашка висит под сообщением, но запрос на
    # сообщение превратил бы открытие разговора в N обращений в базу.
    plans = await chat_crud.plans_for_messages(db, [one.id for one in messages])
    return _detail(
        conversation,
        [
            MessageResponse.model_validate(one).model_copy(
                update={
                    "plan_id": plans[one.id].id if one.id in plans else None,
                }
            )
            for one in messages
        ],
    )


async def _record_question(
    factory: SessionFactory, conversation_id: int, content: str
) -> tuple[list[ChatTurn], int]:
    """
    Записать реплику человека и вернуть контекст хода вместе с позицией ответа.

    Сессия открывается и закрывается здесь целиком: к моменту, когда начнётся
    генерация, соединение уже возвращено в пул.
    """
    async with factory() as db:
        conversation = await chat_crud.get_conversation(db, conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation {conversation_id} not found",
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
        await chat_crud.touch_conversation(
            db,
            conversation,
            at=now_utc(),
            title=chat_crud.title_from(content),
        )
        await db.commit()

    turns.append(ChatTurn(role=MESSAGE_ROLE_USER, content=content))
    return turns, seq + 1


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
        await _attach_plan(
            db,
            message_id=message.id,
            text=text,
            complete=status_value == MESSAGE_STATUS_COMPLETE,
        )
        await db.commit()
        return message.id


async def _attach_plan(
    db: AsyncSession, *, message_id: int, text: str, complete: bool
) -> None:
    """
    Записать план, если ответ его несёт.

    Ремонтный заход отсюда не делается: сессия уже открыта, ход уже закончен, и
    второй вызов модели держал бы соединение ещё на десятки секунд. Ответ, из
    которого план не собрался с первого раза, остаётся обычным сообщением — что
    и обещано в `app.llm.chat.plan`.

    Оборванный и провалившийся ход план не получает: предложение, снятое с
    половины ответа, — это предложение, которого модель не договорила.
    """
    if not complete:
        return
    plan = await plan_from_answer(text)
    if plan is None:
        return
    await chat_crud.save_plan(
        db,
        message_id=message_id,
        entry_date=plan.entry_date,
        plan=plan.model_dump(mode="json"),
    )


async def _turn_events(
    *,
    factory: SessionFactory,
    client: ChatLLMClient,
    conversation_id: int,
    answer_seq: int,
    turns: list[ChatTurn],
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
                system_prompt=CHAT_SYSTEM_PROMPT, turns=turns
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

    turns, answer_seq = await _record_question(
        factory, conversation_id, payload.content
    )

    return StreamingResponse(
        _turn_events(
            factory=factory,
            client=client,
            conversation_id=conversation_id,
            answer_seq=answer_seq,
            turns=turns,
        ),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


def _plan_response(row: ChatPlanRow) -> ChatPlanResponse:
    """Строка плана как её читает плашка."""
    plan = SchemaChatPlan.model_validate(row.plan)
    return ChatPlanResponse(
        id=row.id,
        message_id=row.message_id,
        entry_date=row.entry_date,
        status=row.status,
        plan=plan,
        operation_count=plan.operation_count(),
        applied_summary_id=row.applied_summary_id,
        applied_at=row.applied_at,
        created_at=row.created_at,
    )


async def _require_plan(db: AsyncSession, plan_id: int) -> ChatPlanRow:
    """План или 404."""
    row = await chat_crud.get_plan(db, plan_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"chat plan {plan_id} not found",
        )
    return row


@router.get("/plans/{plan_id}", response_model=ChatPlanResponse)
async def get_plan(
    plan_id: int, db: AsyncSession = Depends(get_db)
) -> ChatPlanResponse:
    """
    План, показанный сколько угодно ходов назад.

    Отдаётся ровно то, что лежит в `chat_plans.plan`. Плашка в ленте открывается
    по этой ссылке и обязана совпасть с тем, что было применено, — иначе
    персистентность плана ничего не доказывает.
    """
    return _plan_response(await _require_plan(db, plan_id))


@router.post(
    "/plans/{plan_id}/apply",
    response_model=ChatPlanApplyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Повтор с тем же Idempotency-Key: ничего не записано"},
        400: {"description": "План указывает на категорию или поле, которых нет"},
        409: {
            "description": (
                "План уже применён, погашен как `stale`, или Idempotency-Key "
                "занят другой записью"
            )
        },
        422: {"description": "Отметка в нечеклистовой категории или чужом поле"},
    },
)
async def apply_plan(
    plan_id: int,
    payload: ChatPlanApply,
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ChatPlanApplyResponse:
    """
    Записать то, что человек оставил отмеченным.

    Пишет не модель и не эта ручка: пишет `apply_daily_summary` — тот самый
    транзакционный путь, которым записывает экран разбора дня, с тем же
    `Idempotency-Key` и теми же кодами отказа. Второго способа положить данные в
    базу из разговора не заводится, поэтому и разбираться потом придётся с одним.

    Присланное сверяется с сохранённым планом: применить можно подмножество
    показанного и ничего сверх него. Дата берётся оттуда же — из плана, а не из
    тела.
    """
    row = await _require_plan(db, plan_id)
    if row.status not in (PLAN_STATUS_PROPOSED, PLAN_STATUS_APPLIED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"chat plan {plan_id} is {row.status} and cannot be applied",
        )

    stored = SchemaChatPlan.model_validate(row.plan)
    try:
        request = narrow_to_plan(stored, payload)
    except PlanSelectionRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=rejected.message
        ) from rejected

    try:
        if idempotency_key is not None:
            replayed = await daily_summary_crud.find_applied_summary(
                db, request, idempotency_key
            )
            if replayed is not None:
                response.status_code = status.HTTP_200_OK
                await db.commit()
                return ChatPlanApplyResponse(
                    plan=_plan_response(row),
                    entry_ids=replayed.entry_ids,
                    journal_entry_id=replayed.journal_entry_id,
                    applied_operations=_applied_operations(request),
                )

        categories = await category_crud.get_categories(
            db, limit=None, active_only=True
        )
        written = await daily_summary_crud.apply_daily_summary(
            db, request, categories, idempotency_key
        )
    except DailySummaryApplyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    row.status = PLAN_STATUS_APPLIED
    row.applied_at = now_utc()
    # Без внешнего ключа намеренно: удаление квитанции не должно стирать факт,
    # что план применяли. Та же причина, что у `journal_entry_id`.
    row.applied_summary_id = (
        await chat_crud.receipt_id_for(db, idempotency_key)
        if idempotency_key is not None
        else None
    )
    await db.flush()
    # План на дату, по которой уже применён другой, становится неактивным.
    await chat_crud.mark_stale_for_date(db, row.entry_date, except_plan_id=row.id)
    await db.commit()

    return ChatPlanApplyResponse(
        plan=_plan_response(row),
        entry_ids=written.entry_ids,
        journal_entry_id=written.journal_entry_id,
        applied_operations=_applied_operations(request),
    )


def _applied_operations(request: DailySummaryApplyRequest) -> int:
    """Сколько операций закрыло это применение — число под применённой плашкой."""
    return len(request.metrics) + len(request.checklist) + (1 if request.journal else 0)


# `response_model=None` — не украшение: в этом модуле включён
# `from __future__ import annotations`, и аннотация `-> None` доезжает до FastAPI
# строкой, которую тот разворачивает в тип и принимает за модель ответа. У 204
# тела нет, и без явного None маршрут не собирается вовсе.
@router.post(
    "/plans/{plan_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
async def dismiss_plan(plan_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """
    Отклонить предложение.

    Строка остаётся: отклонённый план — такой же факт разговора, как принятый, и
    «что мне предлагали и что я не взял» читается только по нему.
    """
    row = await _require_plan(db, plan_id)
    if row.status == PLAN_STATUS_APPLIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"chat plan {plan_id} is already applied",
        )
    row.status = PLAN_STATUS_DISMISSED
    await db.commit()
