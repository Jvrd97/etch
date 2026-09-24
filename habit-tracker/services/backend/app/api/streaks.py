# [review:need-review] PHASE-01/174
# summary: bulk avoid/build streak endpoint returns every selected category from one history query
"""Bulk read API for category streaks."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import streak as streak_crud
from app.schemas import StreakResponse
from app.schemas.category import CategoryStreakMode

router = APIRouter(prefix="/streaks", tags=["streaks"])


@router.get("", response_model=list[StreakResponse])
async def get_category_streaks(
    streak_mode: CategoryStreakMode = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[StreakResponse]:
    """Return the selected mode's streaks without one request per category."""
    stats = await streak_crud.get_category_streaks(db, streak_mode)
    return [
        StreakResponse(
            category_id=category_id,
            streak_mode=streak_mode,
            current_streak=category_stats.current_streak,
            best_streak=category_stats.best_streak,
            last_relapse_date=category_stats.last_relapse_date,
        )
        for category_id, category_stats in stats
    ]
