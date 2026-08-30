"""
The streak of won days, and the one weekday that is outside it.

Воскресенье стрик не рвёт — and, symmetrically, does not lengthen it either: a
day that is deliberately outside the game cannot be worth a point in it. A day
nobody closed leaves the streak alone as well, for the same reason its verdict
is `null`: silence is not a loss.
"""

# [review:need-review] PHASE-03/90
# summary: tests of step_streak — a won day adds one, a lost day zeroes it, Sunday and an unclosed day change nothing, and a run of days folds to the number the summary stores
from datetime import date

from app.day.evaluate import VERDICT_LOST, VERDICT_WON
from app.day.streak import step_streak

MONDAY = date(2026, 8, 24)
TUESDAY = date(2026, 8, 25)
SATURDAY = date(2026, 8, 29)
SUNDAY_OFF = date(2026, 8, 30)


def run(start: int, days: list[tuple[date, str | None]]) -> list[int]:
    """The streak after each day of a run, as `recompute_history` folds it."""
    current = start
    seen: list[int] = []
    for on, verdict in days:
        current = step_streak(current, on, verdict)
        seen.append(current)
    return seen


def test_a_won_monday_after_nothing_starts_the_streak() -> None:
    assert step_streak(0, MONDAY, VERDICT_WON) == 1


def test_a_lost_tuesday_puts_it_back_to_zero() -> None:
    assert step_streak(3, TUESDAY, VERDICT_LOST) == 0


def test_a_lost_sunday_leaves_the_streak_where_it_was() -> None:
    """Воскресенье вне игры: проиграть в нём нечего."""
    assert SUNDAY_OFF.isoweekday() == 7
    assert step_streak(4, SUNDAY_OFF, VERDICT_LOST) == 4


def test_a_won_sunday_does_not_lengthen_it_either() -> None:
    """
    Symmetry, and it is not decoration.

    A Sunday that could add a point but never subtract one would make the
    streak a number a person can pad by having a good Sunday, which is the
    opposite of what it measures.
    """
    assert step_streak(4, SUNDAY_OFF, VERDICT_WON) == 4


def test_a_day_nobody_closed_changes_nothing() -> None:
    """`verdict is null` — не проигрыш, а молчание."""
    assert step_streak(2, SATURDAY, None) == 2


def test_a_week_folds_to_the_numbers_the_summaries_store() -> None:
    assert run(
        0,
        [
            (MONDAY, VERDICT_WON),
            (TUESDAY, VERDICT_WON),
            (date(2026, 8, 26), None),
            (date(2026, 8, 27), VERDICT_LOST),
            (date(2026, 8, 28), VERDICT_WON),
            (SATURDAY, VERDICT_WON),
            (SUNDAY_OFF, VERDICT_LOST),
        ],
    ) == [1, 2, 2, 0, 1, 2, 2]
