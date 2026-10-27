# [review:need-review] PHASE-03/131
# summary: intake of a chunk byte-for-byte as the iOS pump encodes it (millisecond UTC instants, a walk across an hour boundary), its daily fold and an idempotent re-send
"""
`POST /api/v1/health/samples` fed with the exact body the iPhone sends.

The literal below is what `HealthSamplesRequestDTO` encodes to: snake_case
keys, instants in UTC with milliseconds, units taken from the app catalogue.
`HealthSampleMappingTests.testEncodedChunkMatchesTheServerFixture` on the iOS
side asserts the same values, so the two halves cannot drift apart unnoticed.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud

STEPS = "HKQuantityTypeIdentifierStepCount"
RESTING_HR = "HKQuantityTypeIdentifierRestingHeartRate"

DEVICE_BODY = (
    '{"samples":['
    '{"identifier":"HKQuantityTypeIdentifierStepCount","value":1200,"unit":"count",'
    '"start":"2026-10-20T06:50:00.000Z","end":"2026-10-20T07:30:00.000Z",'
    '"utc_offset_minutes":120},'
    '{"identifier":"HKQuantityTypeIdentifierRestingHeartRate","value":54,'
    '"unit":"count\\/min","start":"2026-10-20T03:00:00.250Z",'
    '"end":"2026-10-20T03:00:00.250Z","utc_offset_minutes":120},'
    '{"identifier":"HKQuantityTypeIdentifierRestingHeartRate","value":58,'
    '"unit":"count\\/min","start":"2026-10-20T03:20:00.000Z",'
    '"end":"2026-10-20T03:20:00.000Z","utc_offset_minutes":120},'
    '{"identifier":"HKQuantityTypeIdentifierRestingHeartRate","value":62,'
    '"unit":"count\\/min","start":"2026-10-20T09:00:00.000Z",'
    '"end":"2026-10-20T09:00:00.000Z","utc_offset_minutes":120}'
    "]}"
)
JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


async def _post_device_body(client: AsyncClient) -> dict[str, int]:
    response = await client.post(
        "/api/v1/health/samples", content=DEVICE_BODY, headers=JSON_HEADERS
    )
    assert response.status_code == 200, response.text
    body: dict[str, int] = response.json()
    return body


async def _day(client: AsyncClient) -> dict[str, list[dict[str, object]]]:
    response = await client.get(
        "/api/v1/health/metrics",
        params={"date_from": "2026-10-20", "date_to": "2026-10-20"},
    )
    assert response.status_code == 200
    return {m["identifier"]: m["days"] for m in response.json()["metrics"]}


@pytest.mark.asyncio
async def test_device_chunk_is_accepted_and_folds_into_the_lived_day(
    client: AsyncClient,
) -> None:
    body = await _post_device_body(client)

    # Steps: 08:50-09:30 local spans two hours. Resting HR: hours 05 and 11.
    assert body == {"samples_received": 4, "buckets_written": 4}
    days = await _day(client)
    assert days[STEPS] == [{"date": "2026-10-20", "value": 1200.0}]
    # Weighted by readings: (56 * 2 + 62) / 3 = 58, not the mean of hours (59).
    assert days[RESTING_HR] == [{"date": "2026-10-20", "value": 58.0}]


@pytest.mark.asyncio
async def test_resending_the_device_chunk_keeps_the_numbers(
    client: AsyncClient,
) -> None:
    await _post_device_body(client)
    before = await _day(client)

    again = await _post_device_body(client)

    assert again == {"samples_received": 4, "buckets_written": 4}
    assert await _day(client) == before
