# [review:need-review] PHASE-03/132
# summary: the sync-run journal — a three-chunk run is one row with summed counters, a failed run keeps only a failure class, lag reads the journal and not the buckets, an abandoned run is named as such
"""
`health_sync_run` and `GET /api/v1/health/sync-status` (`#132`).

The journal answers one question the buckets cannot: "did the pump run, or did
the person just not move". Every test here drives the real endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import health as health_crud
from app.models.health import HealthHourBucket, HealthSyncRun

STEPS = "HKQuantityTypeIdentifierStepCount"
SAMPLES_URL = "/api/v1/health/samples"
STATUS_URL = "/api/v1/health/sync-status"
SECRET_VALUE = 123456789.5


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


def _chunk(
    run_id: uuid.UUID,
    index: int,
    total: int | None,
    *,
    hour: int = 6,
    value: float = 100,
    kind: str = "backfill",
) -> dict[str, Any]:
    start = f"2026-10-20T{hour:02d}:00:00Z"
    end = f"2026-10-20T{hour + 1:02d}:00:00Z"
    return {
        "sync_run_id": str(run_id),
        "kind": kind,
        "device_id": "device-1",
        "chunk_index": index,
        "chunks_total": total,
        "samples": [
            {
                "identifier": STEPS,
                "value": value,
                "unit": "count",
                "start": start,
                "end": end,
                "utc_offset_minutes": 0,
            }
        ],
    }


async def _rows(db: AsyncSession) -> list[HealthSyncRun]:
    return list((await db.execute(select(HealthSyncRun))).scalars().all())


def _finished_run(db: AsyncSession, finished_at: datetime) -> None:
    db.add(
        HealthSyncRun(
            client_run_id=uuid.uuid4(),
            kind="rolling",
            status="ok",
            started_at=finished_at - timedelta(seconds=5),
            updated_at=finished_at,
            finished_at=finished_at,
            samples_received=0,
            buckets_written=0,
            chunks_done=1,
            chunks_total=1,
        )
    )


async def test_three_chunks_are_one_row_with_summed_counters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    for index in range(3):
        response = await client.post(
            SAMPLES_URL, json=_chunk(run_id, index, 3, hour=6 + index)
        )
        assert response.status_code == 200, response.text

    rows = await _rows(db_session)
    assert len(rows) == 1
    run = rows[0]
    assert (run.samples_received, run.buckets_written) == (3, 3)
    assert (run.chunks_done, run.chunks_total) == (3, 3)
    assert run.status == "ok"
    assert run.finished_at is not None
    assert run.kind == "backfill"
    assert run.device_id == "device-1"


async def test_unfinished_run_stays_running_until_the_last_chunk(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    await client.post(SAMPLES_URL, json=_chunk(run_id, 0, 3))

    (run,) = await _rows(db_session)
    assert (run.status, run.finished_at, run.chunks_done) == ("running", None, 1)


async def test_chunk_without_a_run_id_is_a_finished_rolling_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = _chunk(uuid.uuid4(), 0, 1)
    for key in ("sync_run_id", "kind", "device_id", "chunk_index", "chunks_total"):
        del body[key]

    assert (await client.post(SAMPLES_URL, json=body)).status_code == 200

    (run,) = await _rows(db_session)
    assert (run.kind, run.status, run.chunks_done) == ("rolling", "ok", 1)


async def test_network_failure_is_a_class_not_a_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    await client.post(SAMPLES_URL, json=_chunk(run_id, 0, 3))

    response = await client.post(
        f"/api/v1/health/sync-runs/{run_id}/fail",
        json={"failure_kind": "network", "kind": "backfill", "device_id": "device-1"},
    )
    assert response.status_code == 200, response.text

    (run,) = await _rows(db_session)
    assert (run.status, run.failure_kind) == ("failed", "network")
    assert run.finished_at is not None


async def test_failure_report_for_a_run_that_never_arrived_creates_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/health/sync-runs/{run_id}/fail",
        json={"failure_kind": "network", "kind": "rolling", "device_id": "device-1"},
    )
    assert response.status_code == 200

    (run,) = await _rows(db_session)
    assert (run.status, run.failure_kind, run.chunks_done) == ("failed", "network", 0)


async def test_failure_kind_outside_the_four_classes_is_refused(
    client: AsyncClient,
) -> None:
    response = await client.post(
        f"/api/v1/health/sync-runs/{uuid.uuid4()}/fail",
        json={"failure_kind": "Connection refused to 100.64.0.1", "kind": "manual"},
    )
    assert response.status_code == 422


async def test_unknown_metric_rejects_the_chunk_and_fails_the_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    body = _chunk(run_id, 0, 1, value=SECRET_VALUE)
    body["samples"][0]["identifier"] = "HKQuantityTypeIdentifierNoSuchThing"

    response = await client.post(SAMPLES_URL, json=body)
    assert response.status_code == 422

    (run,) = await _rows(db_session)
    assert (run.status, run.failure_kind) == ("failed", "unknown_metric")


async def test_unit_mismatch_fails_the_run_as_unit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = _chunk(uuid.uuid4(), 0, 1)
    body["samples"][0]["unit"] = "parsec"

    assert (await client.post(SAMPLES_URL, json=body)).status_code == 422

    (run,) = await _rows(db_session)
    assert (run.status, run.failure_kind) == ("failed", "unit")


async def test_status_never_carries_exception_text_or_metric_values(
    client: AsyncClient,
) -> None:
    run_id = uuid.uuid4()
    body = _chunk(run_id, 0, 1, value=SECRET_VALUE)
    body["samples"][0]["unit"] = "parsec"
    await client.post(SAMPLES_URL, json=body)

    text = (await client.get(STATUS_URL)).text

    assert "parsec" not in text
    assert str(SECRET_VALUE) not in text
    assert "123456789" not in text


async def test_status_with_no_runs_says_never_synced(client: AsyncClient) -> None:
    body = (await client.get(STATUS_URL)).json()

    assert body["last_runs"] == []
    assert body["last_success_at"] is None
    assert body["lag_hours"] is None
    assert body["interrupted"] is False


async def test_lag_follows_the_journal_not_the_buckets(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A still person with a live pump: zero steps and a lag under an hour."""
    now = datetime.now(timezone.utc)
    _finished_run(db_session, now - timedelta(minutes=10))
    await db_session.commit()
    assert (
        await db_session.execute(select(func.count(HealthHourBucket.id)))
    ).scalar() == 0

    body = (await client.get(STATUS_URL)).json()

    assert body["lag_hours"] is not None and body["lag_hours"] < 1
    assert body["interrupted"] is False


async def test_phone_off_for_a_day_reads_as_twenty_four_hours(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(timezone.utc)
    _finished_run(db_session, now - timedelta(hours=24))
    await db_session.commit()

    body = (await client.get(STATUS_URL)).json()

    assert 23.9 <= body["lag_hours"] <= 24.5
    assert [run["kind"] for run in body["last_runs"]] == ["rolling"]


async def test_running_run_older_than_an_hour_is_reported_interrupted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run_id = uuid.uuid4()
    await client.post(SAMPLES_URL, json=_chunk(run_id, 0, 3))
    (run,) = await _rows(db_session)
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    run.started_at = stale
    run.updated_at = stale
    await db_session.commit()

    body = (await client.get(STATUS_URL)).json()

    (last,) = body["last_runs"]
    assert last["status"] == "running"
    assert last["interrupted"] is True
    assert last["finished_at"] is None
    assert body["interrupted"] is True
    assert body["last_success_at"] is None


async def test_fresh_running_run_is_not_interrupted(client: AsyncClient) -> None:
    await client.post(SAMPLES_URL, json=_chunk(uuid.uuid4(), 0, 3))

    body = (await client.get(STATUS_URL)).json()

    assert body["last_runs"][0]["interrupted"] is False
    assert body["interrupted"] is False


async def test_status_returns_the_latest_run_of_each_kind(
    client: AsyncClient,
) -> None:
    for kind in ("backfill", "rolling", "rolling", "manual"):
        run_id = uuid.uuid4()
        await client.post(SAMPLES_URL, json=_chunk(run_id, 0, 1, kind=kind))

    body = (await client.get(STATUS_URL)).json()

    assert sorted(run["kind"] for run in body["last_runs"]) == [
        "backfill",
        "manual",
        "rolling",
    ]


async def test_status_query_count_does_not_grow_with_the_journal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import event

    async def count_selects() -> int:
        statements: list[str] = []

        def capture(*args: Any) -> None:
            statements.append(str(args[2]))

        sync_engine = db_session.get_bind()
        event.listen(sync_engine, "before_cursor_execute", capture)
        try:
            assert (await client.get(STATUS_URL)).status_code == 200
        finally:
            event.remove(sync_engine, "before_cursor_execute", capture)
        return len(statements)

    await client.post(SAMPLES_URL, json=_chunk(uuid.uuid4(), 0, 1))
    few = await count_selects()
    for _ in range(12):
        await client.post(SAMPLES_URL, json=_chunk(uuid.uuid4(), 0, 1, kind="manual"))
    many = await count_selects()

    assert many == few
