# [review:need-review] PHASE-01/52-text-to-category-plan
# summary: POST /onboarding/draft — transcript -> validated additive-only plan; 503 no backend, 502 on double failure
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import category as category_crud
from app.llm.client import LLMClient, LLMError, resolve_llm_client
from app.llm.onboarding import OnboardingPlanError, generate_onboarding_plan
from app.schemas.onboarding import OnboardingDraftRequest, OnboardingPlan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def get_llm_client() -> LLMClient | None:
    """
    LLM client dependency; None when no backend is available.

    Tests override this dependency to mock at the app/llm boundary.
    """
    return resolve_llm_client()


@router.post("/draft", response_model=OnboardingPlan)
async def draft_plan(
    payload: OnboardingDraftRequest,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm_client),
) -> OnboardingPlan:
    """
    Построить additive-only план категорий из свободного текста.

    План не персистится — это предпросмотр того, что будет создано. Существующие
    категории подаются модели, чтобы она дополняла систему, а не дублировала её;
    конфликты имён помечаются флагом прямо в ответе.

    Бэкенд LLM недоступен -> 503. Сбой самого бэкенда (таймаут, ошибка API/CLI)
    или двойной провал парсинга/валидации -> 502.
    """
    if llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Onboarding is disabled: no LLM backend available "
                "(set ANTHROPIC_API_KEY or install the claude CLI)"
            ),
        )

    categories = await category_crud.get_categories(db, limit=None, active_only=True)

    try:
        return await generate_onboarding_plan(llm, categories, payload.transcript)
    except LLMError as exc:
        # Backend itself failed (timeout, API/CLI error) — same 502 the insights
        # endpoint returns, rather than leaking a 500. The message is the
        # exception class only, never request content.
        logger.warning("onboarding LLM backend failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM request failed",
        ) from exc
    except OnboardingPlanError as exc:
        # Neither the transcript nor the validation-error text is logged:
        # both can echo user content. Only the failure kind is recorded.
        logger.warning("onboarding plan generation failed after repair pass")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Onboarding plan generation failed",
        ) from exc
