# [review:need-review] PHASE-03/94, 309
# summary: #309 — a range of days reads the titles and the (kind, mark) of every item as plain columns, three statements whatever the length of the range, instead of the plan tree as ORM objects in selectinload batches
# summary: the week as a stored snapshot — recompute reads day_summary and writes only the counters and computed_at, the prose is replaced by a separate call, and a range of days is answered in the shape the old /api/days had, counted by the one function that counts tasks
"""
Database access for the week and for a range of days.

**Пересчёт трогает счётчики и `computed_at`, и больше ничего.**
`recompute_week` writes `won_days`, `total_days`, `streak_end` and the moment it
did so. `retro_md` and its three neighbours are never touched by it. That is the
whole reason the week is a stored row and not a `SELECT`: ретро утверждает то,
что было верно, когда его писали, and a day reopened in November must move the
numbers without silently rewriting the sentence beside them.

**Считает задачи одна функция.** The counters of `/days` come from
`app.day.marks.count_tasks`, the function `app.crud.mark.task_counts` wraps for
the header of the day screen and the verdict of `#90`. A `count(*)
FILTER (WHERE state = 'done')` in SQL would be the second definition of «skipped
выходит из знаменателя», and the first one to disagree with the verdict.

**Диапазон читается пачками, а не по дню.** Four queries answer any range: the
days, the plan titles, every item's kind with its mark, and the итоги. A loop
over `get_plan`/`list_marks` per date would be two round trips per square of a
timeline that draws a year at a time. The items come as columns, not as
`DayPlan → sections → items` objects: counting needs the id, the kind and the
state of a line, and the tree cost forty thousand ORM objects and a
`selectinload` batch per 500 sections on four years (#309).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.day.evaluate import VERDICT_WON
from app.day.marks import count_tasks
from app.day.week import week_bounds
from app.models.day import Day
from app.models.mark import PlanMark
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.models.summary import ORIGIN_NONE, DaySummary, verdict_origin
from app.models.week import Week, WeekReviewItem
from app.crud import day_profile as profile_crud
from app.day.debt import week_is_won
from app.schemas.week import (
    DayListItem,
    WeekIn,
    WeekResponse,
    WeekReviewItemResponse,
)

__all__ = [
    "get_week",
    "list_days",
    "recompute_week",
    "replace_week_text",
    "to_response",
]


async def list_days(db: AsyncSession, start: date, end: date) -> list[DayListItem]:
    """
    Every day of `[start, end]`, oldest first, in the shape `/api/days` had.

    A date with a `day` row but no plan and no итог still appears — as a title
    of `""` and a `verdict` of null. That is «день есть, никто его не закрыл»,
    and it is precisely the state the old timeline could not draw.
    """
    days = await db.execute(
        select(Day.day_date)
        .where(Day.day_date.between(start, end))
        .order_by(Day.day_date)
    )
    dates = list(days.scalars().all())
    if not dates:
        return []

    titles = await _titles_in_range(db, start, end)
    lines = await _lines_in_range(db, start, end)
    verdicts = await _verdicts_in_range(db, start, end)

    listed: list[DayListItem] = []
    for on in dates:
        kinds, states = lines.get(on, ({}, {}))
        counts = count_tasks(kinds, states)
        verdict, origin = verdicts.get(on, (None, ORIGIN_NONE))
        listed.append(
            DayListItem(
                date=on,
                title=titles.get(on) or "",
                verdict=verdict,
                verdict_origin=origin,
                done=counts.done,
                total=counts.planned,
            )
        )
    return listed


async def _titles_in_range(
    db: AsyncSession, start: date, end: date
) -> dict[date, str | None]:
    """The title of every plan of the range, by its day."""
    result = await db.execute(
        select(DayPlan.day_date, DayPlan.title).where(
            DayPlan.day_date.between(start, end)
        )
    )
    return {day_date: title for day_date, title in result.all()}


_Lines = tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]


async def _lines_in_range(
    db: AsyncSession, start: date, end: date
) -> dict[date, _Lines]:
    """
    Every item of every plan of the range as `count_tasks` reads it, by day.

    Per day: the kind of each item by its id, and the state of each marked item.
    The mark rides along by an outer join — one row per item, a line without a
    mark is pending.
    """
    result = await db.execute(
        select(DayPlan.day_date, PlanItem.id, PlanItem.kind, PlanMark.state)
        .join(PlanSection, PlanSection.plan_id == DayPlan.id)
        .join(PlanItem, PlanItem.section_id == PlanSection.id)
        .outerjoin(PlanMark, PlanMark.item_id == PlanItem.id)
        .where(DayPlan.day_date.between(start, end))
    )
    lines: dict[date, _Lines] = {}
    for day_date, item_id, kind, state in result.all():
        kinds, states = lines.setdefault(day_date, ({}, {}))
        kinds[item_id] = kind
        if state is not None:
            states[item_id] = state
    return lines


async def _verdicts_in_range(
    db: AsyncSession, start: date, end: date
) -> dict[date, tuple[str | None, str]]:
    """
    Вердикт каждого закрытого дня диапазона и его происхождение.

    Даты в ответе нет — день не закрыт. Происхождение едет рядом с вердиктом, а
    не считается на экране: «жёлтый квадрат, который никто не вычислял» — это
    факт строки, и таймлайн подписывает его, а не догадывается по источнику,
    которого у него нет.
    """
    result = await db.execute(
        select(DaySummary.day_date, DaySummary.verdict, DaySummary.source).where(
            DaySummary.day_date.between(start, end)
        )
    )
    return {
        row.day_date: (row.verdict, verdict_origin(row.source, row.verdict))
        for row in result
    }


async def get_week(db: AsyncSession, iso: str) -> Week | None:
    """
    The stored week, with its checklist loaded, or None when there is none.

    `populate_existing` because both writers here go around the ORM: the counters
    arrive by `INSERT … ON CONFLICT` and the checklist by a bulk `DELETE`, and an
    instance already in the identity map would otherwise answer with the numbers
    and the items it was loaded with — the read after a write would return the
    state before it.
    """
    result = await db.execute(
        select(Week)
        .where(Week.iso_code == iso)
        .options(selectinload(Week.review_items))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def recompute_week(db: AsyncSession, iso: str) -> Week:
    """
    Take the counters of the week `iso` again, creating the row if it is new.

    Writes four fields and no others: `won_days`, `total_days`, `streak_end` and
    `computed_at`. The prose stays exactly as it was — that is the difference
    between a snapshot with a date on it and a view that quietly rewrites what a
    person concluded in August.

    A week nobody has written about is created here rather than 404ing: the days
    of that week exist, they were won or lost, and «ретро не написано» is a fact
    about the week rather than an absence of one.
    """
    starts_on, ends_on = week_bounds(iso)
    total_days = await _count_days(db, starts_on, ends_on)
    won_days, streak_end = await _closed_days(db, starts_on, ends_on)
    now = datetime.now(timezone.utc)

    values = {
        "iso_code": iso,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "won_days": won_days,
        "total_days": total_days,
        "streak_end": streak_end,
        "computed_at": now,
    }
    statement = pg_insert(Week).values(**values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[Week.iso_code],
            set_={key: statement.excluded[key] for key in values if key != "iso_code"},
        )
    )
    await db.flush()

    week = await get_week(db, iso)
    if week is None:  # pragma: no cover - the upsert either lands or conflicts
        raise RuntimeError(
            f"week {iso} vanished between upsert and read; the row was deleted "
            "by a concurrent writer."
        )
    return week


async def _count_days(db: AsyncSession, starts_on: date, ends_on: date) -> int:
    """
    How many days of the week exist as rows — the denominator of «0 из 7».

    Counts `day`, not `day_summary`: a week whose Tuesday was never closed is
    «1 из 7», and counting only closed days would flatter every unfinished week
    into «1 из 1».
    """
    result = await db.execute(
        select(Day.day_date).where(Day.day_date.between(starts_on, ends_on))
    )
    return len(list(result.scalars().all()))


async def _closed_days(
    db: AsyncSession, starts_on: date, ends_on: date
) -> tuple[int, int | None]:
    """
    Won days of the week, and the streak after its last closed day.

    `streak_after` of the *latest* closed day rather than of Sunday: a week whose
    last two days were never closed still ended with the streak its Friday left,
    and reporting null for it would lose a number the person can read.
    """
    result = await db.execute(
        select(DaySummary.verdict, DaySummary.streak_after)
        .where(DaySummary.day_date.between(starts_on, ends_on))
        .order_by(DaySummary.day_date)
    )
    rows = list(result)
    won = sum(1 for row in rows if row.verdict == VERDICT_WON)
    streak_end = rows[-1].streak_after if rows else None
    return won, streak_end


async def replace_week_text(db: AsyncSession, iso: str, body: WeekIn) -> Week:
    """
    Replace what a person wrote about the week, then take the counters again.

    The checklist is replaced whole rather than patched line by line: the list is
    edited as a list — a question is answered, another moves to next week — and a
    per-line API would need ids the writer of a retro does not have.
    """
    week = await recompute_week(db, iso)
    week.retro_md = body.retro_md
    week.blockers_md = body.blockers_md
    week.mgmt_retro_md = body.mgmt_retro_md
    week.weekly_number_md = body.weekly_number_md
    await db.flush()

    await db.execute(delete(WeekReviewItem).where(WeekReviewItem.week_iso == iso))
    for ord_, item in enumerate(body.review_items, start=1):
        db.add(
            WeekReviewItem(
                id=uuid.uuid4(),
                week_iso=iso,
                ord=ord_,
                text_md=item.text_md,
                done=item.done,
            )
        )
    await db.flush()

    refreshed = await get_week(db, iso)
    if refreshed is None:  # pragma: no cover - written a few lines above
        raise RuntimeError(f"week {iso} vanished while its retro was being written.")
    return refreshed


async def week_debt(db: AsyncSession, week: Week) -> int:
    """
    Minutes of overtime this week still owes.

    Scoped to the week's own dates: a debt incurred in August must not keep every
    September week from ever being won. `#179` is about buying back the hours a
    raised ceiling let through, not about a permanent mark.
    """
    return await profile_crud.open_debt_minutes(db, week.starts_on, week.ends_on)


def to_response(week: Week, debt_minutes: int = 0) -> WeekResponse:
    """
    The week as the wire carries it.

    Written out field by field rather than by `from_attributes`: the checklist
    items carry their uuid as a string, and a DTO half-filled by reflection is
    the version that quietly drops a field on the next edit.
    """
    return WeekResponse(
        iso_code=week.iso_code,
        starts_on=week.starts_on,
        ends_on=week.ends_on,
        won_days=week.won_days,
        total_days=week.total_days,
        streak_end=week.streak_end,
        debt_minutes=debt_minutes,
        # Третье условие выигранной недели (`#179`): все дни выиграны, дни есть
        # и долг за переработку вернулся. Считается здесь, а не хранится: два из
        # трёх слагаемых меняются на каждом закрытии дня.
        is_won=week_is_won(week.won_days, week.total_days, debt_minutes),
        retro_md=week.retro_md,
        blockers_md=week.blockers_md,
        mgmt_retro_md=week.mgmt_retro_md,
        weekly_number_md=week.weekly_number_md,
        review_items=[
            WeekReviewItemResponse(
                id=str(item.id), ord=item.ord, text_md=item.text_md, done=item.done
            )
            for item in week.review_items
        ],
        computed_at=week.computed_at,
    )
