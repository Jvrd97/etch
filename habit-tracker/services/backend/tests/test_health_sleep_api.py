# [review:need-review] PHASE-03/238
# summary: sleep through POST /health/samples (category samples, the same chunk and journal as the quantity metrics) and GET /health/sleep — a night across midnight, iPhone and Watch not added up, a re-sent night overwritten not doubled, an empty range, the sleep day in /health/metrics, refusals by class (unknown stage, sleep as a quantity, a quantity as a category), and a category type added by a catalogue row alone
"""
Sleep end to end on the HTTP surface.

The phone sends sleep as `category_samples` in the same chunk as everything
else; the server folds them into nights keyed by the local wake date
(`app.health.sleep`) and overwrites each night it receives whole.
"""

import uuid
from io import StringIO
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from app.models import HealthHourBucket, HealthMetric, HealthSleepNight, HealthSyncRun

SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
STEPS = "HKQuantityTypeIdentifierStepCount"
MINDFUL = "HKCategoryTypeIdentifierMindfulSession"
BERLIN = 120

IN_BED, ASLEEP, AWAKE, CORE, DEEP, REM = range(6)

SAMPLES_URL = "/api/v1/health/samples"
SLEEP_URL = "/api/v1/health/sleep"


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def stage(value: int, start: str, end: str, offset: int = BERLIN) -> dict[str, Any]:
    return {
        "identifier": SLEEP,
        "value": value,
        "start": start,
        "end": end,
        "utc_offset_minutes": offset,
    }


# Monday night into Tuesday 20 October 2026, Berlin: phone in bed 23:00-07:00,
# watch stages inside it.
NIGHT = [
    stage(IN_BED, "2026-10-19T21:00:00.000Z", "2026-10-20T05:00:00.000Z"),
    stage(CORE, "2026-10-19T21:30:00.000Z", "2026-10-20T01:00:00.000Z"),
    stage(DEEP, "2026-10-20T01:00:00.000Z", "2026-10-20T02:00:00.000Z"),
    stage(REM, "2026-10-20T02:00:00.000Z", "2026-10-20T04:00:00.000Z"),
    stage(AWAKE, "2026-10-20T04:00:00.000Z", "2026-10-20T04:30:00.000Z"),
]


async def post(client: AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(SAMPLES_URL, json={"samples": [], **body})
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


async def nights(
    client: AsyncClient, date_from: str = "2026-10-14", date_to: str = "2026-10-20"
) -> list[dict[str, Any]]:
    response = await client.get(
        SLEEP_URL, params={"date_from": date_from, "date_to": date_to}
    )
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()["nights"]
    return body


async def test_a_night_arrives_as_stages_and_reads_back_on_its_wake_date(
    client: AsyncClient,
) -> None:
    answer = await post(client, {"category_samples": NIGHT})

    assert answer["samples_received"] == len(NIGHT)
    (night,) = await nights(client)
    assert night["date"] == "2026-10-20"
    assert night["asleep_min"] == 390
    assert night["in_bed_min"] == 480
    assert (night["core_min"], night["deep_min"], night["rem_min"]) == (210, 60, 120)
    assert night["awake_min"] == 30
    assert night["unspecified_min"] == 0
    # Bedtime and wake time on the clock the device lived on that night.
    assert night["bedtime"] == "2026-10-19T23:00:00+02:00"
    assert night["wake_time"] == "2026-10-20T07:00:00+02:00"


async def test_iphone_and_watch_over_the_same_night_are_not_added_up(
    client: AsyncClient,
) -> None:
    watch_copy = [dict(sample) for sample in NIGHT if sample["value"] != IN_BED]
    await post(client, {"category_samples": NIGHT + watch_copy})

    (night,) = await nights(client)
    assert night["asleep_min"] == 390
    assert night["in_bed_min"] == 480


async def test_a_resent_night_is_overwritten_not_doubled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await post(client, {"category_samples": NIGHT})
    await post(client, {"category_samples": NIGHT})
    # Apple later trims the night: the newer reading wins.
    await post(client, {"category_samples": NIGHT[1:3]})

    (night,) = await nights(client)
    assert night["asleep_min"] == 270
    count = await db_session.scalar(select(func.count()).select_from(HealthSleepNight))
    assert count == 1


async def test_a_range_without_nights_is_empty_and_the_sleep_day_is_absent(
    client: AsyncClient,
) -> None:
    assert await nights(client) == []

    response = await client.get(
        "/api/v1/health/metrics",
        params={"date_from": "2026-10-14", "date_to": "2026-10-20"},
    )
    sleep = next(m for m in response.json()["metrics"] if m["identifier"] == SLEEP)
    assert sleep["days"] == []
    assert (sleep["kind"], sleep["canonical_unit"], sleep["group"]) == (
        "sleep",
        "min",
        "sleep",
    )


async def test_the_metrics_list_carries_asleep_minutes_on_the_wake_date(
    client: AsyncClient,
) -> None:
    await post(client, {"category_samples": NIGHT})

    response = await client.get(
        "/api/v1/health/metrics",
        params={"date_from": "2026-10-19", "date_to": "2026-10-20"},
    )

    sleep = next(m for m in response.json()["metrics"] if m["identifier"] == SLEEP)
    assert sleep["days"] == [{"date": "2026-10-20", "value": 390}]


async def test_sleep_rides_the_same_chunk_and_journal_as_the_quantities(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    steps = {
        "identifier": STEPS,
        "value": 300,
        "unit": "count",
        "start": "2026-10-20T06:00:00.000Z",
        "end": "2026-10-20T07:00:00.000Z",
        "utc_offset_minutes": BERLIN,
    }

    answer = await post(
        client,
        {
            "samples": [steps],
            "category_samples": NIGHT,
            "sync_run_id": str(run_id),
            "kind": "rolling",
            "chunk_index": 0,
            "chunks_total": 1,
        },
    )

    assert answer["samples_received"] == 1 + len(NIGHT)
    run = await db_session.scalar(
        select(HealthSyncRun).where(HealthSyncRun.client_run_id == run_id)
    )
    assert run is not None
    assert (run.status, run.samples_received) == ("ok", 1 + len(NIGHT))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {
                "category_samples": [
                    stage(9, "2026-10-20T01:00:00Z", "2026-10-20T02:00:00Z")
                ]
            },
            id="unknown-stage",
        ),
        pytest.param(
            {
                "samples": [
                    {
                        "identifier": SLEEP,
                        "value": 1,
                        "unit": "count",
                        "start": "2026-10-20T01:00:00Z",
                        "end": "2026-10-20T02:00:00Z",
                        "utc_offset_minutes": BERLIN,
                    }
                ]
            },
            id="sleep-as-quantity",
        ),
        pytest.param(
            {
                "category_samples": [
                    {
                        **stage(1, "2026-10-20T01:00:00Z", "2026-10-20T02:00:00Z"),
                        "identifier": STEPS,
                    }
                ]
            },
            id="quantity-as-category",
        ),
    ],
)
async def test_a_value_the_server_cannot_read_refuses_the_chunk_as_unit(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, Any]
) -> None:
    run_id = uuid.uuid4()
    response = await client.post(
        SAMPLES_URL,
        json={
            "samples": [],
            **body,
            "sync_run_id": str(run_id),
            "chunk_index": 0,
            "chunks_total": 1,
        },
    )

    assert response.status_code == 422
    run = await db_session.scalar(
        select(HealthSyncRun).where(HealthSyncRun.client_run_id == run_id)
    )
    assert run is not None
    assert (run.status, run.failure_kind) == ("failed", "unit")
    assert (
        await db_session.scalar(select(func.count()).select_from(HealthSleepNight)) == 0
    )


async def test_an_unknown_category_type_is_refused_as_unknown_metric(
    client: AsyncClient,
) -> None:
    response = await client.post(
        SAMPLES_URL,
        json={
            "samples": [],
            "category_samples": [
                {
                    **stage(0, "2026-10-20T01:00:00Z", "2026-10-20T01:10:00Z"),
                    "identifier": MINDFUL,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert MINDFUL in response.json()["detail"]


async def test_a_category_type_with_minutes_is_one_catalogue_row_away(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A category type that is a duration needs a row, not code: minutes per hour."""
    db_session.add(
        HealthMetric(
            identifier=MINDFUL,
            kind="cumulative",
            canonical_unit="min",
            display_name="Осознанность",
            group="mind",
        )
    )
    await db_session.commit()

    await post(
        client,
        {
            "category_samples": [
                # 09:50-10:10 Berlin: ten minutes in each hour.
                {
                    **stage(0, "2026-10-20T07:50:00Z", "2026-10-20T08:10:00Z"),
                    "identifier": MINDFUL,
                }
            ]
        },
    )

    buckets = (
        await db_session.execute(
            select(HealthHourBucket.hour, HealthHourBucket.value)
            .join(HealthMetric)
            .where(HealthMetric.identifier == MINDFUL)
            .order_by(HealthHourBucket.hour)
        )
    ).all()
    assert [(hour, round(value, 6)) for hour, value in buckets] == [(9, 10), (10, 10)]


async def test_the_read_range_is_bounded_and_ordered(client: AsyncClient) -> None:
    reversed_range = await client.get(
        SLEEP_URL, params={"date_from": "2026-10-20", "date_to": "2026-10-19"}
    )
    too_long = await client.get(
        SLEEP_URL, params={"date_from": "2025-01-01", "date_to": "2026-10-20"}
    )

    assert reversed_range.status_code == 422
    assert too_long.status_code == 422


# Byte for byte what `HealthSamplesRequestDTO` encodes for a sleep chunk;
# `HealthSampleMappingTests.testEncodedSleepChunkMatchesTheServerFixture` asserts
# the same keys and values on the iOS side.
DEVICE_SLEEP_BODY = (
    '{"samples":[],"category_samples":['
    '{"identifier":"HKCategoryTypeIdentifierSleepAnalysis","value":3,'
    '"start":"2026-10-19T21:30:00.000Z","end":"2026-10-20T01:00:00.000Z",'
    '"utc_offset_minutes":120},'
    '{"identifier":"HKCategoryTypeIdentifierSleepAnalysis","value":4,'
    '"start":"2026-10-20T01:00:00.000Z","end":"2026-10-20T02:00:00.000Z",'
    '"utc_offset_minutes":120}'
    "]}"
)


async def test_the_body_the_phone_encodes_is_accepted_as_is(
    client: AsyncClient,
) -> None:
    response = await client.post(
        SAMPLES_URL,
        content=DEVICE_SLEEP_BODY,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200, response.text
    (night,) = await nights(client)
    assert (night["date"], night["core_min"], night["deep_min"]) == (
        "2026-10-20",
        210,
        60,
    )


SLEEP_REVISION = "4359c5a3d24e"
SLEEP_PREVIOUS_REVISION = "f1b3d5a7c9e2"


def _migration_sql(revision_range: str, *, downgrade: bool) -> str:
    config = Config()
    config.set_main_option("script_location", "alembic")
    buffer = StringIO()
    config.output_buffer = buffer
    runner = command.downgrade if downgrade else command.upgrade
    runner(config, revision_range, sql=True)
    return buffer.getvalue().lower()


def test_sleep_migration_is_reversible_and_keeps_one_head() -> None:
    config = Config()
    config.set_main_option("script_location", "alembic")
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1

    upgrade_sql = _migration_sql(
        f"{SLEEP_PREVIOUS_REVISION}:{SLEEP_REVISION}", downgrade=False
    )
    assert "create table health_sleep_nights" in upgrade_sql
    assert "insert into health_metrics" in upgrade_sql
    assert SLEEP.lower() in upgrade_sql

    downgrade_sql = _migration_sql(
        f"{SLEEP_REVISION}:{SLEEP_PREVIOUS_REVISION}", downgrade=True
    )
    assert "drop table health_sleep_nights" in downgrade_sql
    assert "delete from health_metrics" in downgrade_sql
    assert "health_hour_buckets" not in downgrade_sql
