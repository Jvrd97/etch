# [review:need-review] PHASE-03/135
# summary: intervals of activity become minutes of a role — the day's intervals cut at the day boundary of `core/daytime`, dropped whole on a non-working mode, resolved through `roles/matcher` (an interval with no title is matched on `bundle_id` alone), written as `role_time_block` with `source='app_usage'`, the id of the interval and the id of the rule that fired, and then cut down by every stronger source through `roles/precedence`
"""
Which role the day's measured activity belongs to.

The agent answers «что происходило»; this module answers «чем это было». The
split is why the classifier lives on the server: attribution is a rule table a
person edits from the web, and a rule that changes by shipping a new build of a
mac app is a rule nobody changes.

**`rule_id` не украшение.** Every automatic row names the rule that produced it.
Without that, wrong markup is indistinguishable from right markup, and wrong
markup that nobody can question is the main source of quiet lying in this theme.

**Режим дня уважается на входе.** Minutes outside a working mode are not
distributed at all — not to `unassigned`, not anywhere. The mode is read from
`day_mode`/`mode_schedule`, where an open manual override beats the schedule.
Автоопределение режима по активности отвергнуто человеком, and it is not here:
it would have been wrong exactly in the evening free block, which `config.md`
forbids filling with a schedule in the first place.

**Границу суток модуль не изобретает.** `work_day` is `core.daytime.local_date`
and nothing else; an interval that crosses the boundary is cut at it, because a
night session charged whole to one day makes both days' numbers wrong. There is
no second `WORK_DAY_BOUNDARY_HOUR` here and no second reading of `day_rule_set`.

**Заголовок может отсутствовать, и это штатный путь.** `title_source='dropped'`
is what the privacy policy produces for everything not explicitly allowed; such
an interval is matched on `bundle_id` alone. A window title is never written to a
log, here or below — `MatchSample` carries it, the matcher matches on it, and
neither prints it.

Re-running the markup restates the day rather than adding to it: rows are keyed
`(source, external_ref)` and a row a person confirmed is left exactly as it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import day_bounds, local_date
from app.crud import activity as activity_crud
from app.crud import role as role_crud
from app.models.activity import WORKING_MODES, ActivityInterval, TrackedApp
from app.models.role import (
    CONFIDENCE_AUTO,
    CONFIDENCE_CONFIRMED,
    SOURCE_APP_USAGE,
    RoleTimeBlock,
)
from app.roles import plan_source
from app.roles.matcher import MatchSample
from app.roles.precedence import Span, minutes_of

logger = logging.getLogger(__name__)

__all__ = [
    "ClassifyResult",
    "classify_day",
    "classify_range",
    "day_slices",
    "touched_days",
]


@dataclass(frozen=True)
class DaySlice:
    """
    One interval's share of one work day.

    An interval that crosses the boundary produces two of these, and each is
    charged to its own day. `interval_id` is kept so the row can be traced back
    to what was measured.
    """

    interval_id: int
    work_day: date
    span: Span
    bundle_id: str | None
    window_title: str | None

    @property
    def external_ref(self) -> str:
        """
        The key this slice's row is idempotent on.

        The day is part of it because an interval cut at the boundary writes two
        rows, and `(source, external_ref)` is unique — the two halves of one
        night session must not fight over one row.
        """
        return f"{self.interval_id}:{self.work_day.isoformat()}"


@dataclass(frozen=True)
class ClassifyResult:
    """
    What one run of the markup did to one day, in numbers a screen can print.

    `skipped_off_mode` and `skipped_short` exist so that «минут меньше, чем я
    работал» has an answer other than a shrug: the first is the mode, the second
    is slices under a minute.
    """

    work_day: date
    mode: str
    intervals: int
    blocks_written: int
    kept_confirmed: int
    minutes: int
    unassigned_minutes: int
    skipped_off_mode: int
    skipped_short: int


def day_slices(interval: ActivityInterval, bundle_id: str | None) -> list[DaySlice]:
    """
    One interval cut into the work days it actually spans.

    Pure but for the day boundary, which is a process-wide value of
    `app.core.daytime` rather than an argument — the whole point of `#107` is
    that nobody passes it around and nobody disagrees about it.

    A session from 23:30 to 00:30 under a four o'clock boundary comes back as one
    slice on the previous work day, because that is the day it was lived on.
    """
    slices: list[DaySlice] = []
    cursor: datetime = interval.started_at
    while cursor < interval.ended_at:
        work_day = local_date(cursor)
        _, day_end = day_bounds(work_day)
        stop = min(interval.ended_at, day_end)
        slices.append(
            DaySlice(
                interval_id=interval.id,
                work_day=work_day,
                span=Span(start=cursor, end=stop),
                bundle_id=bundle_id,
                window_title=interval.title,
            )
        )
        cursor = stop
    return slices


def touched_days(interval: ActivityInterval) -> list[date]:
    """
    Every work day one interval has minutes on, oldest first.

    What the intake needs after a batch: an interval from 03:30 to 04:30 is half
    of one day and half of the next, and marking up only the day it started on
    would leave the second half uncounted until somebody ran the markup by hand.
    """
    return [piece.work_day for piece in day_slices(interval, None)]


async def _bundles(db: AsyncSession) -> dict[int, str]:
    """Catalogue id to bundle id — the only thing the matcher needs from it."""
    rows = await db.execute(select(TrackedApp.id, TrackedApp.bundle_id))
    return {row.id: row.bundle_id for row in rows}


async def _automatic_blocks(db: AsyncSession, work_day: date) -> list[RoleTimeBlock]:
    """Every record of minutes this day owes to the agent."""
    result = await db.execute(
        select(RoleTimeBlock).where(
            RoleTimeBlock.work_day == work_day,
            RoleTimeBlock.source == SOURCE_APP_USAGE,
        )
    )
    return list(result.scalars().all())


async def classify_day(db: AsyncSession, work_day: date) -> ClassifyResult:
    """
    Turn the day's intervals into minutes of roles, and restate them if re-run.

    Four things happen in order, and the order is the meaning:

    1. the mode of the day decides whether anything is distributed at all;
    2. every interval is cut at the day boundary, so a night session lands where
       it was lived;
    3. each slice is resolved through the rules and written with the id of the
       rule that fired — an unmatched slice goes to `unassigned` rather than to
       NULL, because «не удалось отнести» is a fact worth seeing;
    4. every stronger source takes back the hours it already owns
       (`app.roles.plan_source.apply_precedence`), so a planned section and the
       agent agreeing about the same hour do not add up to two.
    """
    mode = await activity_crud.day_mode(db, work_day)
    intervals = await activity_crud.day_intervals(db, work_day)
    bundles = await _bundles(db)

    if mode.kind not in WORKING_MODES:
        removed = await _drop_automatic(db, work_day)
        return ClassifyResult(
            work_day=work_day,
            mode=mode.kind,
            intervals=len(intervals),
            blocks_written=0,
            kept_confirmed=removed.kept_confirmed,
            minutes=0,
            unassigned_minutes=0,
            skipped_off_mode=len(intervals),
            skipped_short=0,
        )

    slices = [
        piece
        for interval in intervals
        for piece in day_slices(interval, bundles.get(interval.app_id or -1))
        if piece.work_day == work_day
    ]

    fallback = await role_crud.fallback_role_id(db)
    written = 0
    kept = 0
    short = 0
    minutes_total = 0
    unassigned = 0
    alive: set[str] = set()

    for piece in slices:
        minutes = minutes_of([piece.span])
        if minutes == 0:
            short += 1
            continue
        resolution = await role_crud.resolve_role(
            db,
            MatchSample(
                source=SOURCE_APP_USAGE,
                bundle_id=piece.bundle_id,
                window_title=piece.window_title,
            ),
        )
        outcome = await role_crud.write_time_block(
            db,
            role_crud.TimeBlockDraft(
                work_day=work_day,
                role_id=resolution.role_id,
                minutes=minutes,
                source=SOURCE_APP_USAGE,
                started_at=piece.span.start,
                ended_at=piece.span.end,
                confidence=CONFIDENCE_AUTO,
                external_ref=piece.external_ref,
                rule_id=resolution.rule_id,
            ),
        )
        alive.add(piece.external_ref)
        if outcome.kept_confirmed:
            kept += 1
        else:
            written += 1
        minutes_total += outcome.row.minutes
        if resolution.role_id == fallback:
            unassigned += outcome.row.minutes

    await _drop_automatic(db, work_day, keep=alive)
    await plan_source.apply_precedence(db, work_day)

    return ClassifyResult(
        work_day=work_day,
        mode=mode.kind,
        intervals=len(intervals),
        blocks_written=written,
        kept_confirmed=kept,
        minutes=minutes_total,
        unassigned_minutes=unassigned,
        skipped_off_mode=0,
        skipped_short=short,
    )


@dataclass(frozen=True)
class _Dropped:
    """How many automatic rows a cleanup removed, and how many it refused to."""

    removed: int
    kept_confirmed: int


async def _drop_automatic(
    db: AsyncSession, work_day: date, keep: set[str] | None = None
) -> _Dropped:
    """
    Remove automatic rows this run did not restate.

    An interval deleted, corrected or moved to another day would otherwise leave
    its minutes standing — the day would keep growing and never shrink. A row a
    person confirmed is never removed: automation retracts its own claim and
    nobody else's.
    """
    removed = 0
    kept = 0
    for block in await _automatic_blocks(db, work_day):
        if keep is not None and block.external_ref in keep:
            continue
        if block.confidence == CONFIDENCE_CONFIRMED:
            kept += 1
            continue
        await db.delete(block)
        removed += 1
    await db.flush()
    return _Dropped(removed=removed, kept_confirmed=kept)


async def classify_range(
    db: AsyncSession, date_from: date, date_to: date
) -> list[ClassifyResult]:
    """
    The markup of every day in `[date_from, date_to]`, oldest first.

    A range rather than a day, because the honest reason to run this by hand is
    «поправил правило — переразметь неделю», and asking for seven requests to do
    it would make the rules editor of `#139` unusable.
    """
    results: list[ClassifyResult] = []
    day = date_from
    while day <= date_to:
        results.append(await classify_day(db, day))
        day = date.fromordinal(day.toordinal() + 1)
    logger.info("role markup: %s days from %s to %s", len(results), date_from, date_to)
    return results
