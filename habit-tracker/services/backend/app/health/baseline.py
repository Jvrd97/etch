# [review:need-review] PHASE-02/69
# summary: the personal baseline of a Health metric — mean and spread of the metric's own days before the latest one, and how far the latest day sits from it; pure functions over a day-to-value map, reused by the list endpoint and by later insight prompts
"""
A metric against its own history.

The baseline is the mean and the spread of the same metric's daily values over
the `BASELINE_DAYS` days *before* the latest day. The latest day is left out so
a spike cannot raise the very yardstick it is measured against. No population
norm is involved: the comparison is always "you against you", which holds for
anyone and needs no calibration.

Days without a measurement are absent from the map and are simply not counted:
a gap is not a zero. With fewer than `MIN_BASELINE_DAYS` days behind it the
baseline does not exist, and the screen shows no deviation instead of a false one.

**Which metrics have a baseline.** Quantity types (`HKQuantityType…`) and sleep.
Every other category type — event, symptom, minutes of a session — has none, and
the catalog's `kind` cannot tell them apart: a category counted in minutes or
events is `cumulative` like steps. The gate is therefore the source type, the
identifier prefix `CATEGORY_PREFIX`, with sleep (a category folded into nights)
let through by its `sleep` kind. Such a category has none: for them a missing day may mean "zero events" or
"nothing recorded", and that is not decided, so a mean over the recorded days
would be a guess. The gate reads the catalog's `kind`, not a list of names.

**Today is not compared for cumulative metrics.** The day still being lived holds
only part of the steps or kilocalories it will end with; against whole days it
would read as a false drop every morning. A cumulative metric is compared on the
last day before the range's end (the latest whole day); discrete metrics and sleep
use the last shown day.

**A flat history is not infinitely steady.** With zero spread any difference would
be "outside the usual", so the spread used for that judgement has a floor
(`MIN_SPREAD_SHARE` of the mean, never below `MIN_SPREAD_ABSOLUTE`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean, pstdev

from app.health.aggregate import MetricKind
from app.health.categories import CATEGORY_PREFIX

BASELINE_DAYS = 30
MIN_BASELINE_DAYS = 7
# The latest day is "outside the usual" when it is further from the mean than
# this many standard deviations of the baseline days.
OUTSIDE_STDDEVS = 1.5
# Floor of the spread used for "outside the usual": a share of the mean, and an
# absolute minimum for a mean near zero.
MIN_SPREAD_SHARE = 0.05
MIN_SPREAD_ABSOLUTE = 0.01
BASELINE_KINDS = frozenset(
    {MetricKind.CUMULATIVE, MetricKind.DISCRETE, MetricKind.SLEEP}
)


@dataclass(frozen=True)
class Baseline:
    """The metric's usual level and where the latest day stands against it."""

    mean: float
    stddev: float
    days: int
    deviation: float
    outside_typical: bool


def compute_baseline(by_day: dict[date, float], latest_day: date) -> Baseline | None:
    """Baseline of the days before `latest_day`; `None` when there are too few of them."""
    start = latest_day - timedelta(days=BASELINE_DAYS)
    latest = by_day.get(latest_day)
    values = [value for day, value in by_day.items() if start <= day < latest_day]
    if latest is None or len(values) < MIN_BASELINE_DAYS:
        return None
    mean = fmean(values)
    stddev = pstdev(values)
    deviation = latest - mean
    spread = max(stddev, MIN_SPREAD_SHARE * abs(mean), MIN_SPREAD_ABSOLUTE)
    return Baseline(
        mean=mean,
        stddev=stddev,
        days=len(values),
        deviation=deviation,
        outside_typical=abs(deviation) > OUTSIDE_STDDEVS * spread,
    )


def metric_baseline(
    identifier: str,
    kind: str,
    by_day: dict[date, float],
    date_from: date,
    date_to: date,
) -> Baseline | None:
    """
    Baseline of one catalog metric for the range `date_from..date_to`.

    `by_day` holds the metric's history, reaching `BASELINE_DAYS` before `date_from`.
    """
    try:
        metric_kind = MetricKind(kind)
    except ValueError:
        return None
    if metric_kind not in BASELINE_KINDS:
        return None
    if metric_kind != MetricKind.SLEEP and identifier.startswith(CATEGORY_PREFIX):
        return None
    shown = [
        day
        for day in by_day
        if date_from <= day <= date_to
        and (metric_kind != MetricKind.CUMULATIVE or day < date_to)
    ]
    if not shown:
        return None
    return compute_baseline(by_day, max(shown))
