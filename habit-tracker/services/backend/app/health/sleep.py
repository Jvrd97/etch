# [review:need-review] PHASE-03/238
# summary: the sleep fold — HealthKit sleep stages by their raw values, intervals grouped into nights by the local wake date (18:00 boundary), minutes per stage over a timeline where overlapping sources count once and a detailed stage wins, bedtime and wake time of the longest session
"""
Sleep intervals into nights.

HealthKit keeps sleep as `HKCategorySample`s of `HKCategoryTypeIdentifierSleepAnalysis`:
intervals, each with one stage. The phone sends them raw; this module is the
one place that turns them into nights, as `app.health.aggregate` is for the
quantity metrics. Pure functions, no database.

**A night is named by the wake date.** Every interval that ends between 18:00
the evening before and 18:00 that day, on the device's own clock, belongs to
the night of that date. A night that crosses midnight is therefore one night,
and an afternoon nap counts toward the day it was taken.

**Sources do not add up.** iPhone and Watch (and any sleep app) write their
own intervals over the same minutes. The fold walks the timeline once: each
moment counts once, under the most detailed stage any source gave it (deep >
REM > core > awake > asleep without a stage > in bed).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import IntEnum
from itertools import pairwise

from app.core.humanize import MINUTES_PER_HOUR
from app.health.aggregate import local_time

SECONDS_PER_MINUTE = 60
HOURS_PER_DAY = 24

# The local hour at which one sleep day hands over to the next.
NIGHT_BOUNDARY_HOUR = 18
_WAKE_DATE_SHIFT = timedelta(hours=HOURS_PER_DAY - NIGHT_BOUNDARY_HOUR)

# A gap at least this long between intervals starts a new session (a nap).
SESSION_GAP = timedelta(minutes=MINUTES_PER_HOUR)

# Minutes are stored to a tenth: the fold works in seconds and a night of
# dozens of intervals would otherwise carry float noise into the table.
MINUTE_DIGITS = 1


class SleepValueError(ValueError):
    """A category value that is not a sleep stage HealthKit defines."""


class SleepStage(IntEnum):
    """`HKCategoryValueSleepAnalysis` raw values — the key both sides send."""

    IN_BED = 0
    ASLEEP_UNSPECIFIED = 1
    AWAKE = 2
    ASLEEP_CORE = 3
    ASLEEP_DEEP = 4
    ASLEEP_REM = 5


# Which stage a moment counts under when several sources cover it.
_PRIORITY: dict[SleepStage, int] = {
    SleepStage.IN_BED: 0,
    SleepStage.ASLEEP_UNSPECIFIED: 1,
    SleepStage.AWAKE: 2,
    SleepStage.ASLEEP_CORE: 3,
    SleepStage.ASLEEP_REM: 4,
    SleepStage.ASLEEP_DEEP: 5,
}

_ASLEEP = frozenset(
    {
        SleepStage.ASLEEP_UNSPECIFIED,
        SleepStage.ASLEEP_CORE,
        SleepStage.ASLEEP_DEEP,
        SleepStage.ASLEEP_REM,
    }
)


def stage_of(raw: int) -> SleepStage:
    """The stage behind a HealthKit raw value, or `SleepValueError`."""
    try:
        return SleepStage(raw)
    except ValueError:
        raise SleepValueError(f"unknown sleep stage value: {raw}") from None


@dataclass(frozen=True)
class SleepInterval:
    """One sample of the sleep type as it left the device."""

    stage: SleepStage
    start: datetime
    end: datetime
    utc_offset_minutes: int


@dataclass(frozen=True)
class SleepNight:
    """
    One night, keyed by the local wake date.

    `in_bed_min` is all the time any source covered; `asleep_min` the part under
    a sleep stage. `bedtime`/`wake_time` are the bounds of the longest session,
    so a nap neither moves the bedtime nor turns the afternoon into the wake time.
    """

    wake_date: date
    bedtime: datetime
    wake_time: datetime
    utc_offset_minutes: int
    in_bed_min: float
    asleep_min: float
    awake_min: float
    core_min: float
    deep_min: float
    rem_min: float
    unspecified_min: float


def wake_date_of(interval: SleepInterval) -> date:
    """The night an interval belongs to: its local end shifted past the 18:00 boundary."""
    return (
        local_time(interval.end, interval.utc_offset_minutes) + _WAKE_DATE_SHIFT
    ).date()


def fold_nights(intervals: Iterable[SleepInterval]) -> list[SleepNight]:
    """Group intervals into nights by wake date and fold each one, oldest first."""
    by_night: dict[date, list[SleepInterval]] = {}
    for interval in intervals:
        if interval.end <= interval.start:
            continue
        by_night.setdefault(wake_date_of(interval), []).append(interval)
    return [_fold_night(day, by_night[day]) for day in sorted(by_night)]


def _fold_night(wake_date: date, intervals: Sequence[SleepInterval]) -> SleepNight:
    seconds = _seconds_per_stage(intervals)
    bedtime, wake_time = _longest_session(intervals)
    last = max(intervals, key=lambda interval: interval.end)

    def minutes(*stages: SleepStage) -> float:
        total = sum(seconds[stage] for stage in stages) / SECONDS_PER_MINUTE
        return round(total, MINUTE_DIGITS)

    return SleepNight(
        wake_date=wake_date,
        bedtime=bedtime,
        wake_time=wake_time,
        utc_offset_minutes=last.utc_offset_minutes,
        in_bed_min=minutes(*SleepStage),
        asleep_min=minutes(*_ASLEEP),
        awake_min=minutes(SleepStage.AWAKE),
        core_min=minutes(SleepStage.ASLEEP_CORE),
        deep_min=minutes(SleepStage.ASLEEP_DEEP),
        rem_min=minutes(SleepStage.ASLEEP_REM),
        unspecified_min=minutes(SleepStage.ASLEEP_UNSPECIFIED),
    )


def _seconds_per_stage(intervals: Sequence[SleepInterval]) -> dict[SleepStage, float]:
    """
    Seconds under each stage, every moment counted once.

    The timeline is cut at every interval edge; each slice goes to the
    highest-priority stage among the intervals covering it. Quadratic in the
    intervals of one night, which is a few dozen.
    """
    seconds = dict.fromkeys(SleepStage, 0.0)
    edges = sorted({moment for i in intervals for moment in (i.start, i.end)})
    for left, right in pairwise(edges):
        covering = [i.stage for i in intervals if i.start <= left and i.end >= right]
        if covering:
            stage = max(covering, key=_PRIORITY.__getitem__)
            seconds[stage] += (right - left).total_seconds()
    return seconds


def _longest_session(intervals: Sequence[SleepInterval]) -> tuple[datetime, datetime]:
    """Bounds of the longest run of intervals with no gap of `SESSION_GAP` or more."""
    ordered = sorted(intervals, key=lambda interval: interval.start)
    sessions: list[tuple[datetime, datetime]] = []
    start, end = ordered[0].start, ordered[0].end
    for interval in ordered[1:]:
        if interval.start - end >= SESSION_GAP:
            sessions.append((start, end))
            start, end = interval.start, interval.end
        else:
            end = max(end, interval.end)
    sessions.append((start, end))
    return max(sessions, key=lambda session: session[1] - session[0])
