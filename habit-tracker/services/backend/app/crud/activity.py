# [review:need-review] PHASE-03/135
# summary: database access for the agent's tables — the catalogue lookup that refuses an unknown bundle, the batch upsert of intervals on `(source, started_at, app_id)`, the intervals of one work day read through `day_bounds()`, and the mode of a date, where a manual row overrides the schedule and nothing else does
"""
Database access for the activity the macOS agent records.

Two things here decide behaviour; the rest is queries.

**Незнакомый bundle отвергается, а не заводится.** `tracked_app` is also the list
of whose window titles may ever be kept, so a catalogue that grows from the data
stream is a catalogue that silently widens what the system is allowed to
remember. `UnknownApp` carries the bundle id, and the API turns it into a 422.

**Режим дня: ручная строка перебивает расписание.** No `day_mode` row is the
normal state — the mode is then whatever `mode_schedule` says about that weekday.
A row exists only where a person decided, and it wins for that date alone. Same
semantics as `override=YYYY-MM-DD:on|off` in `~/.claude/nocode/config`.

The intervals of a day are read by `started_at` inside `day_bounds()` rather than
by the `local_date` column the writer filled in: which day a moment belongs to is
`app.core.daytime`'s question alone, and a column filled by a client is a second
opinion about it. The column stays useful as an index and as what the agent
believed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import day_bounds
from app.models.activity import (
    ACTIVITY_SOURCE_AGENT,
    MODE_SOURCE_SCHEDULE,
    TITLE_DROPPED,
    ActivityInterval,
    DayMode,
    ModeSchedule,
    TrackedApp,
)

__all__ = [
    "DayModeAnswer",
    "IntervalDraft",
    "UnknownApp",
    "app_names",
    "day_intervals",
    "day_mode",
    "list_apps",
    "upsert_intervals",
]


class UnknownApp(LookupError):
    """
    A batch named a bundle the catalogue does not carry.

    Carries the bundle id, because the answer a person needs is «заведи вот это»
    and not «одно из приложений неизвестно».
    """

    def __init__(self, bundle_id: str) -> None:
        super().__init__(bundle_id)
        self.bundle_id = bundle_id


@dataclass(frozen=True)
class IntervalDraft:
    """One interval as the agent states it, before the table has an opinion."""

    bundle_id: str | None
    started_at: datetime
    ended_at: datetime
    local_date: date
    utc_offset_minutes: int = 0
    title: str | None = None
    title_source: str = TITLE_DROPPED
    idle_seconds: int = 0
    switch_count: int = 0
    source: str = ACTIVITY_SOURCE_AGENT
    note: str | None = None


@dataclass(frozen=True)
class DayModeAnswer:
    """
    Which kind of day a date is, and who said so.

    `source` matters as much as `kind`: «выходной по расписанию» and «выходной,
    потому что человек так решил» are the same day and different facts, and the
    screen that shows a mode has to be able to say which one it is looking at.
    """

    kind: str
    nocode: bool
    source: str


async def list_apps(db: AsyncSession) -> list[TrackedApp]:
    """The catalogue, in the order a screen lists it."""
    return list(
        (await db.execute(select(TrackedApp).order_by(TrackedApp.display_name)))
        .scalars()
        .all()
    )


async def app_names(db: AsyncSession) -> dict[int, str]:
    """Application id to display name, read once per request instead of per row."""
    rows = await db.execute(select(TrackedApp.id, TrackedApp.display_name))
    return {row.id: row.display_name for row in rows}


async def _app_ids(db: AsyncSession) -> dict[str, int]:
    """Bundle id to catalogue id, for resolving a whole batch in one query."""
    rows = await db.execute(select(TrackedApp.bundle_id, TrackedApp.id))
    return {row.bundle_id: row.id for row in rows}


async def upsert_intervals(
    db: AsyncSession, drafts: list[IntervalDraft]
) -> list[ActivityInterval]:
    """
    Write a batch of intervals, once per `(source, started_at, app_id)`.

    The whole batch is resolved against the catalogue before a single row is
    written, so an unknown bundle leaves nothing behind — a batch is accepted or
    refused, never half-applied.

    `ON CONFLICT DO UPDATE` is what makes a re-sent batch land on the rows it
    already wrote. That is the reason this stream needs no `Idempotency-Key`:
    the natural key is the idempotency, exactly as in the health contour's
    `upsert_buckets`.
    """
    if not drafts:
        return []

    known = await _app_ids(db)
    for draft in drafts:
        if draft.bundle_id is not None and draft.bundle_id not in known:
            raise UnknownApp(draft.bundle_id)

    written: list[ActivityInterval] = []
    for draft in drafts:
        app_id = known.get(draft.bundle_id) if draft.bundle_id else None
        statement = pg_insert(ActivityInterval).values(
            source=draft.source,
            app_id=app_id,
            started_at=draft.started_at,
            ended_at=draft.ended_at,
            local_date=draft.local_date,
            utc_offset_minutes=draft.utc_offset_minutes,
            title=draft.title,
            title_source=draft.title_source,
            idle_seconds=draft.idle_seconds,
            switch_count=draft.switch_count,
            note=draft.note,
        )
        stored = await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_activity_interval_natural",
                set_={
                    "ended_at": statement.excluded.ended_at,
                    "local_date": statement.excluded.local_date,
                    "utc_offset_minutes": statement.excluded.utc_offset_minutes,
                    "title": statement.excluded.title,
                    "title_source": statement.excluded.title_source,
                    "idle_seconds": statement.excluded.idle_seconds,
                    "switch_count": statement.excluded.switch_count,
                    "note": statement.excluded.note,
                },
            ).returning(ActivityInterval.id)
        )
        written.append(await _reload(db, stored.scalar_one()))
    await db.flush()
    return written


async def _reload(db: AsyncSession, interval_id: int) -> ActivityInterval:
    """
    The stored row, read back rather than assembled from the draft.

    `duration_seconds` is generated by postgres, so the only way to know it is to
    ask; assembling the row here would invent the one number the table is the
    authority on.
    """
    row = (
        await db.execute(
            select(ActivityInterval).where(ActivityInterval.id == interval_id)
        )
    ).scalar_one()
    await db.refresh(row)
    return row


async def day_intervals(db: AsyncSession, work_day: date) -> list[ActivityInterval]:
    """
    Every interval that overlaps the work day `work_day`, in the order it happened.

    Overlap rather than «начался в этот день»: a session from 03:30 to 04:30 is
    half of one day and half of the next, and a query keyed on the start would
    hand the second half to nobody. `app.roles.classify` cuts what this returns.

    Against `day_bounds()` rather than against the `local_date` column the writer
    filled in: which day a moment belongs to is `app.core.daytime`'s question
    alone, and a column filled by a client is a second opinion about it. The
    column stays useful as an index and as what the agent believed.
    """
    start, end = day_bounds(work_day)
    result = await db.execute(
        select(ActivityInterval)
        .where(ActivityInterval.started_at < end, ActivityInterval.ended_at > start)
        .order_by(ActivityInterval.started_at, ActivityInterval.id)
    )
    return list(result.scalars().all())


async def day_mode(db: AsyncSession, on: date) -> DayModeAnswer:
    """
    Which kind of day `on` is: a person's decision, or the schedule's default.

    A weekday the schedule has no row for answers `work`: a schedule that has
    lost a row must not turn a working day into a day nothing is measured on,
    which is the failure that would be hardest to notice.
    """
    stored = await db.get(DayMode, on)
    if stored is not None:
        return DayModeAnswer(
            kind=stored.kind, nocode=stored.nocode, source=stored.source
        )

    # `date.isoweekday()` is 1=Mon…7=Sun; the schedule counts 0=Sun…6=Sat.
    weekday = on.isoweekday() % 7
    row = (
        await db.execute(select(ModeSchedule).where(ModeSchedule.weekday == weekday))
    ).scalar_one_or_none()
    if row is None:
        return DayModeAnswer(kind="work", nocode=False, source=MODE_SOURCE_SCHEDULE)
    return DayModeAnswer(kind=row.kind, nocode=row.nocode, source=MODE_SOURCE_SCHEDULE)
