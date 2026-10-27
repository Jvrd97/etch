# [review:need-review] PHASE-03/131, PHASE-03/234, PHASE-03/233
# summary: intake of a chunk byte-for-byte as the iOS pump encodes it (steps as HealthKit hourly sums, resting HR as readings), its daily fold, an idempotent re-send, hourly sums around midnight and the autumn clock change, and a percentage sent as a fraction
"""
`POST /api/v1/health/samples` fed with the exact body the iPhone sends.

The literal below is what `HealthSamplesRequestDTO` encodes to: snake_case
keys, instants in UTC with milliseconds, units taken from the app catalogue.
Steps arrive as HealthKit's own hourly sums (one record per whole hour, already
deduplicated across iPhone and Watch); resting heart rate as raw readings.
`HealthSampleMappingTests.testEncodedChunkMatchesTheServerFixture` on the iOS
side asserts the same values, so the two halves cannot drift apart unnoticed.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud

STEPS = "HKQuantityTypeIdentifierStepCount"
RESTING_HR = "HKQuantityTypeIdentifierRestingHeartRate"
OXYGEN_SATURATION = "HKQuantityTypeIdentifierOxygenSaturation"

DEVICE_BODY = (
    '{"samples":['
    '{"identifier":"HKQuantityTypeIdentifierStepCount","value":300,"unit":"count",'
    '"start":"2026-10-20T06:00:00.000Z","end":"2026-10-20T07:00:00.000Z",'
    '"utc_offset_minutes":120},'
    '{"identifier":"HKQuantityTypeIdentifierStepCount","value":900,"unit":"count",'
    '"start":"2026-10-20T07:00:00.000Z","end":"2026-10-20T08:00:00.000Z",'
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


async def _post(
    client: AsyncClient, samples: list[dict[str, object]]
) -> dict[str, int]:
    response = await client.post("/api/v1/health/samples", json={"samples": samples})
    assert response.status_code == 200, response.text
    body: dict[str, int] = response.json()
    return body


def _hour(start: str, end: str, value: float, offset: int) -> dict[str, object]:
    return {
        "identifier": STEPS,
        "value": value,
        "unit": "count",
        "start": start,
        "end": end,
        "utc_offset_minutes": offset,
    }


async def _day(
    client: AsyncClient, date_from: str = "2026-10-20", date_to: str = "2026-10-20"
) -> dict[str, list[dict[str, object]]]:
    response = await client.get(
        "/api/v1/health/metrics",
        params={"date_from": date_from, "date_to": date_to},
    )
    assert response.status_code == 200
    return {m["identifier"]: m["days"] for m in response.json()["metrics"]}


@pytest.mark.asyncio
async def test_device_chunk_is_accepted_and_folds_into_the_lived_day(
    client: AsyncClient,
) -> None:
    body = await _post_device_body(client)

    # Steps: whole hours 08 and 09 local. Resting HR: hours 05 and 11.
    assert body == {"samples_received": 5, "buckets_written": 4}
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

    assert again == {"samples_received": 5, "buckets_written": 4}
    assert await _day(client) == before


@pytest.mark.asyncio
async def test_hourly_sums_either_side_of_midnight_stay_whole_in_their_days(
    client: AsyncClient,
) -> None:
    # A walk 23:30-00:30 in Berlin, already split by HealthKit at local midnight.
    body = await _post(
        client,
        [
            _hour("2026-10-19T21:00:00.000Z", "2026-10-19T22:00:00.000Z", 300, 120),
            _hour("2026-10-19T22:00:00.000Z", "2026-10-19T23:00:00.000Z", 400, 120),
        ],
    )

    assert body == {"samples_received": 2, "buckets_written": 2}
    days = await _day(client, "2026-10-19", "2026-10-20")
    assert days[STEPS] == [
        {"date": "2026-10-19", "value": 300.0},
        {"date": "2026-10-20", "value": 400.0},
    ]


@pytest.mark.asyncio
async def test_repeated_hour_of_the_autumn_clock_change_keeps_both_sums(
    client: AsyncClient,
) -> None:
    # 2026-10-25 in Berlin: local hour 02 is lived at +02:00 and again at +01:00.
    body = await _post(
        client,
        [
            _hour("2026-10-25T00:00:00.000Z", "2026-10-25T01:00:00.000Z", 10, 120),
            _hour("2026-10-25T01:00:00.000Z", "2026-10-25T02:00:00.000Z", 20, 60),
        ],
    )

    assert body == {"samples_received": 2, "buckets_written": 1}
    days = await _day(client, "2026-10-25", "2026-10-25")
    assert days[STEPS] == [{"date": "2026-10-25", "value": 30.0}]


@pytest.mark.asyncio
async def test_percentage_sent_as_a_fraction_is_stored_in_percent(
    client: AsyncClient,
) -> None:
    # `HKUnit.percent()` yields 0.97; the app labels it `fraction`.
    await _post(
        client,
        [
            {
                "identifier": OXYGEN_SATURATION,
                "value": 0.97,
                "unit": "fraction",
                "start": "2026-10-20T03:00:00.000Z",
                "end": "2026-10-20T03:00:00.000Z",
                "utc_offset_minutes": 120,
            }
        ],
    )

    days = await _day(client)
    assert days[OXYGEN_SATURATION] == [{"date": "2026-10-20", "value": 97.0}]
