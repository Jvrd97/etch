# [review:need-review] PHASE-02/70
# summary: workouts through POST /health/samples and GET /health/workouts — upsert on the HealthKit UUID (a re-sent window does not double, a corrected one overwrites), a session across midnight kept on its start date, the optional numbers left absent not zero, no hourly bucket written, a bad type or an end before the start refused whole, the range bound, and the journal counting the workout
"""Workouts end to end on the HTTP surface and in the pure helpers."""

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from app.health.workouts import (
    UNKNOWN_ACTIVITY_LABEL,
    activity_label,
    local_date_of_start,
)
from app.models import HealthHourBucket, HealthSyncRun, HealthWorkout
from app.schemas.health import HealthWorkoutIn

SAMPLES_URL = "/api/v1/health/samples"
WORKOUTS_URL = "/api/v1/health/workouts"
BERLIN = 120
RUN_UUID = "5F1E0C2A-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def workout(
    start: str = "2026-10-20T16:00:00.000Z",
    end: str = "2026-10-20T16:45:00.000Z",
    *,
    workout_uuid: str = RUN_UUID,
    activity_type: str = "running",
    offset: int = BERLIN,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "uuid": workout_uuid,
        "activity_type": activity_type,
        "start": start,
        "end": end,
        "utc_offset_minutes": offset,
        "duration_seconds": 2700.0,
        "energy_kcal": 410.5,
        "distance_m": 7200.0,
        "avg_heart_rate": 152.0,
        "max_heart_rate": 178.0,
        **extra,
    }


async def send(
    client: AsyncClient, workouts: list[dict[str, Any]], **extra: Any
) -> Any:
    return await client.post(
        SAMPLES_URL, json={"samples": [], "workouts": workouts, **extra}
    )


async def listed(client: AsyncClient, date_from: str, date_to: str) -> list[Any]:
    response = await client.get(
        WORKOUTS_URL, params={"date_from": date_from, "date_to": date_to}
    )
    assert response.status_code == 200
    return list(response.json()["workouts"])


def test_local_date_is_the_start_date_across_midnight() -> None:
    start = datetime(
        2026, 10, 20, 21, 30, tzinfo=timezone.utc
    )  # 23:30 in Berlin (+02:00)
    assert local_date_of_start(start, BERLIN).isoformat() == "2026-10-20"
    # The same instant on a device already past midnight is the next day.
    assert local_date_of_start(start, 4 * 60).isoformat() == "2026-10-21"


def test_unknown_activity_type_gets_the_generic_label() -> None:
    assert activity_label("running") == "Бег"
    assert activity_label("quidditch") == UNKNOWN_ACTIVITY_LABEL


async def test_workout_is_stored_and_listed(client: AsyncClient) -> None:
    response = await send(client, [workout()])
    assert response.status_code == 200
    assert response.json() == {"samples_received": 1, "buckets_written": 1}

    [item] = await listed(client, "2026-10-20", "2026-10-20")
    assert item["id"] == RUN_UUID.lower()
    assert item["activity_type"] == "running"
    assert item["activity_label"] == "Бег"
    assert item["date"] == "2026-10-20"
    assert item["start"] == "2026-10-20T18:00:00+02:00"
    assert item["end"] == "2026-10-20T18:45:00+02:00"
    assert item["duration_min"] == 45.0
    assert item["energy_kcal"] == 410.5
    assert item["distance_m"] == 7200.0
    assert item["avg_heart_rate"] == 152.0
    assert item["max_heart_rate"] == 178.0


async def test_resending_the_window_does_not_duplicate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for _ in range(3):
        assert (await send(client, [workout()])).status_code == 200
    count = await db_session.scalar(select(func.count()).select_from(HealthWorkout))
    assert count == 1


async def test_resent_workout_overwrites_the_numbers(client: AsyncClient) -> None:
    await send(client, [workout()])
    await send(client, [workout(energy_kcal=432.0, max_heart_rate=181.0)])
    [item] = await listed(client, "2026-10-20", "2026-10-20")
    assert item["energy_kcal"] == 432.0
    assert item["max_heart_rate"] == 181.0


async def test_two_workouts_with_different_uuids_both_stay(
    client: AsyncClient,
) -> None:
    other = "5F1E0C2A-0000-4000-8000-000000000002"
    await send(client, [workout(), workout(workout_uuid=other, activity_type="yoga")])
    items = await listed(client, "2026-10-20", "2026-10-20")
    assert [item["activity_label"] for item in items] == ["Бег", "Йога"]


async def test_workout_across_midnight_is_one_entry_on_its_start_date(
    client: AsyncClient,
) -> None:
    # 23:30 to 00:30 in Berlin on 20-21 October.
    await send(
        client, [workout("2026-10-20T21:30:00.000Z", "2026-10-20T22:30:00.000Z")]
    )
    assert len(await listed(client, "2026-10-20", "2026-10-20")) == 1
    assert await listed(client, "2026-10-21", "2026-10-21") == []


async def test_missing_numbers_stay_absent_not_zero(client: AsyncClient) -> None:
    await send(
        client,
        [
            workout(
                energy_kcal=None,
                distance_m=None,
                avg_heart_rate=None,
                max_heart_rate=None,
            )
        ],
    )
    [item] = await listed(client, "2026-10-20", "2026-10-20")
    assert item["energy_kcal"] is None
    assert item["distance_m"] is None
    assert item["avg_heart_rate"] is None
    assert item["max_heart_rate"] is None


async def test_workout_writes_no_hourly_bucket(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await send(client, [workout()])
    buckets = await db_session.scalar(
        select(func.count()).select_from(HealthHourBucket)
    )
    assert buckets == 0


async def test_unknown_type_still_lands(client: AsyncClient) -> None:
    assert (await send(client, [workout(activity_type="quidditch")])).status_code == 200
    [item] = await listed(client, "2026-10-20", "2026-10-20")
    assert item["activity_label"] == UNKNOWN_ACTIVITY_LABEL


@pytest.mark.parametrize(
    "bad",
    [
        {"activity_type": "Running"},
        {"activity_type": "run ning"},
        {"activity_type": ""},
        {"duration_seconds": -1.0},
        {"energy_kcal": -5.0},
        {"distance_m": -1.0},
        {"avg_heart_rate": 0.0},
        {"uuid": "not-a-uuid"},
    ],
)
async def test_malformed_workout_is_refused(
    client: AsyncClient, db_session: AsyncSession, bad: dict[str, Any]
) -> None:
    response = await send(client, [workout(**bad)])
    assert response.status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(HealthWorkout)) == 0


async def test_end_before_start_is_refused(client: AsyncClient) -> None:
    response = await send(
        client, [workout("2026-10-20T16:45:00.000Z", "2026-10-20T16:00:00.000Z")]
    )
    assert response.status_code == 422


async def test_listing_range_is_bounded(client: AsyncClient) -> None:
    response = await client.get(
        WORKOUTS_URL, params={"date_from": "2024-01-01", "date_to": "2026-01-01"}
    )
    assert response.status_code == 422


async def test_empty_range_is_an_empty_list(client: AsyncClient) -> None:
    assert await listed(client, "2026-10-01", "2026-10-31") == []


async def test_journal_counts_the_workout(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = str(uuid.uuid4())
    response = await send(
        client,
        [workout()],
        sync_run_id=run_id,
        kind="rolling",
        device_id="dev-1",
        chunk_index=0,
        chunks_total=1,
    )
    assert response.status_code == 200
    run = (await db_session.execute(select(HealthSyncRun))).scalar_one()
    assert run.samples_received == 1
    assert run.buckets_written == 1
    assert run.status == "ok"


def test_the_wire_fields_are_the_ones_the_phone_sends() -> None:
    # `HealthWorkoutDTO` in ios/.../API/DTOs+Health.swift, keys after snake_case conversion
    # (asserted on the phone side in HealthWorkoutTests).
    assert set(HealthWorkoutIn.model_fields) == {
        "uuid",
        "activity_type",
        "start",
        "end",
        "utc_offset_minutes",
        "duration_seconds",
        "energy_kcal",
        "distance_m",
        "avg_heart_rate",
        "max_heart_rate",
    }
