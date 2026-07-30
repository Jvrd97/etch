# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: POST /daily-summary/draft (text -> validated metric plan, transcript stored) and /apply (one transaction)
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core.database import get_db
from app.crud import category as category_crud
from app.crud import daily_summary as daily_summary_crud
from app.crud import transcript as transcript_crud
from app.crud.daily_summary import DAILY_SUMMARY_SOURCE, DailySummaryApplyError
from app.llm.client import LLMClient, LLMError
from app.llm.daily_summary import DailySummaryPlanError, generate_daily_summary_plan
from app.schemas.daily_summary import (
    DailySummaryApplyRequest,
    DailySummaryApplyResponse,
    DailySummaryDraftRequest,
    DailySummaryPlan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/daily-summary", tags=["daily-summary"])


@router.post("/draft", response_model=DailySummaryPlan)
async def draft_plan(
    payload: DailySummaryDraftRequest,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm_client),
) -> DailySummaryPlan:
    """
    Разобрать пересказ дня в план числовых записей.

    План не персистится — это предпросмотр, производный от текста; повторный
    вызов строит его заново. Персистится сам текст: он ложится в `transcripts`
    до обращения к модели, поэтому сбой генерации не теряет сказанное.

    Модель получает каталог категорий с идентификаторами и обязана вернуть
    `category_id` и `field_id`; имена в разрешении не участвуют. Метрика, для
    которой категории не нашлось, приходит в `unresolved` и ничего не создаёт.

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
        return await generate_daily_summary_plan(
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


@router.post(
    "/apply",
    response_model=DailySummaryApplyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_plan(
    payload: DailySummaryApplyRequest,
    db: AsyncSession = Depends(get_db),
) -> DailySummaryApplyResponse:
    """
    Применить выбранные метрики одной транзакцией: всё-или-ничего.

    Частично применённый день — состояние, в котором непонятно, что доделывать,
    поэтому его не бывает по построению: любой отказ откатывает весь план. Это
    же делает повтор *после ошибки* безопасным без идемпотентных ключей — после
    неудачи не записано ничего.

    Повтор после *успеха* не защищён: в отличие от `POST /entries` (#39) ручка
    не принимает `Idempotency-Key`, поэтому второе успешное применение того же
    плана создаёт вторые записи, которые table суммирует. Риск принят на этом
    срезе осознанно: экран уходит на Entries сразу после успеха, так что окно
    для двойного нажатия узкое. Ключ добавляется в #74 по образцу entries.

    Ids проверяются заново, а не принимаются на веру: план приходит с клиента, и
    между предпросмотром и применением категория могла измениться. Несуществующая
    категория, чужое поле или нечисловой тип -> 400 с текстом из одних id.
    """
    categories = await category_crud.get_categories(db, limit=None, active_only=True)
    try:
        return await daily_summary_crud.apply_daily_summary(db, payload, categories)
    except DailySummaryApplyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
