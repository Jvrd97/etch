# [review:need-review] PHASE-03/priemka-5.7
# summary: tests of hours_and_minutes() — the single rendering of a duration the verdict clause and the Friday report both print
"""
Продолжительность словами.

Строку читают в двух местах — расшифровка клауза переработки и блок пятничного
отчёта, — и до слияния каждое место писало её само. Тест держит одну.
"""

from __future__ import annotations

from app.core.humanize import hours_and_minutes


def test_whole_hour_keeps_the_zero_minutes() -> None:
    """Ноль минут печатается: «8 ч» и «8 ч 0 мин» читаются одинаково точно."""
    assert hours_and_minutes(480) == "8 ч 0 мин"


def test_hours_and_the_rest() -> None:
    assert hours_and_minutes(545) == "9 ч 5 мин"


def test_below_an_hour_is_zero_hours() -> None:
    assert hours_and_minutes(45) == "0 ч 45 мин"
