# [review:need-review] PHASE-03/111, PHASE-03/112, PHASE-03/113, PHASE-03/115, PHASE-03/116, PHASE-03/117
# summary: the chat router — conversations created, listed and read back with their messages, the plans proposed in them and whether the next turn continues a CLI session, one turn answered as text/event-stream whose answer is written by a session opened after generation, never by the one that read the context, and the apply that goes through the existing transactional `apply_daily_summary` rather than writing anything of its own
# summary: PHASE-03/117 adds DELETE /conversations/{id} (204, cascade plus the CLI session file) and hangs the usage rollup on both the feed and the detail
# summary: PHASE-03/113 builds the day card in the same session that records the question, sends it in the system prompt, and shows it back through GET /conversations/{id}/context
# summary: PHASE-03/116 opens the answer row as `streaming` before generation (it is also the lock that makes a second POST a 409), closes it from `finally` on every exit, refuses with 502 when the backend dies before the first frame, and unsticks a dialogue by a reset handle when the worker died with it
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

**Стратегию хода выбирает транспорт, а не ручка.** Отсюда уходит подсказка из
таблицы (`ResumeHint`), обратно приезжает id сессии; продолжать её или собирать
разговор заново — решает `app/llm/chat`. Ручка знает ровно одно решение сама:
устаревшую версию контекста она обнуляет до хода, чтобы таблица не показывала
сессию, которой уже нельзя пользоваться.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)
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
from app.llm.chat.context import build_day_card
from app.llm.chat.limits import (
    ERROR_FIRST_DELTA_TIMEOUT,
    ERROR_SLOTS_BUSY,
    ERROR_TURN_TIMEOUT,
    SlotsBusyError,
    TurnSlot,
    acquire_turn_slot,
    guarded_turn,
)
from app.llm.chat.plan import plan_from_answer
from app.llm.chat.prompt import (
    CHAT_CONTEXT_VERSION,
    ChatTurn,
    compose_system_prompt,
)
from app.llm.chat.session import ResumeHint
from app.llm.client import LLMError
from app.schemas.daily_summary import DailySummaryApplyRequest
from app.models.chat import (
    CONVERSATION_KINDS,
    PLAN_STATUS_APPLIED,
    PLAN_STATUS_DISMISSED,
    PLAN_STATUS_PROPOSED,
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
    ResetResponse,
    ChatPlanApply,
    ChatPlanApplyResponse,
    ChatPlanResponse,
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

# Коды, которым соответствует не 502, а свой ответ. Занятый потолок — это не
# сбой бэкенда, а «попробуйте через минуту», и путать их кодом ответа значит
# заставлять фронт разбираться в причине по тексту.
ERROR_CODE_STATUS = {ERROR_SLOTS_BUSY: status.HTTP_429_TOO_MANY_REQUESTS}

# Коды вотчдога переживают дорогу до базы как есть: «замолчал на старте» и «не
# уложился в срок» — разные поломки. Всё остальное схлопывается в один общий
# код, потому что текст исключения не обязан быть свободным от куска промпта.
WATCHDOG_CODES = frozenset({ERROR_FIRST_DELTA_TIMEOUT, ERROR_TURN_TIMEOUT})


def _machine_code(exc: LLMError) -> str:
    """Машинный код отказа хода — из белого списка либо общий."""
    text = str(exc)
    return text if text in WATCHDOG_CODES else ERROR_CODE_BACKEND


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
    usage: chat_crud.ConversationUsage,
    *,
    client: ChatLLMClient | None,
) -> ConversationDetail:
    """
    Разговор с сообщениями и расходом — DTO, а не доменная модель наружу.

    `resume_ready` считает транспорт, а не эта функция: условий продолжения
    четыре, и второе их описание разошлось бы с первым молча. Выключенный чат
    (`client is None`) продолжать нечего, и флаг у него ложный.
    """
    return ConversationDetail(
        **_feed_item(conversation, usage).model_dump(),
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
    usage = await chat_crud.usage_of(db, conversation_id)
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
        usage,
        client=client,
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
    resume: ResumeHint
    # Строка ответа заводится до генерации (`#116`): она же — замок диалога.
    message_id: int


async def _open_turn(
    factory: SessionFactory, conversation_id: int, content: str, model: str | None
) -> _TurnContext:
    """
    Записать реплику человека, завести ход и вернуть его контекст.

    Сессия открывается и закрывается здесь целиком: к моменту, когда начнётся
    генерация, соединение уже возвращено в пул.

    Одна транзакция под блокировкой строки разговора (`#116`): пока она открыта,
    второй POST в этот же диалог ждёт, а дождавшись — видит незакрытый ход и
    получает 409. Строка ответа заводится здесь же, со статусом `streaming`:
    она и есть замок, и живёт он в таблице, а не в памяти воркера.

    Здесь же разговор приводится к текущей версии контекста: системный промпт с
    карточкой — не тот, под которым собиралась прежняя сессия CLI, и продолжать
    её было бы продолжением разговора с другой моделью поведения. Обнуление
    происходит до хода, поэтому таблица и подсказка расходятся ровно ноль
    времени: наружу уходит уже вычищенный `ResumeHint`.

    История читается `list_messages`, то есть в порядке `seq`. Порядок по
    `created_at` переставил бы местами два сообщения одной секунды, и разговор
    реплеился бы задом наперёд.
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
        await chat_crud.drop_stale_session(
            db, conversation, context_version=CHAT_CONTEXT_VERSION
        )
        hint = _hint(conversation)
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
    return _TurnContext(
        turns=turns,
        answer_seq=answer_seq,
        system_prompt=compose_system_prompt(card.text),
        resume=hint,
        message_id=answer_id,
    )


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
                context_version=CHAT_CONTEXT_VERSION,
            )
        await _attach_plan(
            db,
            message_id=message_id,
            text=text,
            complete=status_value == MESSAGE_STATUS_COMPLETE,
        )
        await db.commit()


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


async def _turn_frames(
    *,
    factory: SessionFactory,
    client: ChatLLMClient,
    slot: TurnSlot,
    conversation_id: int,
    context: _TurnContext,
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
                client.stream_turn(
                    system_prompt=context.system_prompt,
                    turns=context.turns,
                    resume=context.resume,
                )
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
            # Текст исключения не пересылается наружу: у него нет обязательства
            # не содержать куска промпта. Наружу идёт код.
            status_value = MESSAGE_STATUS_FAILED
            error_code = _machine_code(exc)
            yield (
                SSE_EVENT_ERROR,
                {
                    "code": error_code,
                    "message_id": context.message_id,
                },
            )
        else:
            status_value = MESSAGE_STATUS_COMPLETE
            yield (
                SSE_EVENT_DONE,
                {
                    "message_id": context.message_id,
                    "seq": context.answer_seq,
                    "status": status_value,
                },
            )
    finally:
        latency_ms = int((time.monotonic() - started) * MILLISECONDS_PER_SECOND)
        await _close_turn(
            factory,
            conversation_id=conversation_id,
            message_id=context.message_id,
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
        context = await _open_turn(
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
        context=context,
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
