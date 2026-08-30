# [review:need-review] PHASE-03/107
# summary: the one day boundary — 04:00 checked from both sides, midnight, both DST weekends, naive input refused, and a signature test that keeps #86 from having to edit call sites
"""
Tests for the single day boundary.

Nothing here touches the database, the network or FastAPI: `local_date()` and
`day_bounds()` are pure functions of a moment and two settings, and a boundary
test that needs postgres is a boundary test that stops being run.

The two DST weekends are covered by walking every minute of the transition and
asserting the two functions agree on all of them. That is the property the
whole phase leans on — a moment belongs to exactly one day — and it is the one
an example-based test misses.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.config import Settings
from app.core.daytime import day_bounds, local_date, today_local

BERLIN = ZoneInfo("Europe/Berlin")

# Last Sunday of March 2026: 02:00 -> 03:00, that local hour never happens.
DST_SPRING = date(2026, 3, 29)
# Last Sunday of October 2026: 03:00 -> 02:00, that local hour happens twice.
DST_AUTUMN = date(2026, 10, 25)


def berlin(
    year: int, month: int, day: int, hour: int, minute: int = 0, *, fold: int = 0
) -> datetime:
    """A wall-clock reading in the configured zone."""
    return datetime(year, month, day, hour, minute, tzinfo=BERLIN, fold=fold)


# --- the boundary itself ---------------------------------------------------


def test_after_midnight_belongs_to_the_previous_day() -> None:
    assert local_date(berlin(2026, 8, 29, 0, 30)) == date(2026, 8, 28)


def test_start_hour_begins_the_day() -> None:
    assert local_date(berlin(2026, 8, 29, 4, 0)) == date(2026, 8, 29)


def test_the_boundary_is_checked_from_both_sides() -> None:
    """One boundary, not two: the minute before it and the minute on it differ."""
    before = local_date(berlin(2026, 8, 29, 3, 59))
    on = local_date(berlin(2026, 8, 29, 4, 0))
    assert before == date(2026, 8, 28)
    assert on == date(2026, 8, 29)
    assert on - before == timedelta(days=1)


def test_the_boundary_is_read_in_the_configured_zone_not_in_the_caller_s() -> None:
    """
    The same instant, spelled in UTC, lands on the same local day.

    02:30 UTC on 2026-08-29 is 04:30 in Berlin, so it is already the new day
    even though its UTC clock reads before 04:00.
    """
    moment = datetime(2026, 8, 29, 2, 30, tzinfo=timezone.utc)
    assert local_date(moment) == date(2026, 8, 29)


def test_late_evening_stays_in_its_own_day() -> None:
    assert local_date(berlin(2026, 8, 29, 23, 59)) == date(2026, 8, 29)


# --- naive input -----------------------------------------------------------


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        local_date(datetime(2026, 8, 29, 0, 30))


def test_naive_datetime_message_names_the_way_out() -> None:
    with pytest.raises(ValueError, match="datetime.now"):
        local_date(datetime(2026, 8, 29, 0, 30))


# --- day_bounds ------------------------------------------------------------


def test_day_bounds_are_utc_and_half_open() -> None:
    start, end = day_bounds(date(2026, 8, 29))
    assert start == datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    assert local_date(start) == date(2026, 8, 29)
    assert local_date(end) == date(2026, 8, 30)


def test_day_bounds_of_neighbouring_days_touch_without_a_gap() -> None:
    _, first_end = day_bounds(date(2026, 8, 29))
    second_start, _ = day_bounds(date(2026, 8, 30))
    assert first_end == second_start


# --- daylight saving -------------------------------------------------------


def assert_bounds_agree_with_local_date(day: date, *, step_minutes: int = 1) -> None:
    """
    Walk the day minute by minute and check the two functions never disagree.

    Also walks two hours past the end, so a moment that fell out of every day
    would show up as a failure rather than as a silent gap.
    """
    start, end = day_bounds(day)
    cursor = start
    while cursor < end:
        assert local_date(cursor) == day, f"{cursor.isoformat()} left day {day}"
        cursor += timedelta(minutes=step_minutes)
    while cursor < end + timedelta(hours=2):
        assert local_date(cursor) == day + timedelta(days=1)
        cursor += timedelta(minutes=step_minutes)


def test_spring_forward_day_is_twenty_three_hours() -> None:
    """
    The short day is the one that contains the 02:00 -> 03:00 jump.

    With a 04:00 boundary that is 2026-03-28, not the calendar date of the
    transition: 02:00 on 2026-03-29 is still the evening of the previous
    logical day.
    """
    short_day = DST_SPRING - timedelta(days=1)
    start, end = day_bounds(short_day)
    assert end - start == timedelta(hours=23)


def test_spring_forward_leaves_no_moment_without_a_day() -> None:
    assert_bounds_agree_with_local_date(DST_SPRING - timedelta(days=1))
    assert_bounds_agree_with_local_date(DST_SPRING)


def test_the_hour_that_never_happens_does_not_split_the_boundary() -> None:
    """03:59 exists on the spring-forward date; 02:30 does not, and both agree."""
    assert local_date(berlin(2026, 3, 29, 3, 59)) == date(2026, 3, 28)
    assert local_date(berlin(2026, 3, 29, 4, 0)) == date(2026, 3, 29)


def test_fall_back_day_is_twenty_five_hours() -> None:
    long_day = DST_AUTUMN - timedelta(days=1)
    start, end = day_bounds(long_day)
    assert end - start == timedelta(hours=25)


def test_both_occurrences_of_the_repeated_hour_are_the_same_day() -> None:
    """
    02:30 on 2026-10-25 happens twice — CEST first, CET an hour later.

    Both are before the 04:00 boundary, so both belong to 2026-10-24. If they
    landed on different days, an evening entry would move once the clocks went
    back.
    """
    first = berlin(2026, 10, 25, 2, 30, fold=0)
    second = berlin(2026, 10, 25, 2, 30, fold=1)
    assert second.astimezone(timezone.utc) - first.astimezone(
        timezone.utc
    ) == timedelta(hours=1)
    assert local_date(first) == local_date(second) == date(2026, 10, 24)


def test_fall_back_leaves_no_moment_without_a_day() -> None:
    assert_bounds_agree_with_local_date(DST_AUTUMN - timedelta(days=1))
    assert_bounds_agree_with_local_date(DST_AUTUMN)


# --- the signature #86 must not have to change -----------------------------


def test_local_date_takes_only_the_moment() -> None:
    """
    `#86` moves the rule into `day_rule_set` by editing this module only.

    A timezone or a start-hour parameter here would turn that move into an edit
    of every call site, so the signature is part of the contract and is
    asserted, not just described.
    """
    parameters = list(inspect.signature(local_date).parameters)
    assert parameters == ["at"]


def test_day_bounds_takes_only_the_date() -> None:
    parameters = list(inspect.signature(day_bounds).parameters)
    assert parameters == ["d"]


def test_today_local_takes_nothing() -> None:
    assert list(inspect.signature(today_local).parameters) == []


def test_today_local_agrees_with_local_date() -> None:
    """The wrapper reads the same clock, it does not carry a rule of its own."""
    before = local_date(datetime.now(timezone.utc))
    now = today_local()
    after = local_date(datetime.now(timezone.utc))
    assert now in (before, after)


# --- the settings source ---------------------------------------------------


def test_defaults_are_berlin_and_four() -> None:
    """`#86` inherits these values; changing them silently would move history."""
    settings = Settings()
    assert settings.APP_TIMEZONE == "Europe/Berlin"
    assert settings.DAY_START_HOUR == 4


def test_unknown_timezone_is_refused_at_settings_build() -> None:
    with pytest.raises(ValueError, match="APP_TIMEZONE"):
        Settings(APP_TIMEZONE="Europe/Berlim")  # type: ignore[call-arg]  # BaseSettings takes **kwargs


def test_start_hour_outside_the_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="DAY_START_HOUR"):
        Settings(DAY_START_HOUR=24)  # type: ignore[call-arg]  # BaseSettings takes **kwargs
