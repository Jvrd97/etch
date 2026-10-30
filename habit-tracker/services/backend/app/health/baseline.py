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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean, pstdev

BASELINE_DAYS = 30
MIN_BASELINE_DAYS = 7
# The latest day is "outside the usual" when it is further from the mean than
# this many standard deviations of the baseline days.
OUTSIDE_STDDEVS = 1.5


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
    return Baseline(
        mean=mean,
        stddev=stddev,
        days=len(values),
        deviation=deviation,
        outside_typical=abs(deviation) > OUTSIDE_STDDEVS * stddev,
    )
