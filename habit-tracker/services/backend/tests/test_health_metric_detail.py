# [review:need-review] PHASE-02/68
# summary: GET /health/metrics/{identifier}/days and /hours — the daily series of one metric and the hours of one day: empty hours absent (the screen draws them), min/max of a discrete hour, a one-sample hour, a DST day, the same numbers as the daily list, refusals (unknown metric, sleep has no hours, reversed range), and a statement count that does not grow with the data
"""
The detail screen of one Health metric on the HTTP surface.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from tests.conftest import test_engine

STEPS = "HKQuantityTypeIdentifierStepCount"
HEART = "HKQuantityTypeIdentifierHeartRate"
SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
BERLIN_SUMMER = 120
BERLIN_WINTER = 60

SAMPLES_URL = "/api/v1/health/samples"
METRICS_URL = "/api/v1/health/metrics"


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def sample(
    identifier: str,
    value: float,
    unit: str,
    start: str,
    end: str | None = None,
    offset: int = BERLIN_SUMMER,
) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "value": value,
        "unit": unit,
        "start": start,
        "end": end or start,
        "utc_offset_minutes": offset,
    }


async def post(client: AsyncClient, samples: list[dict[str, Any]]) -> None:
    response = await client.post(SAMPLES_URL, json={"samples": samples})
    assert response.status_code == 200, response.text


async def hours(client: AsyncClient, identifier: str, day: str) -> dict[str, Any]:
    response = await client.get(
        f"{METRICS_URL}/{identifier}/hours", params={"date": day}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def days(
    client: AsyncClient, identifier: str, date_from: str, date_to: str
) -> dict[str, Any]:
    response = await client.get(
        f"{METRICS_URL}/{identifier}/days",
        params={"date_from": date_from, "date_to": date_to},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# 20 July 2026, Berlin (UTC+2): steps at 08:00 and 18:00, heart at 05:00 (two
# readings) and 11:00 (one reading).
DAY = [
    sample(STEPS, 1200, "count", "2026-07-20T06:00:00Z", "2026-07-20T06:30:00Z"),
    sample(STEPS, 800, "count", "2026-07-20T16:00:00Z", "2026-07-20T16:20:00Z"),
    sample(HEART, 54, "count/min", "2026-07-20T03:00:00Z"),
    sample(HEART, 58, "count/min", "2026-07-20T03:20:00Z"),
    sample(HEART, 90, "count/min", "2026-07-20T09:00:00Z"),
]


async def test_hours_of_a_day_hold_only_hours_that_have_data(
    client: AsyncClient,
) -> None:
    await post(client, DAY)

    body = await hours(client, STEPS, "2026-07-20")

    assert body["identifier"] == STEPS
    assert body["kind"] == "cumulative"
    assert body["canonical_unit"] == "count"
    assert [(h["hour"], h["value"]) for h in body["hours"]] == [(8, 1200), (18, 800)]


async def test_a_discrete_hour_carries_its_range_and_a_one_sample_hour_has_equal_ends(
    client: AsyncClient,
) -> None:
    await post(client, DAY)

    body = await hours(client, HEART, "2026-07-20")

    early, late = body["hours"]
    assert (early["hour"], early["value"], early["min"], early["max"]) == (
        5,
        56,
        54,
        58,
    )
    assert early["sample_count"] == 2
    assert (late["hour"], late["value"], late["min"], late["max"]) == (11, 90, 90, 90)
    assert late["sample_count"] == 1


async def test_a_day_without_data_is_an_empty_list_not_an_error(
    client: AsyncClient,
) -> None:
    body = await hours(client, STEPS, "2026-07-21")

    assert body["hours"] == []


async def test_the_day_sums_hours_to_the_number_the_daily_list_shows(
    client: AsyncClient,
) -> None:
    await post(client, DAY)

    hourly = await hours(client, STEPS, "2026-07-20")
    series = await days(client, STEPS, "2026-07-20", "2026-07-20")

    assert series["days"] == [{"date": "2026-07-20", "value": 2000}]
    assert sum(h["value"] for h in hourly["hours"]) == 2000
    listed = (
        await client.get(
            METRICS_URL,
            params={
                "date_from": "2026-07-20",
                "date_to": "2026-07-20",
            },
        )
    ).json()["metrics"]
    in_list = next(m for m in listed if m["identifier"] == STEPS)
    assert in_list["days"] == series["days"]


async def test_a_discrete_day_is_the_weighted_mean_not_the_mean_of_hours(
    client: AsyncClient,
) -> None:
    await post(client, DAY)

    series = await days(client, HEART, "2026-07-20", "2026-07-20")

    # (56 * 2 + 90 * 1) / 3, not (56 + 90) / 2.
    assert series["days"][0]["value"] == pytest.approx(202 / 3)


async def test_the_day_the_clocks_go_back_reads_without_a_hole(
    client: AsyncClient,
) -> None:
    # 25 October 2026: Berlin leaves summer time at 03:00 -> 02:00. The first
    # 02:xx is UTC+2, the second UTC+1; both land in local hour 2.
    await post(
        client,
        [
            sample(STEPS, 100, "count", "2026-10-25T00:10:00Z", offset=BERLIN_SUMMER),
            sample(STEPS, 50, "count", "2026-10-25T01:10:00Z", offset=BERLIN_WINTER),
            sample(STEPS, 70, "count", "2026-10-25T02:10:00Z", offset=BERLIN_WINTER),
        ],
    )

    body = await hours(client, STEPS, "2026-10-25")

    assert [(h["hour"], h["value"]) for h in body["hours"]] == [(2, 150), (3, 70)]
    series = await days(client, STEPS, "2026-10-25", "2026-10-25")
    assert series["days"][0]["value"] == 220


async def test_the_days_of_a_range_come_oldest_first(client: AsyncClient) -> None:
    await post(
        client,
        [
            sample(STEPS, 10, "count", "2026-07-22T06:00:00Z"),
            sample(STEPS, 30, "count", "2026-07-20T06:00:00Z"),
        ],
    )

    series = await days(client, STEPS, "2026-07-19", "2026-07-23")

    assert [d["date"] for d in series["days"]] == ["2026-07-20", "2026-07-22"]


async def test_an_unknown_metric_is_not_found(client: AsyncClient) -> None:
    response = await client.get(
        f"{METRICS_URL}/HKQuantityTypeIdentifierNope/hours",
        params={"date": "2026-07-20"},
    )
    assert response.status_code == 404

    response = await client.get(
        f"{METRICS_URL}/HKQuantityTypeIdentifierNope/days",
        params={"date_from": "2026-07-20", "date_to": "2026-07-20"},
    )
    assert response.status_code == 404


async def test_sleep_has_no_hours(client: AsyncClient) -> None:
    response = await client.get(
        f"{METRICS_URL}/{SLEEP}/hours", params={"date": "2026-07-20"}
    )

    assert response.status_code == 422


async def test_a_reversed_range_is_refused(client: AsyncClient) -> None:
    response = await client.get(
        f"{METRICS_URL}/{STEPS}/days",
        params={"date_from": "2026-07-21", "date_to": "2026-07-20"},
    )

    assert response.status_code == 422


async def count_statements(
    client: AsyncClient, url: str, params: dict[str, str]
) -> int:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        response = await client.get(url, params=params)
        assert response.status_code == 200, response.text
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)
    return len(statements)


async def test_statements_do_not_grow_with_the_data(client: AsyncClient) -> None:
    hours_url = f"{METRICS_URL}/{STEPS}/hours"
    days_url = f"{METRICS_URL}/{STEPS}/days"
    day_params = {"date": "2026-07-20"}
    range_params = {"date_from": "2026-07-01", "date_to": "2026-07-31"}
    await post(client, DAY[:1])
    hours_before = await count_statements(client, hours_url, day_params)
    days_before = await count_statements(client, days_url, range_params)

    await post(
        client,
        [
            sample(STEPS, 5, "count", f"2026-07-{d:02d}T{h:02d}:00:00Z")
            for d in range(1, 29)
            for h in range(0, 22, 3)
        ],
    )

    assert await count_statements(client, hours_url, day_params) == hours_before
    assert await count_statements(client, days_url, range_params) == days_before
