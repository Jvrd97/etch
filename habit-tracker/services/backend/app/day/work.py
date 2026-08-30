# [review:need-review] PHASE-03/91
# summary: pure arithmetic of measured work — the minutes one interval contributes (an open one counts up to now, clamped to the end of its own day), the day's sum over `mode='work'`, and the rule that no intervals at all means «не измерено» rather than zero
"""
How many minutes of work a day holds, decided without a database.

**Отсутствие интервалов — не ноль.** `day_work_minutes` answers `None` for a day
nothing was recorded for, exactly as `fold_daily` in `app.health.aggregate`
answers `None` for an empty counter. A zero would say "работал ноль минут" and
`evaluate_day` would then read the day as comfortably inside the ceiling; the
day has to say "не измерено" and skip the overtime check instead. A day that
carries intervals of `mode='off'` only *is* measured, and its answer is zero.

**Открытый интервал считается до сих пор, но не дальше своих суток.** A running
interval has no `ended_at`, and the honest length of it is "from its start to
now". Left uncapped, one forgotten interval would still be running three days
later and would report forty hours; so it is clamped to the end of the day it
belongs to, which `app.core.daytime.day_bounds` — the single answer to where a
day ends — hands over.

Nothing here reads the database or FastAPI, by the same reasoning as
`app.day.evaluate`: the arithmetic of a day's minutes is worth a millisecond
test, not a fixture.

Related: ADR-0014 (day in postgres), Р7.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from app.core.daytime import day_bounds, now_utc

__all__ = [
    "MODES",
    "MODE_OFF",
    "MODE_WORK",
    "SOURCES",
    "SOURCE_AGENT",
    "SOURCE_CORRECTED",
    "SOURCE_MANUAL",
    "IntervalSpan",
    "day_work_minutes",
    "span_minutes",
]

# What the interval says the person was doing. Only `work` adds up: the `off`
# rows exist so that a switch flipped at lunch records the pause rather than
# leaving a hole nobody can tell from "агент не работал".
MODE_WORK: Final = "work"
MODE_OFF: Final = "off"
MODES: tuple[str, ...] = (MODE_WORK, MODE_OFF)

# Who put the interval there. `corrected` is не третий писатель, а состояние:
# an agent's proposal that a person moved, with the proposal kept beside it.
SOURCE_MANUAL: Final = "manual"
SOURCE_AGENT: Final = "agent"
SOURCE_CORRECTED: Final = "corrected"
SOURCES: tuple[str, ...] = (SOURCE_MANUAL, SOURCE_AGENT, SOURCE_CORRECTED)

SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class IntervalSpan:
    """
    One interval reduced to the three fields its length depends on.

    A value rather than the model, so that this module never imports SQLAlchemy
    and the truth table of "how long is an interval" runs without postgres.
    """

    started_at: datetime
    ended_at: datetime | None
    mode: str


def _now(now: datetime | None) -> datetime:
    """The moment an open interval is measured against."""
    return now if now is not None else now_utc()


def span_minutes(span: IntervalSpan, on: date, *, now: datetime | None = None) -> int:
    """
    How many minutes of work `span` contributes to the day `on`.

    An interval of `mode='off'` contributes nothing: it is a recorded pause, not
    a shorter piece of work. An open interval is measured to `now`, and never
    past the end of `on` — a forgotten one would otherwise keep growing after
    the day it belongs to was over.

    Truncated, not rounded: 89 seconds is one minute of work, and rounding up
    would let a handful of short intervals invent an hour that nobody worked.
    """
    if span.mode != MODE_WORK:
        return 0
    if span.ended_at is not None:
        end = span.ended_at
    else:
        _, day_end = day_bounds(on)
        end = min(_now(now), day_end)
    seconds = (end - span.started_at).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // SECONDS_PER_MINUTE)


def day_work_minutes(
    spans: Iterable[IntervalSpan], on: date, *, now: datetime | None = None
) -> int | None:
    """
    The minutes of work recorded for `on`, or None when nothing was recorded.

    `None` is the whole point of the function: it is what makes
    `evaluate_day` skip the overtime check and put `work_minutes` into
    `missing_data` instead of judging a day by a measurement that was never
    taken.
    """
    rows = list(spans)
    if not rows:
        return None
    moment = _now(now)
    return sum(span_minutes(span, on, now=moment) for span in rows)
