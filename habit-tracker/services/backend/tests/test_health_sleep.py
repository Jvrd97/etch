# [review:need-review] PHASE-03/238
# summary: pure tests of the sleep fold — a night across midnight lands on its wake date, the 18:00 boundary, iPhone and Watch over the same minutes counted once, stage priority, a nap does not move bedtime or wake time, an empty input is no night, unknown stage values refused
"""
The night fold of `app.health.sleep`, without a database.

A night is identified by the local date the person woke up on; every interval
ending between 18:00 the evening before and 18:00 that day belongs to it.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.health.sleep import (
    SleepInterval,
    SleepStage,
    SleepValueError,
    fold_nights,
    stage_of,
)

BERLIN = 120  # minutes east of UTC, summer
UTC = timezone.utc


def at(text: str) -> datetime:
    """A UTC instant from 'YYYY-MM-DDTHH:MM'."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def interval(
    stage: SleepStage, start: str, end: str, offset: int = BERLIN
) -> SleepInterval:
    return SleepInterval(
        stage=stage, start=at(start), end=at(end), utc_offset_minutes=offset
    )


def test_a_night_across_midnight_lands_on_the_wake_date() -> None:
    # 23:30 Monday → 07:00 Tuesday in Berlin.
    (night,) = fold_nights(
        [interval(SleepStage.ASLEEP_CORE, "2026-10-19T21:30", "2026-10-20T05:00")]
    )

    assert night.wake_date == date(2026, 10, 20)
    assert night.asleep_min == 450
    assert night.core_min == 450
    assert night.bedtime == at("2026-10-19T21:30")
    assert night.wake_time == at("2026-10-20T05:00")
    assert night.utc_offset_minutes == BERLIN


def test_the_part_before_midnight_and_the_part_after_are_one_night() -> None:
    nights = fold_nights(
        [
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T20:00", "2026-10-19T21:59"),
            interval(SleepStage.ASLEEP_DEEP, "2026-10-19T22:00", "2026-10-20T01:00"),
        ]
    )

    assert [n.wake_date for n in nights] == [date(2026, 10, 20)]
    assert nights[0].core_min == 119
    assert nights[0].deep_min == 180


def test_the_day_boundary_is_six_in_the_evening_local() -> None:
    nights = fold_nights(
        [
            # Ends 17:59 Berlin: still Monday's sleep (a nap).
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T15:00", "2026-10-19T15:59"),
            # Ends 18:30 Berlin: already the night that ends on Tuesday.
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T16:00", "2026-10-19T16:30"),
        ]
    )

    assert [n.wake_date for n in nights] == [date(2026, 10, 19), date(2026, 10, 20)]


def test_iphone_and_watch_over_the_same_minutes_are_not_added_up() -> None:
    # The phone says "in bed" for the whole night, the watch has stages inside,
    # and a third-party app repeats the watch's core sleep.
    (night,) = fold_nights(
        [
            interval(SleepStage.IN_BED, "2026-10-19T21:00", "2026-10-20T05:00"),
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T21:30", "2026-10-20T01:00"),
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T21:30", "2026-10-20T01:00"),
            interval(SleepStage.ASLEEP_DEEP, "2026-10-20T01:00", "2026-10-20T02:00"),
            interval(SleepStage.ASLEEP_REM, "2026-10-20T02:00", "2026-10-20T04:00"),
            interval(SleepStage.AWAKE, "2026-10-20T04:00", "2026-10-20T04:30"),
        ]
    )

    assert night.in_bed_min == 480
    assert (night.core_min, night.deep_min, night.rem_min) == (210, 60, 120)
    assert night.asleep_min == 390
    assert night.awake_min == 30
    assert night.bedtime == at("2026-10-19T21:00")
    assert night.wake_time == at("2026-10-20T05:00")


def test_a_detailed_stage_wins_over_an_unspecified_one_on_the_same_minutes() -> None:
    (night,) = fold_nights(
        [
            interval(
                SleepStage.ASLEEP_UNSPECIFIED, "2026-10-19T22:00", "2026-10-20T04:00"
            ),
            interval(SleepStage.ASLEEP_DEEP, "2026-10-19T23:00", "2026-10-20T00:00"),
            interval(SleepStage.AWAKE, "2026-10-20T01:00", "2026-10-20T01:20"),
        ]
    )

    assert night.deep_min == 60
    assert night.awake_min == 20
    assert night.unspecified_min == 280
    assert night.asleep_min == 340


def test_a_nap_counts_as_sleep_but_does_not_move_bedtime_or_wake_time() -> None:
    nights = fold_nights(
        [
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T21:00", "2026-10-20T05:00"),
            # 14:00-14:40 Berlin on Tuesday: same wake date, a separate session.
            interval(SleepStage.ASLEEP_CORE, "2026-10-20T12:00", "2026-10-20T12:40"),
        ]
    )

    (night,) = nights
    assert night.asleep_min == 520
    assert night.bedtime == at("2026-10-19T21:00")
    assert night.wake_time == at("2026-10-20T05:00")


def test_a_short_wake_in_the_night_does_not_split_the_session() -> None:
    (night,) = fold_nights(
        [
            interval(SleepStage.ASLEEP_CORE, "2026-10-19T21:00", "2026-10-20T00:00"),
            interval(SleepStage.ASLEEP_CORE, "2026-10-20T00:40", "2026-10-20T05:00"),
        ]
    )

    assert night.bedtime == at("2026-10-19T21:00")
    assert night.wake_time == at("2026-10-20T05:00")
    assert night.asleep_min == 440


def test_no_intervals_is_no_night_and_empty_intervals_are_ignored() -> None:
    assert fold_nights([]) == []
    assert (
        fold_nights(
            [interval(SleepStage.ASLEEP_CORE, "2026-10-20T03:00", "2026-10-20T03:00")]
        )
        == []
    )


def test_the_wake_date_follows_the_offset_the_device_lived_at() -> None:
    # 04:30 UTC is 23:30 the evening before in New York (UTC-5): that is the
    # bedtime of the night that ends on the 20th, not a night of the 20th by UTC.
    (night,) = fold_nights(
        [
            interval(
                SleepStage.ASLEEP_CORE,
                "2026-10-20T04:30",
                "2026-10-20T11:30",
                offset=-300,
            )
        ]
    )

    assert night.wake_date == date(2026, 10, 20)
    assert night.utc_offset_minutes == -300
    assert night.wake_time - night.bedtime == timedelta(hours=7)


@pytest.mark.parametrize(
    ("raw", "stage"),
    [
        (0, SleepStage.IN_BED),
        (1, SleepStage.ASLEEP_UNSPECIFIED),
        (2, SleepStage.AWAKE),
        (3, SleepStage.ASLEEP_CORE),
        (4, SleepStage.ASLEEP_DEEP),
        (5, SleepStage.ASLEEP_REM),
    ],
)
def test_stage_values_are_healthkits_raw_values(raw: int, stage: SleepStage) -> None:
    assert stage_of(raw) is stage


@pytest.mark.parametrize("raw", [-1, 6, 42])
def test_an_unknown_stage_value_is_refused(raw: int) -> None:
    with pytest.raises(SleepValueError):
        stage_of(raw)
