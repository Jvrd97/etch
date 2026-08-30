# [review:need-review] PHASE-03/91
# summary: persistence of work intervals — the day of an interval asked of `local_date()` and never computed here, the sum a day answers with, and the edit that turns an agent's row into `corrected` while keeping what the agent proposed
"""
Database access for the intervals a day of work is made of.

Three decisions carry the module.

**Какому дню принадлежит интервал, этот модуль не решает.** It asks
`app.core.daytime.local_date(started_at)` and stores the answer. There is no
arithmetic of the boundary here on purpose: a second one would put an interval
started at 00:30 into one day and a water mark of the same moment into another,
which is precisely the defect the single function exists to remove. A `grep` of
this file finds neither of the two columns the boundary is made of.

**Правка агентского интервала не затирает предложение.** The first edit of a
row the agent wrote copies its boundaries into `auto_started_at`/`auto_ended_at`,
flips `source` to `corrected` and stamps `edited_at`. A second edit moves the
boundaries again and leaves the proposal where it is: what the agent proposed is
one value, not a running history, and the history of edits is not what the
screen is asking for.

**Сумма считается чистой функцией.** `app.day.work.day_work_minutes` is where
the minutes are decided, including the two rules worth testing without postgres:
an empty day answers `None` rather than zero, and an open interval counts up to
now but never past the end of its day.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date, now_utc
from app.day.work import (
    SOURCE_AGENT,
    SOURCE_CORRECTED,
    IntervalSpan,
    day_work_minutes,
    span_minutes,
)
from app.models.work_interval import WorkInterval
from app.schemas.work_interval import (
    WorkDayResponse,
    WorkIntervalIn,
    WorkIntervalPatch,
    WorkIntervalResponse,
)

__all__ = [
    "IntervalNotOnDay",
    "create",
    "day_response",
    "delete",
    "get",
    "list_for_day",
    "minutes_by_day",
    "minutes_for_day",
    "to_response",
    "update",
]


class IntervalNotOnDay(ValueError):
    """
    The interval's start does not belong to the day it was addressed to.

    Raised rather than silently filed elsewhere: an interval written under
    `/day/2026-08-24` and stored on the 25th would be invisible on the page that
    created it, and the reader would conclude the save failed.
    """


def _span(row: WorkInterval) -> IntervalSpan:
    """The row reduced to what its length depends on."""
    return IntervalSpan(started_at=row.started_at, ended_at=row.ended_at, mode=row.mode)


async def list_for_day(db: AsyncSession, on: date) -> list[WorkInterval]:
    """Every interval of `on`, in the order they were lived."""
    result = await db.execute(
        select(WorkInterval)
        .where(WorkInterval.day_date == on)
        .order_by(WorkInterval.started_at)
    )
    return list(result.scalars().all())


async def get(db: AsyncSession, on: date, interval_id: UUID) -> WorkInterval | None:
    """
    One interval of `on`, or None.

    Addressed as "this interval of this day" — an id from another day does not
    resolve here, the same way a mark is addressed as «эта строка этого дня».
    """
    result = await db.execute(
        select(WorkInterval).where(
            WorkInterval.id == interval_id, WorkInterval.day_date == on
        )
    )
    return result.scalar_one_or_none()


def to_response(row: WorkInterval) -> WorkIntervalResponse:
    """One stored interval as the wire carries it, with its length filled in."""
    return WorkIntervalResponse(
        id=row.id,
        day_date=row.day_date,
        started_at=row.started_at,
        ended_at=row.ended_at,
        running=row.ended_at is None,
        minutes=span_minutes(_span(row), row.day_date),
        source=row.source,
        mode=row.mode,
        auto_started_at=row.auto_started_at,
        auto_ended_at=row.auto_ended_at,
        app_bundle_id=row.app_bundle_id,
        note=row.note,
        edited_at=row.edited_at,
    )


def minutes_of(rows: Sequence[WorkInterval], on: date) -> int | None:
    """The minutes `rows` add up to on `on`; None when there are no rows."""
    return day_work_minutes([_span(row) for row in rows], on)


async def minutes_for_day(db: AsyncSession, on: date) -> int | None:
    """
    How many minutes of work `on` holds, or None when nothing was recorded.

    None is the answer the verdict needs: it skips the overtime check and puts
    `work_minutes` into `missing_data`, instead of reading an unmeasured day as
    a short one.
    """
    return minutes_of(await list_for_day(db, on), on)


async def minutes_by_day(db: AsyncSession) -> dict[date, int]:
    """
    The measured minutes of every day that has any, keyed by date.

    One read for the whole history, because `recompute_history` walks every
    closed day and asking per day would turn a recompute into a query per row.
    The grouping is done here rather than in SQL: an open interval's length
    depends on the moment it is asked about and on where its day ends, and
    neither is knowable to a `SUM()`.
    """
    result = await db.execute(select(WorkInterval).order_by(WorkInterval.day_date))
    by_day: dict[date, list[WorkInterval]] = {}
    for row in result.scalars().all():
        by_day.setdefault(row.day_date, []).append(row)
    minutes: dict[date, int] = {}
    for on, rows in by_day.items():
        total = minutes_of(rows, on)
        if total is not None:
            minutes[on] = total
    return minutes


async def day_response(db: AsyncSession, on: date) -> WorkDayResponse:
    """The work block of a day: its intervals, their sum and whether one runs."""
    rows = await list_for_day(db, on)
    return WorkDayResponse(
        day_date=on,
        intervals=[to_response(row) for row in rows],
        work_minutes=minutes_of(rows, on),
        running=any(row.ended_at is None for row in rows),
    )


async def create(db: AsyncSession, on: date, body: WorkIntervalIn) -> WorkInterval:
    """
    Store one interval on the day its start belongs to.

    The day comes from `local_date(started_at)`, and an interval whose start
    lands elsewhere is refused instead of being filed on another date. An
    interval from 23:00 to 01:00 therefore belongs whole to the day it began on:
    nothing here splits it, and nothing here decides where a day ends.
    """
    landed = local_date(body.started_at)
    if landed != on:
        raise IntervalNotOnDay(
            f"интервал с началом {body.started_at.isoformat()} принадлежит дню "
            f"{landed.isoformat()}, а не {on.isoformat()}: день интервала "
            "считается по его началу"
        )
    row = WorkInterval(
        day_date=landed,
        started_at=body.started_at,
        ended_at=body.ended_at,
        source=body.source,
        mode=body.mode,
        auto_started_at=body.auto_started_at,
        auto_ended_at=body.auto_ended_at,
        app_bundle_id=body.app_bundle_id,
        note=body.note,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


def _keep_what_the_agent_proposed(row: WorkInterval) -> None:
    """
    Move the agent's boundaries aside before a person overwrites them.

    Only on the first correction: `source` is already `corrected` afterwards, so
    the proposal stays the one value it is. A row a person typed themselves has
    no proposal to keep and stays `manual`.
    """
    if row.source != SOURCE_AGENT:
        return
    row.auto_started_at = row.started_at
    row.auto_ended_at = row.ended_at
    row.source = SOURCE_CORRECTED


async def update(
    db: AsyncSession, on: date, row: WorkInterval, patch: WorkIntervalPatch
) -> WorkInterval:
    """
    Apply an edit, keeping what the agent proposed and stamping the intervention.

    Only the fields the body actually named are touched — `ended_at: null` reopens
    a closed interval, an absent `ended_at` leaves it alone — so an edit of the
    note cannot silently reopen an interval that was finished hours ago.

    Moving the start moves the interval's day, and the day has to stay the one
    being edited: an interval that would land on another date is refused, for the
    same reason creating one there is.
    """
    named = patch.model_fields_set
    if not named:
        # A body that names nothing is not an intervention; stamping `edited_at`
        # for it would make «человек это смотрел» true of an empty request.
        return row
    _keep_what_the_agent_proposed(row)

    if "started_at" in named and patch.started_at is not None:
        landed = local_date(patch.started_at)
        if landed != on:
            raise IntervalNotOnDay(
                f"начало {patch.started_at.isoformat()} перенесло бы интервал в "
                f"день {landed.isoformat()}; правка не меняет день интервала"
            )
        row.started_at = patch.started_at
    if "ended_at" in named:
        row.ended_at = patch.ended_at
    if "mode" in named and patch.mode is not None:
        row.mode = patch.mode
    if "app_bundle_id" in named:
        row.app_bundle_id = patch.app_bundle_id
    if "note" in named:
        row.note = patch.note

    # Any edit is an intervention, including one that only rewrote the note: the
    # column answers «человек это смотрел», not «человек подвинул границы».
    row.edited_at = now_utc()
    await db.flush()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, row: WorkInterval) -> None:
    """Remove one interval; the day's sum is recomputed from what is left."""
    await db.delete(row)
    await db.flush()
