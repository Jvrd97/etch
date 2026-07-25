# [review:need-review] PHASE-01/52-text-to-category-plan
# summary: insight framing (system prompt) moved here after LLM client went neutral
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import insight as insight_crud
from app.llm.client import InsightsClient, LLMError, resolve_insights_client
from app.llm.context import build_period_context
from app.llm.prompts import INSIGHTS_SYSTEM_PROMPT
from app.models import AIReport
from app.schemas import InsightListItem, InsightRequest, InsightResponse
from app.schemas.insight import PREVIEW_MAX_CHARS

router = APIRouter(prefix="/insights", tags=["insights"])


def get_llm_client() -> InsightsClient | None:
    """
    LLM client dependency; None when no backend is available.

    Tests override this dependency to mock at the app/llm boundary.
    """
    return resolve_insights_client()


@router.get("", response_model=list[InsightListItem])
async def list_insights(db: AsyncSession = Depends(get_db)) -> list[InsightListItem]:
    """История AI-отчётов, новые сверху; content обрезан до превью."""
    reports = await insight_crud.list_ai_reports(db)
    return [
        InsightListItem(
            id=report.id,
            period_days=report.period_days,
            model=report.model,
            created_at=report.created_at,
            preview=report.content[:PREVIEW_MAX_CHARS],
        )
        for report in reports
    ]


@router.get("/{report_id}", response_model=InsightResponse)
async def get_insight(report_id: int, db: AsyncSession = Depends(get_db)) -> AIReport:
    """Полный AI-отчёт по id; 404, если отчёта нет."""
    report = await insight_crud.get_ai_report(db, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI report {report_id} not found",
        )
    return report


@router.post("", response_model=InsightResponse, status_code=status.HTTP_201_CREATED)
async def create_insight(
    payload: InsightRequest | None = None,
    db: AsyncSession = Depends(get_db),
    llm: InsightsClient | None = Depends(get_llm_client),
) -> AIReport:
    """
    Сгенерировать AI-разбор периода и сохранить отчёт.

    - **period_days**: длина периода в днях (по умолчанию 30)

    Синхронный вызов LLM с щедрым таймаутом. Бэкенд выбирается через
    LLM_BACKEND (cli | api | auto); если ни один недоступен — 503;
    при ошибке LLM — 502 (отчёт в этом случае не сохраняется).
    """
    if llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI insights are disabled: no LLM backend available "
                "(set ANTHROPIC_API_KEY or install the claude CLI)"
            ),
        )

    request = payload if payload is not None else InsightRequest()
    context = await build_period_context(db, period_days=request.period_days)
    # The client is now neutral (prompt in, text out): the insight framing
    # lives here, not in the backend.
    prompt = f"{INSIGHTS_SYSTEM_PROMPT}\n\n{context}"

    try:
        content = await llm.generate(prompt)
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM request failed",
        ) from exc

    return await insight_crud.create_ai_report(
        db,
        period_days=request.period_days,
        content=content,
        model=llm.model,
    )
