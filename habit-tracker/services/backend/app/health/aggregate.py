# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: the whole Health arithmetic — unit canonicalisation, local hourly bucketing, DST merge, weighted daily fold; no database, no HTTP
"""
Aggregation of raw HealthKit samples into local hourly buckets.

This module is the one place the Health contour does arithmetic. It is
deliberately free of the database and of FastAPI: every rule here — which hour a
sample belongs to, how a cumulative sample split across an hour boundary is
divided, how a discrete metric collapses into a day — is a pure function over
values, and is covered by `tests/test_health_aggregate.py`.

Two decisions shape everything else:

**Local, not UTC.** A bucket is identified by the device's local date and hour.
Every conclusion the app draws is about a lived calendar ("evenings are worse"),
and storing UTC would still require keeping the historical offset around for
flights and DST — so it buys nothing and costs a conversion on every read.

**The server is the only aggregator.** The client ships raw samples and nothing
else. One implementation under pytest beats two that disagree, and this one can
be fixed by a redeploy rather than by re-signing an app.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

SECONDS_PER_HOUR = 3600
MINUTES_PER_HOUR = 60


class MetricKind(str, Enum):
    """
    How a metric's samples collapse into one number.

    `CUMULATIVE` metrics measure an amount produced over an interval (steps,
    kilocalories, distance): they add up. `DISCRETE` metrics are readings of a
    state at a moment (resting heart rate, weight, HRV): they average, and the
    average has to be weighted by how many readings each bucket holds.
    """

    CUMULATIVE = "cumulative"
    DISCRETE = "discrete"


class UnitError(ValueError):
    """
    A unit the catalogue cannot turn into the metric's canonical unit.

    Raised both for units nobody has taught the server and for units from the
    wrong dimension (kilograms offered for a distance). Both cases must stop the
    batch: the alternative is a plausible-looking number that is wrong by three
    orders of magnitude, and nothing downstream can tell.
    """


@dataclass(frozen=True)
class RawSample:
    """
    One HealthKit sample as it left the device.

    `start`/`end` are absolute instants (timezone-aware). `utc_offset_minutes`
    is the offset the device was living at when the sample was recorded, and it
    is what turns those instants into a lived wall clock — deriving it from the
    server's own timezone would misplace every sample recorded abroad.

    An instantaneous sample has `end == start`.
    """

    value: float
    unit: str
    start: datetime
    end: datetime
    utc_offset_minutes: int


@dataclass(frozen=True)
class HourBucket:
    """
    One local hour of one metric, ready to be upserted.

    `sample_count` is not bookkeeping: it is the weight that makes the daily
    average of a discrete metric correct. `min_value`/`max_value` keep the
    extremes an average destroys — a resting heart rate averaged over an hour
    hides the reading the whole hour was about.
    """

    local_date: date
    hour: int
    value: float
    sample_count: int
    min_value: float
    max_value: float
    utc_offset_minutes: int


# --- Units ------------------------------------------------------------------

# Every unit the server understands, as (dimension, factor to the dimension's
# base unit). Conversion is therefore a division of factors, and two units from
# different dimensions are structurally unconvertible.
#
# The base unit of a dimension is an implementation detail; the *canonical* unit
# is per metric and lives in the catalogue: distance canonicalises to metres and
# height to centimetres, and both are the same dimension here.
_UNITS: dict[str, tuple[str, float]] = {
    # length, base metre
    "m": ("length", 1.0),
    "km": ("length", 1000.0),
    "cm": ("length", 0.01),
    "mm": ("length", 0.001),
    "mi": ("length", 1609.344),
    "ft": ("length", 0.3048),
    "in": ("length", 0.0254),
    # energy, base kilocalorie. "Cal" is the food calorie, i.e. a kilocalorie.
    "kcal": ("energy", 1.0),
    "Cal": ("energy", 1.0),
    "cal": ("energy", 0.001),
    "kJ": ("energy", 1.0 / 4.184),
    "J": ("energy", 1.0 / 4184.0),
    # duration, base minute. Milliseconds live here too: HRV is a duration.
    "min": ("duration", 1.0),
    "s": ("duration", 1.0 / 60.0),
    "ms": ("duration", 1.0 / 60_000.0),
    "hr": ("duration", 60.0),
    "d": ("duration", 1440.0),
    # rate, base count per minute
    "count/min": ("rate", 1.0),
    "bpm": ("rate", 1.0),
    # mass, base kilogram
    "kg": ("mass", 1.0),
    "g": ("mass", 0.001),
    "lb": ("mass", 0.45359237),
    "st": ("mass", 6.35029318),
    # ratio, base percentage point. HealthKit hands fractions out for some
    # metrics (oxygen saturation), and 0.97 must not be stored next to 97.
    "%": ("ratio", 1.0),
    "fraction": ("ratio", 100.0),
    # dimensionless counts
    "count": ("count", 1.0),
}


def canonicalize(value: float, from_unit: str, to_unit: str) -> float:
    """
    Express `value` in `to_unit`, or raise `UnitError`.

    Both units must be known and share a dimension. Silent pass-through of an
    unknown unit is the one behaviour that is never acceptable here: it writes a
    number that reads fine and means something else.
    """
    try:
        from_dimension, from_factor = _UNITS[from_unit]
    except KeyError:
        raise UnitError(f"unknown unit: {from_unit!r}") from None
    try:
        to_dimension, to_factor = _UNITS[to_unit]
    except KeyError:
        raise UnitError(f"unknown canonical unit: {to_unit!r}") from None
    if from_dimension != to_dimension:
        raise UnitError(
            f"cannot convert {from_unit!r} ({from_dimension}) "
            f"to {to_unit!r} ({to_dimension})"
        )
    return value * from_factor / to_factor


# --- Bucketing --------------------------------------------------------------


def local_time(moment: datetime, utc_offset_minutes: int) -> datetime:
    """The wall clock the device was showing at `moment`, as a naive datetime."""
    offset = timezone(timedelta(minutes=utc_offset_minutes))
    return moment.astimezone(offset).replace(tzinfo=None)


@dataclass(frozen=True)
class _Portion:
    """A sample's contribution to a single local hour."""

    local_date: date
    hour: int
    value: float
    utc_offset_minutes: int


def _hour_key(moment: datetime) -> tuple[date, int]:
    return moment.date(), moment.hour


def _split_cumulative(sample: RawSample, value: float) -> list[_Portion]:
    """
    Spread a cumulative sample over the local hours it covers, by duration.

    A 40-minute walk beginning at 08:50 puts a quarter of its steps in the 08
    bucket and the rest in 09. Charging the whole sample to its starting hour
    keeps the daily total right but ruins the hourly shape, which is the reason
    the buckets are hourly at all.
    """
    start = local_time(sample.start, sample.utc_offset_minutes)
    end = local_time(sample.end, sample.utc_offset_minutes)
    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return [_Portion(*_hour_key(start), value, sample.utc_offset_minutes)]

    portions: list[_Portion] = []
    cursor = start
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=1
        )
        slice_end = min(next_hour, end)
        share = (slice_end - cursor).total_seconds() / total_seconds
        portions.append(
            _Portion(*_hour_key(cursor), value * share, sample.utc_offset_minutes)
        )
        cursor = slice_end
    return portions


def _accumulate(kind: MetricKind, portions: Iterable[_Portion]) -> list[HourBucket]:
    """Collapse portions sharing a local hour into one bucket each."""
    grouped: dict[tuple[date, int], list[_Portion]] = {}
    for portion in portions:
        grouped.setdefault((portion.local_date, portion.hour), []).append(portion)

    buckets: list[HourBucket] = []
    for (local_date, hour), group in sorted(grouped.items()):
        values = [portion.value for portion in group]
        # Cumulative hours add up; discrete hours hold the mean of their
        # readings, which `sample_count` later re-weights into the day.
        value = (
            sum(values) if kind is MetricKind.CUMULATIVE else sum(values) / len(values)
        )
        buckets.append(
            HourBucket(
                local_date=local_date,
                hour=hour,
                value=value,
                sample_count=len(group),
                min_value=min(values),
                max_value=max(values),
                # The repeated DST hour holds samples recorded at two different
                # offsets. The earliest one wins: it is the offset the hour
                # started at, and the field only ever serves to explain a bucket
                # back to a human.
                utc_offset_minutes=group[0].utc_offset_minutes,
            )
        )
    return buckets


def aggregate_samples(
    samples: Sequence[RawSample], kind: MetricKind, canonical_unit: str
) -> list[HourBucket]:
    """
    Turn one metric's raw samples into local hourly buckets, in calendar order.

    Raises `UnitError` if any sample carries a unit that cannot become
    `canonical_unit`; the caller is expected to fail the whole chunk rather than
    drop the offending sample, because a chunk is re-sent cheaply and a silently
    missing hour is never noticed.
    """
    portions: list[_Portion] = []
    for sample in samples:
        value = canonicalize(sample.value, sample.unit, canonical_unit)
        if kind is MetricKind.CUMULATIVE:
            portions.extend(_split_cumulative(sample, value))
        else:
            # A discrete sample is a reading, not an amount: it belongs to the
            # hour it was taken in and is not divisible across hours.
            local_start = local_time(sample.start, sample.utc_offset_minutes)
            portions.append(
                _Portion(*_hour_key(local_start), value, sample.utc_offset_minutes)
            )
    return _accumulate(kind, portions)


# --- Daily fold -------------------------------------------------------------


def fold_daily(
    kind: MetricKind, *, value_sum: float, weighted_sum: float, count_sum: int
) -> float | None:
    """
    One day's number, from the three sums a `GROUP BY local_date` produces.

    The formula lives here rather than in SQL so that the case that matters —
    `SUM(value * sample_count) / SUM(sample_count)`, not the average of hourly
    averages — is stated once and tested without a database. Returns `None` for
    a discrete metric with no readings: an absent measurement is not a zero.
    """
    if kind is MetricKind.CUMULATIVE:
        return value_sum
    if count_sum == 0:
        return None
    return weighted_sum / count_sum
