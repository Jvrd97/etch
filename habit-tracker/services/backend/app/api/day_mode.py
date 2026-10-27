# [review:need-review] PHASE-03/228
# summary: the day mode as an API — GET /day-mode answers for the server's current day, GET/PUT/DELETE /day-mode/{date} (a manual decision overrides the schedule for that date only; DELETE gives the date back to the schedule; dates outside 2000..2100 are 422) and GET/PUT /mode-schedule (the whole week at once; resolved on the fly, so an edit moves every past or future day without a decision)
"""
HTTP surface of the day mode: what kind of day it is, who said so, and how to change it.

`GET /agent/day-mode/{date}` stays where the agent's own routes live; this module
is the one the web and the floating window write through. Both resolve through
`app.crud.activity.day_mode`, so the answer on screen and the minutes the role
markup counts come from one rule.
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.core.database import get_db
from app.crud import activity as activity_crud
from app.crud import day_mode as day_mode_crud
from app.schemas.day_mode import (
    DAY_MODE_MAX_DATE,
    DAY_MODE_MIN_DATE,
    DayModeIn,
    DayModeResponse,
    ModeScheduleDay,
    ModeScheduleWeek,
)

router = APIRouter(tags=["day-mode"])


def _calendar_day(on: date_type) -> date_type:
    """The `{on}` of the path, refused when it is outside the calendar of the app."""
    if not DAY_MODE_MIN_DATE <= on <= DAY_MODE_MAX_DATE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Дата вне календаря приложения: "
                f"{DAY_MODE_MIN_DATE.isoformat()}..{DAY_MODE_MAX_DATE.isoformat()}."
            ),
        )
    return on


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


@router.get("/day-mode", response_model=DayModeResponse)
async def get_current_day_mode(db: AsyncSession = Depends(get_db)) -> DayModeResponse:
    """
    Режим текущего дня сервера.

    Какой день идёт, знает сервер (`today_local()`): браузер между полуночью и
    часом границы считает другую дату. Ответ несёт `date`, и экран пишет решение
    на неё, а не на свою.
    """
    return await _answer(db, today_local())


@router.get("/day-mode/{on}", response_model=DayModeResponse)
async def get_day_mode(
    on: date_type = Depends(_calendar_day), db: AsyncSession = Depends(get_db)
) -> DayModeResponse:
    """Режим дня: решение человека, если оно есть, иначе строка расписания."""
    return await _answer(db, on)


@router.put("/day-mode/{on}", response_model=DayModeResponse)
async def put_day_mode(
    decision: DayModeIn,
    on: date_type = Depends(_calendar_day),
    db: AsyncSession = Depends(get_db),
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
    on: date_type = Depends(_calendar_day), db: AsyncSession = Depends(get_db)
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

    Режим дня без решения считается из расписания на лету: правка меняет все
    такие дни, будущие и прошлые. Дни, где человек решил вручную, лежат в
    `day_mode` и этой ручкой не затрагиваются.
    """
    await day_mode_crud.replace_schedule(db, schedule)
    await db.commit()
    return await _week(db)
