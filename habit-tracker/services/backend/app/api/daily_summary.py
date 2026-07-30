# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: POST /daily-summary/draft (text -> validated metric plan + journal op with its append/create mode) and /apply (one transaction, Idempotency-Key aware via applied_daily_summaries; 409 on a key reused with a new metric, a new journal or another date, including on the loser of a race)
import logging
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core.database import get_db
from app.crud import category as category_crud
from app.crud import daily_summary as daily_summary_crud
from app.crud import journal as journal_crud
from app.crud import transcript as transcript_crud
from app.crud.daily_summary import DAILY_SUMMARY_SOURCE, DailySummaryApplyError
from app.llm.client import LLMClient, LLMError
from app.llm.daily_summary import DailySummaryPlanError, generate_daily_summary_plan
from app.schemas.daily_summary import (
    DailySummaryApplyRequest,
    DailySummaryApplyResponse,
    DailySummaryDraftRequest,
    DailySummaryDraftResponse,
    DailySummaryPlan,
    JournalOpPreview,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/daily-summary", tags=["daily-summary"])


async def _resolve_journal_op(
    db: AsyncSession, plan: DailySummaryPlan, entry_date: date
) -> JournalOpPreview | None:
    """
    Достроить журнальную операцию до предпросмотра: дописать или создать.

    Решает бэкенд, а не модель: есть ли за дату запись — факт базы, а не пересказа.
    Режим `replace` здесь не появляется никогда — вариант «заменить текст» есть на
    экране, выключен, и включает его только пользователь.
    """
    if plan.journal is None:
        return None

    existing = await journal_crud.get_day_journal_entry(db, entry_date)
    return JournalOpPreview(
        **plan.journal.model_dump(),
        mode="append" if existing is not None else "create",
        existing_entry_id=existing.id if existing is not None else None,
    )


@router.post("/draft", response_model=DailySummaryDraftResponse)
async def draft_plan(
    payload: DailySummaryDraftRequest,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm_client),
) -> DailySummaryDraftResponse:
    """
    Разобрать пересказ дня в план числовых записей и текст дня.

    План не персистится — это предпросмотр, производный от текста; повторный
    вызов строит его заново. Персистится сам текст: он ложится в `transcripts`
    до обращения к модели, поэтому сбой генерации не теряет сказанное.

    Модель получает каталог категорий с идентификаторами и обязана вернуть
    `category_id` и `field_id`; имена в разрешении не участвуют. Метрика, для
    которой категории не нашлось, приходит в `unresolved` и ничего не создаёт.

    Журнальная операция приходит уже с решённой коллизией: если за дату запись
    есть, операция называется дописыванием и несёт id этой записи; если нет —
    созданием. Модель об этом не спрашивают, она про базу ничего не знает.

    Бэкенд LLM недоступен -> 503. Сбой самого бэкенда или двойной провал
    парсинга/валидации -> 502.
    """
    if llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Daily summary is disabled: no LLM backend available "
                "(set ANTHROPIC_API_KEY or install the claude CLI)"
            ),
        )

    await transcript_crud.save_transcript(db, DAILY_SUMMARY_SOURCE, payload.transcript)
    categories = await category_crud.get_categories(db, limit=None, active_only=True)

    try:
        plan = await generate_daily_summary_plan(
            llm, categories, payload.transcript, payload.entry_date
        )
    except LLMError as exc:
        logger.warning("daily summary LLM backend failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM request failed",
        ) from exc
    except DailySummaryPlanError as exc:
        # Neither the day's text nor the validation-error text is logged: the
        # first is the most personal data in the app, the second can quote it.
        logger.warning("daily summary plan generation failed after repair pass")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Daily summary plan generation failed",
        ) from exc

    return DailySummaryDraftResponse(
        metrics=plan.metrics,
        unresolved=plan.unresolved,
        journal=await _resolve_journal_op(db, plan, payload.entry_date),
    )


@router.post(
    "/apply",
    response_model=DailySummaryApplyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_plan(
    payload: DailySummaryApplyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DailySummaryApplyResponse:
    """
    Применить выбранное одной транзакцией: метрики и текст дня, всё-или-ничего.

    Частично применённый день — состояние, в котором непонятно, что доделывать,
    поэтому его не бывает по построению: любой отказ откатывает весь план,
    включая уже записанные метрики, если упала запись журнала.

    Повтор после успеха закрыт `Idempotency-Key` по образцу `POST /entries`
    (#39): применение дня оставляет строку в `applied_daily_summaries`, и повтор
    с тем же ключом находит её, возвращает исходный результат с HTTP 200 и
    ничего не пишет — в том числе не дописывает пересказ в журнал второй раз.
    Носитель ключа — сам факт применения, а не созданные записи, поэтому apply
    одного лишь журнала дедуплицируется наравне с метриками. Первое применение
    отвечает 201. Без заголовка поведение прежнее: второй успешный вызов пишет
    вторые записи.

    Повтор с тем же ключом, но с чем-то сверх записанного — не повтор:
    пользователь отметил ещё одну галочку, включил журнал или перешёл на
    следующую дату. Добавленная метрика, журнал там, где исходное применение
    его не писало, и другая дата дают 409, иначе добавленное молча пропало бы
    навсегда — тем же ключом его уже не записать.

    Ids проверяются заново, а не принимаются на веру: план приходит с клиента, и
    между предпросмотром и применением категория могла измениться. Несуществующая
    категория, чужое поле или нечисловой тип -> 400 с текстом из одних id.

    Откат при сбое делает сам `apply_daily_summary` — в отличие от
    `app/api/entries.py`, где `rollback()` живёт в роутере. Второй здесь не
    нужен и вреден: сессия к этому моменту уже чистая.
    """
    try:
        if idempotency_key is not None:
            replayed = await daily_summary_crud.find_applied_summary(
                db, payload, idempotency_key
            )
            if replayed is not None:
                response.status_code = status.HTTP_200_OK
                return replayed

        categories = await category_crud.get_categories(
            db, limit=None, active_only=True
        )
        return await daily_summary_crud.apply_daily_summary(
            db, payload, categories, idempotency_key
        )
    except DailySummaryApplyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except IntegrityError:
        # A concurrent apply won the race between the lookup above and the
        # insert; the unique key on applied_daily_summaries is the backstop.
        # Re-read and answer with what the winner wrote instead of failing the
        # second click.
        if idempotency_key is None:
            raise
        # The re-read rejects as readily as the first lookup does — the loser of
        # the race may carry a metric or a journal the winner never wrote. That
        # is the client's 409, so it is caught here: the `except` above has
        # already been passed by, and letting it escape would answer a plain
        # conflict with a 500.
        try:
            winner = await daily_summary_crud.find_applied_summary(
                db, payload, idempotency_key
            )
        except DailySummaryApplyError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        if winner is None:
            raise
        response.status_code = status.HTTP_200_OK
        return winner
