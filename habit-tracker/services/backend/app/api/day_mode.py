# [review:need-review] PHASE-03/162
# summary: the day mode as an API — GET/PUT/DELETE /day-mode/{date} (a manual decision overrides the schedule for that date only; DELETE gives the date back to the schedule) and GET/PUT /mode-schedule (the whole week at once)
"""
HTTP surface of the day mode: what kind of day it is, who said so, and how to change it.

`GET /agent/day-mode/{date}` stays where the agent's own routes live; this module
is the one the web and the floating window write through. Both resolve through
`app.crud.activity.day_mode`, so the answer on screen and the minutes the role
markup counts come from one rule.
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import activity as activity_crud
from app.crud import day_mode as day_mode_crud
from app.schemas.day_mode import (
    DayModeIn,
    DayModeResponse,
    ModeScheduleDay,
    ModeScheduleWeek,
)

router = APIRouter(tags=["day-mode"])


async def _answer(db: AsyncSession, on: date_type) -> DayModeResponse:
    mode = await activity_crud.day_mode(db, on)
    return DayModeResponse(
        date=on, kind=mode.kind, nocode=mode.nocode, source=mode.source
    )


async def _week(db: AsyncSession) -> ModeScheduleWeek:
    rows = await day_mode_crud.list_schedule(db)
    return ModeScheduleWeek(
        days=[
            ModeScheduleDay(weekday=r.weekday, kind=r.kind, nocode=r.nocode)
            for r in rows
        ]
    )


@router.get("/day-mode/{on}", response_model=DayModeResponse)
async def get_day_mode(
    on: date_type, db: AsyncSession = Depends(get_db)
) -> DayModeResponse:
    """Режим дня: решение человека, если оно есть, иначе строка расписания."""
    return await _answer(db, on)


@router.put("/day-mode/{on}", response_model=DayModeResponse)
async def put_day_mode(
    on: date_type, decision: DayModeIn, db: AsyncSession = Depends(get_db)
) -> DayModeResponse:
    """
    Решить режим одного дня вручную.

    Строка перебивает расписание на эту дату и ни на какую другую — как
    `override=YYYY-MM-DD:on|off` в файле, который эта ручка заменяет.
    """
    await day_mode_crud.set_manual_mode(db, on, decision)
    await db.commit()
    return await _answer(db, on)


@router.delete("/day-mode/{on}", response_model=DayModeResponse)
async def delete_day_mode(
    on: date_type, db: AsyncSession = Depends(get_db)
) -> DayModeResponse:
    """Вернуть день расписанию; отвечает режимом, в который он вернулся."""
    await day_mode_crud.clear_manual_mode(db, on)
    await db.commit()
    return await _answer(db, on)


@router.get("/mode-schedule", response_model=ModeScheduleWeek)
async def get_mode_schedule(db: AsyncSession = Depends(get_db)) -> ModeScheduleWeek:
    """Неделя по умолчанию: 0 — воскресенье … 6 — суббота."""
    return await _week(db)


@router.put("/mode-schedule", response_model=ModeScheduleWeek)
async def put_mode_schedule(
    schedule: ModeScheduleWeek, db: AsyncSession = Depends(get_db)
) -> ModeScheduleWeek:
    """
    Заменить расписание целиком.

    Меняет режим будущих дней без решения. Дни, где человек решил вручную, лежат
    в `day_mode` и этой ручкой не затрагиваются.
    """
    await day_mode_crud.replace_schedule(db, schedule)
    await db.commit()
    return await _week(db)
