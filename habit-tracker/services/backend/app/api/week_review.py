# [review:need-review] PHASE-03/221, PHASE-03/244
# summary: GET /week-review[/{iso}] answers a whole week in one response (read-only, current week named by the day boundary) and POST /week-review/{iso}/narrative writes the AI text through the orchestration layer
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core.database import get_db
from app.core.daytime import today_local
from app.api.supplement_advice import DOSE_GUARD_DETAIL
from app.crud import week_review as review_crud
from app.day.week import BadWeekCode, iso_code
from app.llm.client import LLMClient, LLMError
from app.llm.health_advice import DoseGuardTripped
from app.llm.week_review import write_week_review
from app.schemas.week_review import WeekNarrativeResponse, WeekReviewResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/week-review", tags=["week-review"])


async def _review(db: AsyncSession, iso: str) -> WeekReviewResponse:
    """The review, with a code that names no week turned into a 404."""
    try:
        return await review_crud.build_week_review(db, iso, today_local())
    except BadWeekCode as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error


@router.get("", response_model=WeekReviewResponse)
async def get_current_week_review(
    db: AsyncSession = Depends(get_db),
) -> WeekReviewResponse:
    """
    Обзор текущей недели.

    «Текущая» считается границей суток сервера, а не календарём браузера: в ночь
    с воскресенья на понедельник до 04:00 это ещё прошлая неделя.
    """
    return await _review(db, iso_code(today_local()))


@router.get("/{iso}", response_model=WeekReviewResponse)
async def get_week_review(
    iso: str, db: AsyncSession = Depends(get_db)
) -> WeekReviewResponse:
    """
    Неделя `YYYY-Www` одним ответом: время по ролям и категориям, выполнение
    плана, серии привычек, итог против прошлой недели и цифры здоровья.

    Ничего не пишет. Неполная текущая неделя помечена `window.is_complete=false`
    и сравнивается с первыми днями прошлой недели в том же количестве.
    Код, не называющий неделю, — 404.
    """
    return await _review(db, iso)


@router.post("/{iso}/narrative", response_model=WeekNarrativeResponse)
async def write_week_narrative(
    iso: str,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm_client),
) -> WeekNarrativeResponse:
    """
    Текст итога недели от модели, по тем же цифрам, что в обзоре.

    Запускается по запросу, а не на каждое открытие экрана, и не сохраняется.
    Неделя без данных — 422: писать итог не о чем. Бэкенд LLM недоступен — 503,
    сбой модели — 502. Ни цифры, ни текст ответа в лог не пишутся.
    """
    review = await _review(db, iso)
    if not review_crud.week_has_data(review):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="В этой неделе нет данных для итога.",
        )
    if llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Итог недели от ИИ выключен: нет бэкенда модели "
                "(задай ANTHROPIC_API_KEY или поставь claude CLI)."
            ),
        )
    try:
        text = await write_week_review(llm, review)
    except DoseGuardTripped as error:
        logger.warning("dose guard tripped")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=DOSE_GUARD_DETAIL
        ) from error
    except LLMError as error:
        logger.warning("week narrative LLM backend failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Модель не ответила."
        ) from error
    return WeekNarrativeResponse(iso_code=iso, text=text, model=llm.model)
