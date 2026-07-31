# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: integration tests for the Health contour — raw-sample intake, natural-key idempotency, 422 on an unknown identifier, daily fold by local_date, isolation from entries
"""
Tests for `POST /api/v1/health/samples` and `GET /api/v1/health/metrics`.

These cover what the pure aggregation tests cannot: that a re-sent chunk lands
on the same rows instead of new ones, that an identifier nobody taught the
server is refused rather than dropped, and that the Health contour writes
nothing into `entries`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from app.models import Entry, HealthHourBucket

STEPS = "HKQuantityTypeIdentifierStepCount"
RESTING_HR = "HKQuantityTypeIdentifierRestingHeartRate"
BERLIN_SUMMER_OFFSET = 120


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    """
    Seed the metric catalogue.

    Tests build their schema with `create_all`, which knows nothing about the
    migration's seed, so the same seed data is applied here through the shared
    catalogue module rather than repeated as literals.
    """
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def sample(
    identifier: str,
    value: float,
    unit: str,
    start: str,
    end: str | None = None,
    offset: int = BERLIN_SUMMER_OFFSET,
) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "value": value,
        "unit": unit,
        "start": start,
        "end": end or start,
        "utc_offset_minutes": offset,
    }


# One ordinary day in Berlin: two walks and three heart-rate readings.
CHUNK: list[dict[str, Any]] = [
    sample(STEPS, 1200, "count", "2026-07-20T06:00:00Z", "2026-07-20T06:30:00Z"),
    sample(STEPS, 800, "count", "2026-07-20T16:00:00Z", "2026-07-20T16:20:00Z"),
    sample(RESTING_HR, 54, "count/min", "2026-07-20T03:00:00Z"),
    sample(RESTING_HR, 58, "count/min", "2026-07-20T03:20:00Z"),
    sample(RESTING_HR, 62, "count/min", "2026-07-20T09:00:00Z"),
]


@pytest.mark.asyncio
class TestSampleIntake:
    """POST /health/samples — raw in, hourly buckets out."""

    async def test_chunk_is_accepted_and_stored_as_hourly_buckets(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post("/api/v1/health/samples", json={"samples": CHUNK})

        assert response.status_code == 200
        body = response.json()
        assert body["samples_received"] == len(CHUNK)
        # Steps: two separate hours. Resting HR: 05 (two readings) and 11.
        assert body["buckets_written"] == 4

        stored = (await db_session.execute(select(HealthHourBucket))).scalars().all()
        assert len(stored) == 4
        assert {bucket.hour for bucket in stored} == {8, 5, 11, 18}

    async def test_resending_the_same_chunk_changes_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The natural key `(metric, local_date, hour)` is the whole idempotency
        story: no `Idempotency-Key`, no client bookkeeping, and a backfill that
        died halfway is fixed by sending the chunk again.
        """
        await client.post("/api/v1/health/samples", json={"samples": CHUNK})
        before = await _bucket_state(db_session)

        second = await client.post("/api/v1/health/samples", json={"samples": CHUNK})

        assert second.status_code == 200
        assert await _bucket_state(db_session) == before

    async def test_unknown_identifier_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/health/samples",
            json={
                "samples": [
                    sample(
                        "HKQuantityTypeIdentifierNumberOfTimesFallen",
                        1,
                        "count",
                        "2026-07-20T06:00:00Z",
                    )
                ]
            },
        )

        assert response.status_code == 422
        assert "HKQuantityTypeIdentifierNumberOfTimesFallen" in response.text

    async def test_a_refused_chunk_writes_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One bad sample fails the chunk; a chunk is cheap to re-send, a hole is not."""
        response = await client.post(
            "/api/v1/health/samples",
            json={
                "samples": [
                    *CHUNK,
                    sample(
                        "HKQuantityTypeIdentifierNope",
                        1,
                        "count",
                        "2026-07-20T06:00:00Z",
                    ),
                ]
            },
        )

        assert response.status_code == 422
        assert await _bucket_count(db_session) == 0

    async def test_unknown_unit_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/health/samples",
            json={"samples": [sample(STEPS, 1, "furlong", "2026-07-20T06:00:00Z")]},
        )

        assert response.status_code == 422

    async def test_health_intake_writes_no_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The two contours never touch: Health data is not a manual record."""
        await client.post("/api/v1/health/samples", json={"samples": CHUNK})

        entries = (await db_session.execute(select(func.count(Entry.id)))).scalar_one()
        assert entries == 0


@pytest.mark.asyncio
class TestMetricsRead:
    """GET /health/metrics — the daily fold, straight off `local_date`."""

    async def test_daily_values_fold_by_kind(self, client: AsyncClient) -> None:
        await client.post("/api/v1/health/samples", json={"samples": CHUNK})

        response = await client.get(
            "/api/v1/health/metrics",
            params={"date_from": "2026-07-20", "date_to": "2026-07-20"},
        )

        assert response.status_code == 200
        by_identifier = {m["identifier"]: m for m in response.json()["metrics"]}

        steps = by_identifier[STEPS]
        assert steps["kind"] == "cumulative"
        assert steps["days"] == [{"date": "2026-07-20", "value": 2000.0}]

        # (54 + 58) / 2 = 56 in the 05 bucket with weight 2, plus 62 with weight
        # 1: weighted (56*2 + 62*1)/3 = 58. The naive mean of the two hourly
        # values would be 59.
        resting = by_identifier[RESTING_HR]
        assert resting["kind"] == "discrete"
        assert resting["days"] == [{"date": "2026-07-20", "value": 58.0}]

    async def test_metric_without_data_still_appears_with_no_days(
        self, client: AsyncClient
    ) -> None:
        """A metric the phone never filled is "нет данных", not a missing row."""
        response = await client.get(
            "/api/v1/health/metrics",
            params={"date_from": "2026-07-20", "date_to": "2026-07-20"},
        )

        assert response.status_code == 200
        metrics = response.json()["metrics"]
        assert {m["identifier"] for m in metrics} == {STEPS, RESTING_HR}
        assert all(m["days"] == [] for m in metrics)

    async def test_days_outside_the_range_are_not_returned(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/v1/health/samples", json={"samples": CHUNK})

        response = await client.get(
            "/api/v1/health/metrics",
            params={"date_from": "2026-07-21", "date_to": "2026-07-22"},
        )

        assert all(m["days"] == [] for m in response.json()["metrics"])

    async def test_reversed_range_is_refused(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/health/metrics",
            params={"date_from": "2026-07-22", "date_to": "2026-07-20"},
        )

        assert response.status_code == 422


async def _bucket_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(HealthHourBucket.id)))
    return int(result.scalar_one())


async def _bucket_state(db: AsyncSession) -> list[tuple[int, str, int, float, int]]:
    """Everything a replay could plausibly disturb, in a comparable shape."""
    db.expire_all()
    rows = (
        (
            await db.execute(
                select(HealthHourBucket).order_by(
                    HealthHourBucket.metric_id,
                    HealthHourBucket.local_date,
                    HealthHourBucket.hour,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        (
            bucket.metric_id,
            bucket.local_date.isoformat(),
            bucket.hour,
            bucket.value,
            bucket.sample_count,
        )
        for bucket in rows
    ]
