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
    metric_baseline,
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


def test_a_flat_history_does_not_make_every_difference_unusual() -> None:
    by_day = run_of([100.0] * 10 + [101.0])
    result = compute_baseline(by_day, TODAY)
    assert result is not None
    assert result.stddev == 0.0
    assert result.outside_typical is False


def test_a_cumulative_metric_is_compared_on_the_last_whole_day() -> None:
    # Ten steady days, then a morning with 800 steps so far.
    by_day = run_of([8000.0] * 10 + [800.0])
    steps = metric_baseline("cumulative", by_day, TODAY - timedelta(days=10), TODAY)
    assert steps is not None
    assert steps.deviation == 0.0
    assert steps.outside_typical is False
    heart = metric_baseline("discrete", by_day, TODAY - timedelta(days=10), TODAY)
    assert heart is not None
    assert heart.deviation == -7200.0


def test_a_cumulative_metric_asked_for_today_alone_has_no_baseline() -> None:
    by_day = run_of([8000.0] * 10 + [800.0])
    assert metric_baseline("cumulative", by_day, TODAY, TODAY) is None


def test_sleep_is_compared_on_the_last_shown_night() -> None:
    by_day = run_of([420.0] * 10 + [300.0])
    result = metric_baseline("sleep", by_day, TODAY, TODAY)
    assert result is not None
    assert result.deviation == -120.0


@pytest.mark.parametrize("kind", ["category", "event", "symptom", "unheard-of"])
def test_other_kinds_have_no_baseline(kind: str) -> None:
    by_day = run_of([3.0] * 10 + [9.0])
    assert metric_baseline(kind, by_day, TODAY, TODAY) is None


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


def heart_on(day: date, value: float) -> dict[str, Any]:
    stamp = f"{day.isoformat()}T10:00:00Z"
    return {
        "identifier": HEART,
        "value": value,
        "unit": "count/min",
        "start": stamp,
        "end": stamp,
        "utc_offset_minutes": 0,
    }


async def test_the_list_carries_the_baseline_although_it_asks_for_one_day(
    client: AsyncClient,
) -> None:
    samples = [heart_on(TODAY - timedelta(days=i), 60.0) for i in range(1, 15)]
    samples.append(heart_on(TODAY, 75.0))
    response = await client.post(SAMPLES_URL, json={"samples": samples})
    assert response.status_code == 200, response.text

    body = await list_metrics(client, TODAY)
    heart = next(m for m in body["metrics"] if m["identifier"] == HEART)
    assert [d["date"] for d in heart["days"]] == [TODAY.isoformat()]
    assert heart["baseline"]["mean"] == 60.0
    assert heart["baseline"]["days"] == 14
    assert heart["baseline"]["deviation"] == 15.0
    steps = next(m for m in body["metrics"] if m["identifier"] == STEPS)
    assert steps["days"] == []
    assert steps["baseline"] is None


async def test_a_partial_today_of_a_cumulative_metric_gives_no_false_deviation(
    client: AsyncClient,
) -> None:
    samples = [steps_on(TODAY - timedelta(days=i), 8000.0) for i in range(1, 15)]
    samples.append(steps_on(TODAY, 800.0))
    response = await client.post(SAMPLES_URL, json={"samples": samples})
    assert response.status_code == 200, response.text

    body = await list_metrics(client, TODAY - timedelta(days=1))
    steps = next(m for m in body["metrics"] if m["identifier"] == STEPS)
    assert steps["days"][-1]["value"] == 800.0
    assert steps["baseline"]["deviation"] == 0.0
    assert steps["baseline"]["outside_typical"] is False


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
