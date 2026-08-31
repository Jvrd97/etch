# [review:need-review] PHASE-03/135
# summary: the agent's HTTP surface — POST /agent/activity takes a batch of intervals (capped at 500, 422 naming the bundle the catalogue does not carry) and runs the role markup for every day it touched so the roles screen does not wait for a manual run, GET /agent/activity/{date} rolls the day up per application, and GET /agent/day-mode/{date} says which kind of day it is and who decided
"""
HTTP surface of the macOS agent.

Two decisions shape this module.

**Пачка либо принята целиком, либо отвергнута целиком.** An unknown bundle is a
422 that names it, and nothing from that batch is written — the catalogue is also
the list of whose window titles may ever be kept, and letting a data stream widen
it would widen what the system is allowed to remember.

**Разметка идёт сразу за приёмом.** `#135` exists so that `/roles` shows where
the day went with no manual action at all; a markup that had to be triggered by
hand would be a markup nobody triggers. The same run is available on its own as
`POST /roles/classify` for the case «поправил правило — переразметь неделю».

Ни одного заголовка окна в логах этого модуля нет и быть не может: заголовки
проходят через схему и `crud`, а печатается здесь только счётчик.
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import activity as activity_crud
from app.models.activity import ActivityInterval
from app.roles import classify
from app.schemas.activity import (
    ActivityAppSlice,
    ActivityBatchIn,
    ActivityBatchResponse,
    ActivityDayResponse,
    ActivityIntervalResponse,
    DayModeResponse,
)

router = APIRouter(prefix="/agent", tags=["agent"])

SECONDS_PER_MINUTE = 60

# What a roll-up calls the time of an interval that names no application: a
# manual record has a note, not a bundle, and «—» on a screen is worse than a word.
MANUAL_APP_NAME = "вручную"


def _interval_dto(
    interval: ActivityInterval, bundles: dict[int, str], names: dict[int, str]
) -> ActivityIntervalResponse:
    return ActivityIntervalResponse(
        id=interval.id,
        source=interval.source,
        app_id=interval.app_id,
        bundle_id=bundles.get(interval.app_id) if interval.app_id else None,
        app_name=names.get(interval.app_id) if interval.app_id else None,
        started_at=interval.started_at,
        ended_at=interval.ended_at,
        duration_seconds=interval.duration_seconds,
        local_date=interval.local_date,
        title_source=interval.title_source,
        idle_seconds=interval.idle_seconds,
        switch_count=interval.switch_count,
        is_corrected=interval.is_corrected,
        note=interval.note,
    )


@router.post(
    "/activity",
    response_model=ActivityBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_activity(
    batch: ActivityBatchIn, db: AsyncSession = Depends(get_db)
) -> ActivityBatchResponse:
    """
    Принять пачку интервалов и сразу разметить дни, которых она коснулась.

    Идемпотентность даёт естественный ключ `(source, started_at, app_id)`:
    повторно присланная после обрыва пачка ложится на те же строки и ничего не
    удваивает, поэтому `Idempotency-Key` этому потоку не нужен.

    422 — приложение, которого нет в каталоге `tracked_app`; в теле его
    `bundle_id`. Ни одной строки от такой пачки в базе не остаётся: каталог
    пополняется решением человека, а не потоком данных.
    """
    try:
        written = await activity_crud.upsert_intervals(
            db,
            [
                activity_crud.IntervalDraft(
                    bundle_id=item.bundle_id,
                    started_at=item.started_at,
                    ended_at=item.ended_at,
                    local_date=item.local_date,
                    utc_offset_minutes=item.utc_offset_minutes,
                    title=item.title,
                    title_source=item.title_source,
                    idle_seconds=item.idle_seconds,
                    switch_count=item.switch_count,
                    source=item.source,
                    note=item.note,
                )
                for item in batch.intervals
            ],
        )
    except activity_crud.UnknownApp as unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Приложения {unknown.bundle_id} нет в каталоге tracked_app. "
                "Заведите его — каталог пополняется решением, а не потоком данных."
            ),
        ) from unknown

    # Which days the batch touched is the server's answer, not the client's:
    # `local_date()` is the single reading of «которому дню принадлежит момент»,
    # and an interval that crosses the boundary touches two days, not one.
    days = sorted(
        {day for interval in written for day in classify.touched_days(interval)}
    )
    for day in days:
        await classify.classify_day(db, day)
    await db.commit()
    return ActivityBatchResponse(
        intervals_written=len(written), classified_days=len(days)
    )


@router.get("/activity/{work_day}", response_model=ActivityDayResponse)
async def get_activity(
    work_day: date_type, db: AsyncSession = Depends(get_db)
) -> ActivityDayResponse:
    """
    Где прошёл день: свёртка по приложениям плюс интервалы, из которых она вышла.

    День считается по границе суток сервера, не по колонке `local_date`, которую
    заполнил клиент: единственный ответ на «какое это число» живёт в
    `app.core.daytime`.
    """
    intervals = await activity_crud.day_intervals(db, work_day)
    mode = await activity_crud.day_mode(db, work_day)
    apps = await activity_crud.list_apps(db)
    bundles = {app.id: app.bundle_id for app in apps}
    names = {app.id: app.display_name for app in apps}

    seconds: dict[int | None, int] = {}
    for interval in intervals:
        seconds[interval.app_id] = (
            seconds.get(interval.app_id, 0) + interval.duration_seconds
        )

    slices = [
        ActivityAppSlice(
            app_id=app_id,
            bundle_id=bundles.get(app_id) if app_id else None,
            app_name=names.get(app_id, MANUAL_APP_NAME) if app_id else MANUAL_APP_NAME,
            minutes=total // SECONDS_PER_MINUTE,
        )
        for app_id, total in seconds.items()
    ]
    slices.sort(key=lambda row: (-row.minutes, row.app_name))

    return ActivityDayResponse(
        work_day=work_day,
        mode=mode.kind,
        total_minutes=sum(row.minutes for row in slices),
        apps=slices,
        intervals=[_interval_dto(row, bundles, names) for row in intervals],
    )


@router.get("/day-mode/{on}", response_model=DayModeResponse)
async def get_day_mode(
    on: date_type, db: AsyncSession = Depends(get_db)
) -> DayModeResponse:
    """
    Режим дня: решение человека, если оно есть, иначе строка расписания.

    `source` — часть ответа, а не служебное поле: «выходной по расписанию» и
    «выходной, потому что человек так решил» — один и тот же день и два разных
    факта, и разметка минут читает именно `kind`, а показывает экран оба.
    """
    mode = await activity_crud.day_mode(db, on)
    return DayModeResponse(
        date=on, kind=mode.kind, nocode=mode.nocode, source=mode.source
    )
