# [review:need-review] PHASE-03/296
# summary: GET /dashboard/summary?period=week|month — one read-only answer for the whole dashboard, the window cut on the day of the server
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.core.database import get_db
from app.crud import dashboard_summary as summary_crud
from app.schemas.dashboard_summary import DashboardSummaryResponse, Period

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    period: Period = Query("week", description="Окно: последние 7 или 30 дней"),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """
    Сводка дашборда одним запросом: кольца, серии, здоровье, лучшие показатели,
    тренировки и инсайт.

    Окно кончается «сегодня» по границе суток сервера, а не по UTC и не по часам
    клиента. Блок без данных приходит `null` или пустым списком, не нулём.
    Формулы колец — в docstring схемы и в `docs/PHASE-03/design/296-dashboard-summary.md`.
    """
    return await summary_crud.build_dashboard_summary(db, period, today_local())
