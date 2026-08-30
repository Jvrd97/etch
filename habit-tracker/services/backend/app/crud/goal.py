# [review:need-review] PHASE-03/93
# summary: database access for the goals — the whole board in one read (levels, milestones with their dependency edges, the goals of the current quarter), the set of ids a plan may point at, the status of one milestone, and the five goals of a quarter replaced as a set so the ceiling is checked by the database over the whole quarter at once
"""
Database access for the goals of `goal.md`.

**Квартал приезжает набором, но перезаписывается на месте.**
`PUT /goals/quarter/{quarter}` takes five goals and stores five goals, the same
idiom `replace_plan` uses for a day: the ceiling of five is a property of the
set, and a per-goal API would make it a question about the row being written,
which is never the one over the bar. What «замена» must not mean is
delete-and-insert — `quarter_goal.id` is what `plan_item.quarter_goal_id` and
`day_plan.quarter_goal_id` name, and both are `ondelete='RESTRICT'`. So the
write is an upsert keyed by `(quarter, ord)`, exactly as `app.imports.goal_md`
does it, and dropping a position a lived day still points at is refused by name
and by date instead of by a `ForeignKeyViolation`.

**Статус милстона переживает импорт.** Whether M2 is done is a fact a person
establishes; `goal.md` does not record it. So `set_milestone_status` is the only
writer of `status` and `done_on`, and the import (`app.imports.goal_md`) writes
neither.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import (
    MILESTONE_STATUS_DONE,
    QUARTER_GOAL_STATUSES,
    GoalLevel,
    Milestone,
    MilestoneDep,
    QuarterGoal,
)
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.schemas.goal import QuarterGoalIn

# Months per quarter — three, and the only reason the number is named is that
# `(month - 1) // 3` on its own reads as arithmetic rather than as a quarter.
MONTHS_PER_QUARTER = 3


def quarter_code(on: date) -> str:
    """
    The quarter `on` falls in, as `'2026-Q3'`.

    Sortable, and the shape `week.iso_code` already uses (`'2026-W35'`).
    `goal.md` writes it as «Q3 2026»; one function decides the spelling so the
    import, the API and the screen cannot each pick their own.
    """
    return f"{on.year}-Q{(on.month - 1) // MONTHS_PER_QUARTER + 1}"


async def existing_goal_ids(db: AsyncSession, ids: Iterable[int]) -> frozenset[int]:
    """
    Which of `ids` are goals of the quarter that exist.

    One query for the whole plan, asked by `app.crud.plan` before it writes a
    row. `app.day.plan_validate` gets the answer as a set: the rule lives there
    as a pure function, and reading the table is this layer's job.
    """
    wanted = set(ids)
    if not wanted:
        return frozenset()
    result = await db.execute(select(QuarterGoal.id).where(QuarterGoal.id.in_(wanted)))
    return frozenset(result.scalars().all())


async def list_levels(db: AsyncSession) -> list[GoalLevel]:
    """Levels 0 to 5, in the order `goal.md` writes them."""
    result = await db.execute(select(GoalLevel).order_by(GoalLevel.level))
    return list(result.scalars().all())


async def list_milestones(db: AsyncSession) -> list[Milestone]:
    """M1 to M10, in the order of the table they came from."""
    result = await db.execute(select(Milestone).order_by(Milestone.ord))
    return list(result.scalars().all())


async def dependencies(db: AsyncSession) -> dict[str, list[str]]:
    """
    Every edge of «Открывается чем», grouped by the milestone that waits.

    Read whole rather than per milestone: the screen draws all ten at once, and
    ten queries for a graph of a dozen edges is a loop nobody would write twice.
    """
    result = await db.execute(
        select(MilestoneDep.milestone_code, MilestoneDep.depends_on_code).order_by(
            MilestoneDep.milestone_code, MilestoneDep.depends_on_code
        )
    )
    edges: dict[str, list[str]] = {}
    for code, depends_on in result:
        edges.setdefault(code, []).append(depends_on)
    return edges


async def list_quarter_goals(db: AsyncSession, quarter: str) -> list[QuarterGoal]:
    """The goals of one quarter, in their numbered order."""
    result = await db.execute(
        select(QuarterGoal)
        .where(QuarterGoal.quarter == quarter)
        .order_by(QuarterGoal.ord)
    )
    return list(result.scalars().all())


async def get_milestone(db: AsyncSession, code: str) -> Milestone | None:
    """One milestone by its code, or None."""
    return await db.get(Milestone, code)


async def set_milestone_status(
    db: AsyncSession, milestone: Milestone, status: str, on: date
) -> Milestone:
    """
    Move a milestone to `status`, dating it when that status is "done".

    The date comes from the caller's day rather than from `now()`: the day runs
    from 04:00, and a milestone closed at half past midnight belongs to the day
    that is still running.

    Going back to any other status clears `done_on`. A milestone that is not
    done has no date of being done, and leaving the old one behind is how a
    board ends up showing a закрытый M9 that is also open.
    """
    milestone.status = status
    milestone.done_on = on if status == MILESTONE_STATUS_DONE else None
    await db.flush()
    return milestone


class QuarterGoalsRejected(ValueError):
    """
    A set the quarter cannot be written from, refused before anything is stored.

    Carries the sentence a person reads; the handle only chooses the status
    code. Two things are refused, and both are properties of the set rather than
    of one row: a position claimed twice, and a status outside the three the
    board draws. The database says the same two things
    (`uq_quarter_goal_quarter_ord`, `ck_quarter_goal_status`) — but it can no
    longer be the one to say the first, because an upsert keyed on that pair
    merges a duplicate instead of colliding with it. Which is the whole trade:
    the ids survive, so the ceiling gets stated one layer up.
    """


class QuarterGoalInUse(RuntimeError):
    """
    A goal the new set drops, that a lived day still points at.

    `plan_item.quarter_goal_id` and `day_plan.quarter_goal_id` are `RESTRICT` on
    purpose: a task that named a goal must not quietly become somebody else's
    urgency because the quarter was rewritten. The refusal names the goal and
    the days, so a reader knows what to unlink instead of decoding a constraint.
    """

    def __init__(self, goal: QuarterGoal, days: list[date]) -> None:
        self.goal_id = goal.id
        self.days = days
        listed = ", ".join(one.isoformat() for one in days)
        super().__init__(
            f"цель {goal.ord} квартала {goal.quarter} нельзя убрать: на неё "
            f"ссылается план дня — {listed}"
        )


def _check_set(goals: list[QuarterGoalIn]) -> None:
    """The rules of the whole set, checked before a single row is written."""
    ords = [one.ord for one in goals]
    taken_twice = sorted({one for one in ords if ords.count(one) > 1})
    if taken_twice:
        raise QuarterGoalsRejected(
            "цели квартала — не больше пяти, и место занимается один раз; "
            f"занято дважды: {', '.join(str(one) for one in taken_twice)}"
        )
    for one in goals:
        if one.status not in QUARTER_GOAL_STATUSES:
            raise QuarterGoalsRejected(
                f"статус «{one.status}» не из словаря целей квартала: "
                f"{', '.join(QUARTER_GOAL_STATUSES)}"
            )


async def _days_pointing_at(db: AsyncSession, goal_id: int) -> list[date]:
    """
    The dates whose plan names this goal — the whole day, or one of its tasks.

    Two reads rather than a `UNION`: the answer is a handful of dates for an
    error message, and the two queries have nothing in common beyond the column
    they end on.
    """
    whole_day = select(DayPlan.day_date).where(DayPlan.quarter_goal_id == goal_id)
    by_task = (
        select(DayPlan.day_date)
        .join(PlanSection, PlanSection.plan_id == DayPlan.id)
        .join(PlanItem, PlanItem.section_id == PlanSection.id)
        .where(PlanItem.quarter_goal_id == goal_id)
    )
    dates: set[date] = set()
    for statement in (whole_day, by_task):
        dates.update((await db.execute(statement)).scalars().all())
    return sorted(dates)


async def replace_quarter_goals(
    db: AsyncSession, quarter: str, goals: list[QuarterGoalIn]
) -> list[QuarterGoal]:
    """
    Store `goals` as the goals of `quarter`, keeping the ids a plan points at.

    An upsert keyed by `(quarter, ord)` — the pair the file itself names, and
    the key `app.imports.goal_md` already writes by. Delete-and-insert would
    hand every goal a fresh id and cut a lived day loose from what it was lived
    for; with `ondelete='RESTRICT'` on both referring columns it would not even
    get that far, since the `DELETE` fails as soon as one task points at one
    goal.

    Positions the new set does not name are dropped, and dropping one a plan
    still points at raises `QuarterGoalInUse` rather than a
    `ForeignKeyViolation` the caller has to decode.

    Takes the DTOs rather than rows already built: the handle's job is to hand
    over a parsed document and to name the refusal, exactly as `post_plan` does.
    """
    _check_set(goals)
    for one in goals:
        statement = pg_insert(QuarterGoal).values(
            quarter=quarter,
            ord=one.ord,
            text_md=one.text_md,
            milestone_code=one.milestone_code,
            status=one.status,
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[QuarterGoal.quarter, QuarterGoal.ord],
                set_={
                    "text_md": statement.excluded.text_md,
                    "milestone_code": statement.excluded.milestone_code,
                    "status": statement.excluded.status,
                },
            )
        )
    await db.flush()

    kept = {one.ord for one in goals}
    for stored in await list_quarter_goals(db, quarter):
        if stored.ord in kept:
            continue
        days = await _days_pointing_at(db, stored.id)
        if days:
            raise QuarterGoalInUse(stored, days)
        await db.delete(stored)
    await db.flush()
    return await list_quarter_goals(db, quarter)


__all__ = [
    "QuarterGoalInUse",
    "QuarterGoalsRejected",
    "dependencies",
    "existing_goal_ids",
    "get_milestone",
    "list_levels",
    "list_milestones",
    "list_quarter_goals",
    "quarter_code",
    "replace_quarter_goals",
    "set_milestone_status",
]
