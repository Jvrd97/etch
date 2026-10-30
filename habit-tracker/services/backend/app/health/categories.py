# [review:need-review] PHASE-03/272
# summary: category types (all but sleep) into hourly buckets — minutes over the union of intervals so iPhone and Watch copies count once, counts at the hour of an interval's last moment with identical intervals counted once, and HealthKit's "did not happen" value skipped for the stand hour and symptoms
"""
Category samples into hourly buckets.

Sleep folds into nights (`app.health.sleep`); every other category type in the
catalogue is `cumulative`, and its canonical unit says what an interval is
worth:

- **`min`** (a mindful session): its minutes. iPhone and Watch log their own
  copies of the same session, so the minutes come from the union of the
  intervals, every moment counted once — the sleep fold's rule without stages.
- **`count`** (a stand hour, a heart-rate notification, a symptom): one per
  interval, in the local hour of its last moment. An interval that ends on the
  hour belongs to the hour before it, so a stand hour 10:00-11:00 is hour 10.
  The end, not the start, places it because the phone clips intervals to the
  start of its reading window: the end is the part that never moves.

Pure functions, no database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.health.aggregate import (
    HourBucket,
    MetricKind,
    RawSample,
    UnitError,
    aggregate_samples,
)
from app.health.catalog import GROUP_SYMPTOMS, SEED_METRICS

COUNT_UNIT = "count"
MINUTE_UNIT = "min"
SECONDS_PER_MINUTE = 60

# The step back from an interval's end to its last moment inside it.
_LAST_MOMENT = timedelta(microseconds=1)

# HealthKit names every category type with this prefix; a quantity type sent as
# an interval (steps as a "count") would otherwise be counted, not refused.
CATEGORY_PREFIX = "HKCategoryTypeIdentifier"

STAND_HOUR_IDENTIFIER = "HKCategoryTypeIdentifierAppleStandHour"

# HealthKit's raw value for "it did not happen" in the types that log absence
# too: `HKCategoryValueAppleStandHour.idle`, `HKCategoryValueSeverity.notPresent`,
# `HKCategoryValuePresence.notPresent`, `HKCategoryValueAppetiteChanges.noChange`.
# In the event types the same 1 is the event itself (a low cardio fitness
# notification), so the rule is per type, not per value.
ABSENT_VALUE = 1
TYPES_THAT_LOG_ABSENCE: frozenset[str] = frozenset(
    {STAND_HOUR_IDENTIFIER}
    | {seed.identifier for seed in SEED_METRICS if seed.group == GROUP_SYMPTOMS}
)


@dataclass(frozen=True)
class CategoryInterval:
    """One category sample as it left the device: HealthKit's raw value and an interval."""

    value: int
    start: datetime
    end: datetime
    utc_offset_minutes: int


def category_hours(
    identifier: str, intervals: Sequence[CategoryInterval], canonical_unit: str
) -> list[HourBucket]:
    """
    One category type's intervals as local hourly buckets, in calendar order.

    Raises `UnitError` for a quantity type sent as intervals and (from
    `aggregate_samples`) when the canonical unit is neither minutes nor a
    count: the caller refuses the chunk.
    """
    if not identifier.startswith(CATEGORY_PREFIX):
        raise UnitError(f"{identifier} does not take category samples")
    happened = [
        interval
        for interval in intervals
        if interval.end >= interval.start
        and not (
            identifier in TYPES_THAT_LOG_ABSENCE and interval.value == ABSENT_VALUE
        )
    ]
    if canonical_unit == COUNT_UNIT:
        samples = _counts(happened)
    else:
        samples = _minutes(happened)
    return aggregate_samples(samples, MetricKind.CUMULATIVE, canonical_unit)


def _counts(intervals: Sequence[CategoryInterval]) -> list[RawSample]:
    """One count per distinct interval, placed at its last moment."""
    distinct = {(i.start, i.end): i for i in intervals}.values()
    return [
        RawSample(
            value=1.0,
            unit=COUNT_UNIT,
            start=_last_moment(interval),
            end=_last_moment(interval),
            utc_offset_minutes=interval.utc_offset_minutes,
        )
        for interval in distinct
    ]


def _last_moment(interval: CategoryInterval) -> datetime:
    if interval.end > interval.start:
        return interval.end - _LAST_MOMENT
    return interval.end


def _minutes(intervals: Sequence[CategoryInterval]) -> list[RawSample]:
    """
    Minutes of the union of the intervals: overlapping sources merge into one run.

    A merged run keeps the offset of the interval that opened it; two sources
    living in different zones over the same minutes do not happen in practice.
    """
    runs: list[CategoryInterval] = []
    for interval in sorted(intervals, key=lambda i: (i.start, i.end)):
        if interval.end == interval.start:
            continue
        if runs and interval.start <= runs[-1].end:
            last = runs[-1]
            runs[-1] = CategoryInterval(
                value=last.value,
                start=last.start,
                end=max(last.end, interval.end),
                utc_offset_minutes=last.utc_offset_minutes,
            )
        else:
            runs.append(interval)
    return [
        RawSample(
            value=(run.end - run.start).total_seconds() / SECONDS_PER_MINUTE,
            unit=MINUTE_UNIT,
            start=run.start,
            end=run.end,
            utc_offset_minutes=run.utc_offset_minutes,
        )
        for run in runs
    ]
