# [review:need-review] PHASE-02/69
# summary: the personal baseline of a Health metric — mean and spread of the metric's own preceding days, a deviation only with enough history, gaps ignored, and the list endpoint serving it at a statement count that does not grow with the number of metrics
"""
Baseline arithmetic and its appearance in `GET /health/metrics`.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from app.health.baseline import (
    BASELINE_DAYS,
    MIN_BASELINE_DAYS,
    compute_baseline,
)
from tests.conftest import test_engine

STEPS = "HKQuantityTypeIdentifierStepCount"
HEART = "HKQuantityTypeIdentifierHeartRate"
SAMPLES_URL = "/api/v1/health/samples"
METRICS_URL = "/api/v1/health/metrics"
TODAY = date(2026, 7, 20)


def run_of(values: list[float], last: date = TODAY) -> dict[date, float]:
    return {last - timedelta(days=len(values) - 1 - i): v for i, v in enumerate(values)}


def test_baseline_is_the_mean_of_the_preceding_days_and_excludes_the_latest() -> None:
    by_day = run_of([100.0] * 10 + [150.0])
    result = compute_baseline(by_day, TODAY)
    assert result is not None
    assert result.days == 10
    assert result.mean == 100.0
    assert result.stddev == 0.0
    assert result.deviation == 50.0
    assert result.outside_typical is True


def test_a_value_inside_the_usual_spread_is_not_outside() -> None:
    by_day = run_of([90.0, 110.0] * 5 + [105.0])
    result = compute_baseline(by_day, TODAY)
    assert result is not None
    assert result.mean == 100.0
    assert result.deviation == 5.0
    assert result.outside_typical is False


def test_short_history_gives_no_baseline() -> None:
    by_day = run_of([100.0] * MIN_BASELINE_DAYS)  # the latest day leaves one short
    assert compute_baseline(by_day, TODAY) is None


def test_a_single_point_gives_no_baseline() -> None:
    assert compute_baseline({TODAY: 5.0}, TODAY) is None


def test_gaps_shrink_the_day_count_but_do_not_break_the_mean() -> None:
    by_day = {
        TODAY - timedelta(days=offset): 100.0
        for offset in range(1, BASELINE_DAYS + 1)
        if offset % 2 == 0
    }
    by_day[TODAY] = 100.0
    result = compute_baseline(by_day, TODAY)
    assert result is not None
    assert result.days == BASELINE_DAYS // 2
    assert result.mean == 100.0


def test_days_older_than_the_baseline_period_are_not_counted() -> None:
    by_day = run_of([1000.0] * 5 + [100.0] * BASELINE_DAYS + [100.0])
    result = compute_baseline(by_day, TODAY)
    assert result is not None
    assert result.days == BASELINE_DAYS
    assert result.mean == 100.0


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def steps_on(day: date, value: float) -> dict[str, Any]:
    stamp = f"{day.isoformat()}T10:00:00Z"
    return {
        "identifier": STEPS,
        "value": value,
        "unit": "count",
        "start": stamp,
        "end": stamp,
        "utc_offset_minutes": 0,
    }


async def list_metrics(client: AsyncClient, date_from: date) -> dict[str, Any]:
    response = await client.get(
        METRICS_URL,
        params={"date_from": date_from.isoformat(), "date_to": TODAY.isoformat()},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_the_list_carries_the_baseline_although_it_asks_for_one_day(
    client: AsyncClient,
) -> None:
    samples = [steps_on(TODAY - timedelta(days=i), 1000.0) for i in range(1, 15)]
    samples.append(steps_on(TODAY, 1500.0))
    response = await client.post(SAMPLES_URL, json={"samples": samples})
    assert response.status_code == 200, response.text

    body = await list_metrics(client, TODAY)
    steps = next(m for m in body["metrics"] if m["identifier"] == STEPS)
    assert [d["date"] for d in steps["days"]] == [TODAY.isoformat()]
    assert steps["baseline"]["mean"] == 1000.0
    assert steps["baseline"]["days"] == 14
    assert steps["baseline"]["deviation"] == 500.0
    heart = next(m for m in body["metrics"] if m["identifier"] == HEART)
    assert heart["days"] == []
    assert heart["baseline"] is None


async def count_statements(client: AsyncClient) -> int:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        await list_metrics(client, TODAY - timedelta(days=29))
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)
    return len(statements)


async def test_statements_do_not_grow_with_the_number_of_metrics_filled(
    client: AsyncClient,
) -> None:
    """The class of error: a baseline query per metric."""
    first = [steps_on(TODAY - timedelta(days=i), 1000.0) for i in range(10)]
    response = await client.post(SAMPLES_URL, json={"samples": first})
    assert response.status_code == 200, response.text
    small = await count_statements(client)

    stamp = f"{TODAY.isoformat()}T09:00:00Z"
    more = [
        {
            "identifier": identifier,
            "value": 60.0,
            "unit": unit,
            "start": stamp,
            "end": stamp,
            "utc_offset_minutes": 0,
        }
        for identifier, unit in (
            (HEART, "count/min"),
            ("HKQuantityTypeIdentifierRestingHeartRate", "count/min"),
        )
    ]
    response = await client.post(SAMPLES_URL, json={"samples": more})
    assert response.status_code == 200, response.text
    large = await count_statements(client)

    assert large == small
