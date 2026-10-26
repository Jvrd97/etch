# [review:need-review] PHASE-03/162
# summary: writes of the day mode — a manual row upserted for one date, deleted to give the day back to the schedule, and the weekly schedule read and replaced; reading a mode stays in app.crud.activity.day_mode
"""
Database access for the day mode's writes.

Resolving a mode — a manual row beats the schedule, no row means the schedule —
is `app.crud.activity.day_mode`, which the role markup already depends on; it is
reused rather than copied so that the screen and the minutes can never read two
different rules.

A schedule edit touches `mode_schedule` only. A date somebody decided by hand has
its own `day_mode` row and is not looked at, which is the whole of «the edit
moves the days nobody decided».
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import now_utc
from app.models.activity import MODE_SOURCE_MANUAL, DayMode, ModeSchedule
from app.schemas.day_mode import DayModeIn, ModeScheduleWeek

__all__ = ["clear_manual_mode", "list_schedule", "replace_schedule", "set_manual_mode"]


async def set_manual_mode(db: AsyncSession, on: date, decision: DayModeIn) -> None:
    """Record the decision for `on`, replacing an earlier one; flushes, does not commit."""
    row = await db.get(DayMode, on)
    if row is None:
        row = DayMode(date=on)
        db.add(row)
    row.kind = decision.kind
    row.nocode = decision.nocode
    row.source = MODE_SOURCE_MANUAL
    row.note = decision.note
    # Server default only fires on insert; an overwritten decision is decided now.
    row.decided_at = now_utc()
    await db.flush()


async def clear_manual_mode(db: AsyncSession, on: date) -> None:
    """Give `on` back to the schedule. No decision to clear is not an error."""
    row = await db.get(DayMode, on)
    if row is not None:
        await db.delete(row)
        await db.flush()


async def list_schedule(db: AsyncSession) -> list[ModeSchedule]:
    """The week, 0 = Sunday first."""
    result = await db.execute(select(ModeSchedule).order_by(ModeSchedule.weekday))
    return list(result.scalars().all())


async def replace_schedule(db: AsyncSession, schedule: ModeScheduleWeek) -> None:
    """Write the seven days over the stored ones, inserting a weekday the table lost."""
    stored = {row.weekday: row for row in await list_schedule(db)}
    for day in schedule.days:
        row = stored.get(day.weekday)
        if row is None:
            row = ModeSchedule(weekday=day.weekday)
            db.add(row)
        row.kind = day.kind
        row.nocode = day.nocode
    await db.flush()
