# [review:need-review] PHASE-03/166
# summary: what the closing of the day reads from the measured time — minutes per task of the day (union of ranges), tasks ticked done with no interval and no commit behind them, untasked intervals of half an hour or more, and the share of untasked intervals over the last thirty days with the number of days actually observed
"""
The measured time read against the plan of one day.

Four questions, each one query, none of them per task: the statement count of
`task_time_report` does not move with the size of the plan (a test holds it).

**Задача дня — это пункт плана (`plan_item.id`).** `activity_interval.plan_item_id`
carries the foreign key `ON DELETE SET NULL` since `#159`, so the tie asked for in
`#166` is that one: deleting a task never takes the hour that was worked on it.
`plan_task_id` is the older numeric column and stays only for what wrote it.

**«Сделано без следов» — это три нуля сразу:** a `done` mark, no interval naming
the item, and no commit. The server does not see git, so commits arrive from the
caller as the ids it found commits for; `commits_checked` says whether it looked
at all, because «нет коммитов» and «коммиты не проверяли» must not read alike.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Select, and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import day_bounds, local_date
from app.crud import activity as activity_crud
from app.day.skeleton import KIND_TASK
from app.models.activity import ActivityInterval
from app.models.mark import MARK_DONE, PlanMark
from app.models.plan import DayPlan, PlanItem, PlanSection

SECONDS_PER_MINUTE = 60

# What a roll-up calls the time of an interval that names no application: a
# manual record has a note, not a bundle, and «—» on a screen is worse than a word.
MANUAL_APP_NAME = "вручную"

# An untasked stretch this long is work outside the plan worth showing in the
# same hour; shorter ones are the noise of a day and only feed the share.
LONG_UNTASKED_SECONDS = 30 * 60

# The window the decision of `#166` is reviewed over: the share of intervals that
# name no task, over this many days. Under half is «привязка работает».
UNTASKED_WINDOW_DAYS = 30

_NO_LINK = and_(
    ActivityInterval.plan_task_id.is_(None),
    ActivityInterval.plan_item_id.is_(None),
    ActivityInterval.clickup_task_id.is_(None),
)


@dataclass(frozen=True)
class TaskMinutes:
    """Minutes on one task of the day, the union of the intervals naming it."""

    plan_item_id: uuid.UUID
    title: str
    minutes: int


@dataclass(frozen=True)
class TracelessTask:
    """A task ticked done with nothing behind the tick."""

    plan_item_id: uuid.UUID
    title: str


@dataclass(frozen=True)
class LongUntasked:
    """One stretch of work outside the plan, with the application's name resolved."""

    interval_id: int
    started_at: datetime
    ended_at: datetime
    minutes: int
    app_name: str


@dataclass(frozen=True)
class UntaskedShare:
    """
    Intervals that name no task, over the last `window_days` days.

    `observed_days` is how far back the data really goes inside the window: a
    share over three days of history is a three-day number, and the screen has to
    be able to say so instead of calling it monthly.
    """

    window_days: int
    observed_days: int
    intervals: int
    untasked: int

    @property
    def share(self) -> float | None:
        return self.untasked / self.intervals if self.intervals else None


@dataclass(frozen=True)
class TaskTimeReport:
    tasks: list[TaskMinutes]
    untasked_seconds: int
    long_untasked: list[LongUntasked]
    done_without_traces: list[TracelessTask]
    untasked_share: UntaskedShare


def _day_task_items(on: date) -> Select[tuple[uuid.UUID, str]]:
    return (
        select(PlanItem.id, PlanItem.text_plain)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanItem.kind == KIND_TASK)
        .order_by(PlanSection.ord, PlanItem.ord)
    )


async def _titles(db: AsyncSession, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(PlanItem.id, PlanItem.text_plain).where(PlanItem.id.in_(item_ids))
    )
    return {row.id: row.text_plain for row in rows}


async def _done_without_traces(
    db: AsyncSession, on: date, committed: set[uuid.UUID]
) -> list[TracelessTask]:
    has_interval = exists().where(ActivityInterval.plan_item_id == PlanItem.id)
    rows = await db.execute(
        _day_task_items(on)
        .join(PlanMark, PlanMark.item_id == PlanItem.id)
        .where(PlanMark.state == MARK_DONE, ~has_interval)
    )
    return [
        TracelessTask(plan_item_id=row.id, title=row.text_plain)
        for row in rows
        if row.id not in committed
    ]


async def _long_untasked(db: AsyncSession, on: date) -> list[LongUntasked]:
    start, end = day_bounds(on)
    names = await activity_crud.app_names(db)
    rows = await db.execute(
        select(ActivityInterval)
        .where(
            ActivityInterval.started_at >= start,
            ActivityInterval.started_at < end,
            _NO_LINK,
            ActivityInterval.duration_seconds >= LONG_UNTASKED_SECONDS,
        )
        .order_by(ActivityInterval.started_at, ActivityInterval.id)
    )
    return [
        LongUntasked(
            interval_id=row.id,
            started_at=row.started_at,
            ended_at=row.ended_at,
            minutes=row.duration_seconds // SECONDS_PER_MINUTE,
            app_name=names.get(row.app_id, MANUAL_APP_NAME)
            if row.app_id
            else MANUAL_APP_NAME,
        )
        for row in rows.scalars()
    ]


async def untasked_share(db: AsyncSession, today: date) -> UntaskedShare:
    """The share of untasked intervals in the window ending on `today`."""
    first_day = today - timedelta(days=UNTASKED_WINDOW_DAYS - 1)
    window_start = day_bounds(first_day)[0]
    window_end = day_bounds(today)[1]
    row = (
        await db.execute(
            select(
                func.count(),
                func.sum(case((_NO_LINK, 1), else_=0)),
                func.min(ActivityInterval.started_at),
            ).where(
                ActivityInterval.started_at >= window_start,
                ActivityInterval.started_at < window_end,
            )
        )
    ).one()
    total, untasked, earliest = row
    observed = _observed_days(earliest, today)
    return UntaskedShare(
        window_days=UNTASKED_WINDOW_DAYS,
        observed_days=observed,
        intervals=int(total),
        untasked=int(untasked or 0),
    )


def _observed_days(earliest: datetime | None, today: date) -> int:
    if earliest is None:
        return 0
    return (today - local_date(earliest)).days + 1


async def task_time_report(
    db: AsyncSession, on: date, today: date, committed: set[uuid.UUID]
) -> TaskTimeReport:
    """Everything the day's closing needs about measured time, in a fixed number of queries."""
    tasks, untasked_seconds = await activity_crud.task_time_seconds(db, on)
    linked = [(row.plan_item_id, row.seconds) for row in tasks if row.plan_item_id]
    titles = await _titles(db, {item_id for item_id, _ in linked})
    return TaskTimeReport(
        tasks=[
            TaskMinutes(
                plan_item_id=item_id,
                title=titles.get(item_id, ""),
                minutes=seconds // SECONDS_PER_MINUTE,
            )
            for item_id, seconds in linked
        ],
        untasked_seconds=untasked_seconds,
        long_untasked=await _long_untasked(db, on),
        done_without_traces=await _done_without_traces(db, on, committed),
        untasked_share=await untasked_share(db, today),
    )
