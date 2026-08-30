# [review:need-review] PHASE-03/93
# summary: database access for the goals — the whole board in one read (levels, milestones with their dependency edges, the goals of the current quarter), the set of ids a plan may point at, the status of one milestone, and the five goals of a quarter replaced as a set so the ceiling is checked by the database over the whole quarter at once
"""
Database access for the goals of `goal.md`.

**Замена квартала целиком, а не цель за целью.** `PUT /goals/quarter/{quarter}`
takes five goals and replaces five goals, the same idiom `replace_plan` already
uses for a day. A per-goal API would make the ceiling of five a question about
the row being written, and the row being written is never the one over the bar —
the ceiling is a property of the set, and the database checks it as one.

**Статус милстона переживает импорт.** Whether M2 is done is a fact a person
establishes; `goal.md` does not record it. So `set_milestone_status` is the only
writer of `status` and `done_on`, and the import (`app.imports.goal_md`) writes
neither.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import (
    MILESTONE_STATUS_DONE,
    GoalLevel,
    Milestone,
    MilestoneDep,
    QuarterGoal,
)

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


async def replace_quarter_goals(
    db: AsyncSession, quarter: str, goals: list[QuarterGoal]
) -> list[QuarterGoal]:
    """
    Store `goals` as the goals of `quarter`, replacing whatever was there.

    The whole set at once, so the ceiling of five is checked by the database
    over the set rather than by a service counting rows it just read. A sixth
    goal fails on `ck_quarter_goal_ord` or on `uq_quarter_goal_quarter_ord`, and
    the transaction takes the other five with it — which is the right outcome:
    a quarter is five goals or it is not written.
    """
    await db.execute(delete(QuarterGoal).where(QuarterGoal.quarter == quarter))
    await db.flush()
    for goal in goals:
        db.add(goal)
    await db.flush()
    return await list_quarter_goals(db, quarter)


__all__ = [
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
