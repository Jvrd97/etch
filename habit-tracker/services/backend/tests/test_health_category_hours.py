# [review:need-review] PHASE-03/272
# summary: category types folded into hours — minutes of overlapping iPhone and Watch sessions counted once, events counted at the hour of their last moment and once per interval, "did not happen" values (idle stand hour, symptom not present) not counted; the same through POST /health/samples
"""
Category types that land in hourly buckets (`app.health.categories`).

Sleep folds into nights; every other category type in the catalogue is
`cumulative` in minutes (a mindful session) or in counts (a stand hour, a
heart-rate notification, a symptom). iPhone and Watch write their own copies of
the same minutes, so the fold has to count each moment once.
"""

from datetime import date, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from app.health.aggregate import HourBucket
from app.health.categories import CategoryInterval, category_hours
from app.models import HealthHourBucket, HealthMetric

MINDFUL = "HKCategoryTypeIdentifierMindfulSession"
STAND_HOUR = "HKCategoryTypeIdentifierAppleStandHour"
HIGH_HEART_RATE = "HKCategoryTypeIdentifierHighHeartRateEvent"
HEADACHE = "HKCategoryTypeIdentifierHeadache"
BERLIN = 120
DAY = date(2026, 10, 20)

# Raw HealthKit values.
NOT_APPLICABLE = 0
STOOD, IDLE = 0, 1
NOT_PRESENT, MILD = 1, 2


def at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def interval(value: int, start: str, end: str) -> CategoryInterval:
    return CategoryInterval(
        value=value, start=at(start), end=at(end), utc_offset_minutes=BERLIN
    )


def hours(buckets: list[HourBucket]) -> list[tuple[date, int, float]]:
    return [(b.local_date, b.hour, round(b.value, 6)) for b in buckets]


def test_minutes_of_iphone_and_watch_over_the_same_session_count_once() -> None:
    iphone = interval(NOT_APPLICABLE, "2026-10-20T08:00:00Z", "2026-10-20T08:30:00Z")
    watch = interval(NOT_APPLICABLE, "2026-10-20T08:10:00Z", "2026-10-20T08:40:00Z")

    buckets = category_hours(MINDFUL, [iphone, watch], "min")

    # 10:00-10:40 Berlin: forty minutes, not sixty.
    assert hours(buckets) == [(DAY, 10, 40)]


def test_merged_minutes_still_split_across_the_hours_they_cover() -> None:
    iphone = interval(NOT_APPLICABLE, "2026-10-20T07:50:00Z", "2026-10-20T08:05:00Z")
    watch = interval(NOT_APPLICABLE, "2026-10-20T08:00:00Z", "2026-10-20T08:10:00Z")
    later = interval(NOT_APPLICABLE, "2026-10-20T09:00:00Z", "2026-10-20T09:15:00Z")

    buckets = category_hours(MINDFUL, [later, watch, iphone], "min")

    assert hours(buckets) == [(DAY, 9, 10), (DAY, 10, 10), (DAY, 11, 15)]


def test_a_stood_hour_counts_once_in_its_own_hour_and_an_idle_one_not_at_all() -> None:
    stood = interval(STOOD, "2026-10-20T08:00:00Z", "2026-10-20T09:00:00Z")
    idle = interval(IDLE, "2026-10-20T09:00:00Z", "2026-10-20T10:00:00Z")
    watch_copy = interval(STOOD, "2026-10-20T08:00:00Z", "2026-10-20T09:00:00Z")

    buckets = category_hours(STAND_HOUR, [stood, idle, watch_copy], "count")

    # 10:00-11:00 Berlin ends on the hour: it belongs to hour 10, not 11.
    assert hours(buckets) == [(DAY, 10, 1)]


def test_an_event_counts_at_the_hour_it_ends_whatever_part_of_it_is_sent() -> None:
    whole = interval(NOT_APPLICABLE, "2026-10-20T07:50:00Z", "2026-10-20T08:20:00Z")
    clipped_to_a_window = interval(
        NOT_APPLICABLE, "2026-10-20T08:00:00Z", "2026-10-20T08:20:00Z"
    )

    assert hours(category_hours(HIGH_HEART_RATE, [whole], "count")) == [(DAY, 10, 1)]
    assert hours(category_hours(HIGH_HEART_RATE, [clipped_to_a_window], "count")) == [
        (DAY, 10, 1)
    ]


def test_a_symptom_marked_not_present_is_not_counted() -> None:
    present = interval(MILD, "2026-10-20T08:00:00Z", "2026-10-20T08:00:00Z")
    absent = interval(NOT_PRESENT, "2026-10-20T09:00:00Z", "2026-10-20T09:00:00Z")

    assert hours(category_hours(HEADACHE, [present, absent], "count")) == [(DAY, 10, 1)]


def test_value_one_counts_for_a_type_where_it_is_the_event_itself() -> None:
    # HKCategoryValueLowCardioFitnessEvent.lowFitness is 1: an event, not an absence.
    low_fitness = interval(1, "2026-10-20T08:00:00Z", "2026-10-20T08:00:00Z")

    buckets = category_hours(
        "HKCategoryTypeIdentifierLowCardioFitnessEvent", [low_fitness], "count"
    )

    assert hours(buckets) == [(DAY, 10, 1)]


# --- HTTP surface -----------------------------------------------------------


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def sample(identifier: str, value: int, start: str, end: str) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "value": value,
        "start": start,
        "end": end,
        "utc_offset_minutes": BERLIN,
    }


async def test_mindful_minutes_from_iphone_and_watch_land_once_in_the_hour(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(
        "/api/v1/health/samples",
        json={
            "samples": [],
            "category_samples": [
                sample(MINDFUL, 0, "2026-10-20T08:00:00Z", "2026-10-20T08:30:00Z"),
                sample(MINDFUL, 0, "2026-10-20T08:10:00Z", "2026-10-20T08:40:00Z"),
            ],
        },
    )
    assert response.status_code == 200, response.text

    rows = (
        await db_session.execute(
            select(HealthHourBucket.hour, HealthHourBucket.value)
            .join(HealthMetric)
            .where(HealthMetric.identifier == MINDFUL)
        )
    ).all()
    assert [(hour, round(value, 6)) for hour, value in rows] == [(10, 40)]
