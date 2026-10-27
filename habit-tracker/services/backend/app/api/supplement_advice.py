# [review:need-review] PHASE-03/223
# summary: GET /health-advice/summary (sleep, sport, supplements over 7-14 closed days, read-only) and POST /health-advice (the advice from the same summary through the orchestration layer; not stored; 422 too little data, 503 no backend, 502 model failure; no name or value in a log)
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core.daytime import today_local
from app.core.database import get_db
from app.crud import supplement_advice as advice_crud
from app.llm.client import LLMClient, LLMError
from app.llm.health_advice import write_health_advice
from app.schemas.supplement_advice import (
    MAX_WINDOW_DAYS,
    MIN_WINDOW_DAYS,
    HealthAdviceRequest,
    HealthAdviceResponse,
    HealthSummaryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health-advice", tags=["health-advice"])


@router.get("/summary", response_model=HealthSummaryResponse)
async def get_health_summary(
    days: int = Query(MIN_WINDOW_DAYS, ge=MIN_WINDOW_DAYS, le=MAX_WINDOW_DAYS),
    db: AsyncSession = Depends(get_db),
) -> HealthSummaryResponse:
    """
    Шаги, минуты тренировки, пульс покоя и приём добавок за `days` прошедших
    суток против такого же числа суток до них.

    Сегодняшний день не входит: он ещё проживается. Сна в каталоге пока нет, и
    фигура `sleep` приходит с `available=false`. Ничего не пишет.
    """
    return await advice_crud.build_health_summary(db, days, today_local())


@router.post("", response_model=HealthAdviceResponse)
async def write_advice(
    payload: HealthAdviceRequest,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm_client),
) -> HealthAdviceResponse:
    """
    Совет по сводке: слой orchestration получает те же цифры, что видит
    `GET /health-advice/summary`.

    Запускается по запросу и не сохраняется. Текст не ставит диагнозов, не
    назначает доз и заканчивается оговоркой «не медицинская рекомендация».
    Данных мало — 422, и модель не вызывается. Бэкенд LLM недоступен — 503,
    сбой модели — 502. Ни названия добавок, ни значения здоровья, ни текст
    совета в лог не пишутся.
    """
    summary = await advice_crud.build_health_summary(db, payload.days, today_local())
    if not summary.enough_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Данных мало: совет по здоровью появится, когда накопится хотя бы "
                "несколько дней шагов, тренировок, пульса или приёма добавок."
            ),
        )
    if llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Совет от ИИ выключен: нет бэкенда модели "
                "(задай ANTHROPIC_API_KEY или поставь claude CLI)."
            ),
        )
    try:
        text = await write_health_advice(llm, summary)
    except LLMError as error:
        logger.warning("health advice LLM backend failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Модель не ответила."
        ) from error
    return HealthAdviceResponse(
        text=text,
        model=llm.model,
        starts_on=summary.window.starts_on,
        ends_on=summary.window.ends_on,
        days=summary.window.days,
    )
