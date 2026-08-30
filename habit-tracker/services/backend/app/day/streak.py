# [review:need-review] PHASE-03/90
# summary: the streak of won days as one pure step — a won day adds one, a lost day zeroes it, and Sunday and an unclosed day leave it exactly where it was
"""
How long the run of won days is, decided without a database.

One function, because the whole rule is one sentence with two exceptions.

**Воскресенье стрик не рвёт.** It does not lengthen it either, and the symmetry
is deliberate: a Sunday that could add a point but never subtract one would turn
the streak into a number a person can pad with a good Sunday, which is the
opposite of what it measures. Sunday is outside the game in both directions.

**A day nobody closed changes nothing.** Its verdict is `null` — silence rather
than a loss — and a streak that broke on silence would count "я не дошёл до
закрытия" as "я проиграл", which is the distinction `#88` and this ticket both
exist to keep.

`app.crud.summary.recompute_history` folds this over the days in date order and
writes the result into `day_summary.streak_after`. Nothing else computes a
streak of days.
"""

from __future__ import annotations

from datetime import date

from app.day.evaluate import VERDICT_WON

__all__ = ["SUNDAY", "step_streak"]

# ISO weekday number, the one `date.isoweekday()` returns.
SUNDAY = 7


def step_streak(current: int, on: date, verdict: str | None) -> int:
    """The streak after the day `on`, given what it was before it."""
    if verdict is None or on.isoweekday() == SUNDAY:
        return current
    return current + 1 if verdict == VERDICT_WON else 0
