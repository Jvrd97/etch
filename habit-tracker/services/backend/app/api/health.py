# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: POST /health/samples (raw intake, server-side aggregation, one transaction per chunk, sync-run journal), POST /health/sync-runs/{id}/fail, GET /health/sync-status and GET /health/metrics (daily values)
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import health as health_crud
from app.health.aggregate import (
    MetricKind,
    RawSample,
    UnitError,
    aggregate_samples,
)
from app.models.health import HealthSyncRun
from app.schemas.health import (
    HealthDayValue,
    HealthMetricSeries,
    HealthMetricsResponse,
    HealthSamplesRequest,
    HealthSamplesResponse,
    HealthSyncFailureIn,
    HealthSyncRunOut,
    HealthSyncStatusResponse,
    SyncFailureKind,
)

router = APIRouter(prefix="/health", tags=["health"])

# Upper bound for a read range (leap year): every day of every metric is
# materialised into a response object.
MAX_RANGE_DAYS = 366


@router.post("/samples", response_model=HealthSamplesResponse)
async def ingest_samples(
    payload: HealthSamplesRequest,
    db: AsyncSession = Depends(get_db),
) -> HealthSamplesResponse:
    """
    Приём сырых семплов HealthKit.

    Клиент присылает сырьё — сервер канонизирует единицы, раскладывает по
    локальным часовым корзинам и делает upsert по естественному ключу
    `(metric, local_date, hour)`. Повторная отправка того же чанка ничего не
    меняет: `Idempotency-Key` здесь не нужен.

    Чанк обрабатывается целиком: незнакомый идентификатор или единица отвергают
    весь запрос с 422. Прерванный бэкфилл лечится повторной отправкой, а тихо
    пропущенный час не замечает никто.
    """
    catalog = {
        metric.identifier: metric for metric in await health_crud.get_catalog(db)
    }

    unknown = sorted({s.identifier for s in payload.samples} - catalog.keys())
    if unknown:
        await _fail_run(db, payload, "unknown_metric")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown health metric identifiers: {', '.join(unknown)}",
        )

    by_identifier: dict[str, list[RawSample]] = {}
    for sample in payload.samples:
        by_identifier.setdefault(sample.identifier, []).append(
            RawSample(
                value=sample.value,
                unit=sample.unit,
                start=sample.start,
                end=sample.end,
                utc_offset_minutes=sample.utc_offset_minutes,
            )
        )

    buckets_written = 0
    for identifier, raw in by_identifier.items():
        metric = catalog[identifier]
        try:
            buckets = aggregate_samples(
                raw, MetricKind(metric.kind), metric.canonical_unit
            )
        except UnitError as error:
            await _fail_run(db, payload, "unit")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{identifier}: {error}",
            ) from error
        buckets_written += await health_crud.upsert_buckets(db, metric.id, buckets)

    try:
        await health_crud.record_chunk(
            db,
            client_run_id=payload.sync_run_id,
            kind=payload.kind,
            device_id=payload.device_id,
            chunk_index=payload.chunk_index,
            chunks_total=payload.chunks_total,
            range_from=payload.range_from,
            range_to=payload.range_to,
            samples_received=len(payload.samples),
            buckets_written=buckets_written,
        )
    except health_crud.DeviceMismatchError as error:
        await db.rollback()
        raise _device_mismatch() from error

    # One commit for the chunk: it lands whole or not at all, and an earlier
    # chunk of the same backfill stays valid regardless.
    await db.commit()

    return HealthSamplesResponse(
        samples_received=len(payload.samples), buckets_written=buckets_written
    )


def _device_mismatch() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="sync run belongs to another device",
    )


async def _fail_run(
    db: AsyncSession, payload: HealthSamplesRequest, failure_kind: SyncFailureKind
) -> None:
    """Drop the half-written chunk and journal the rejection by class."""
    await db.rollback()
    if payload.sync_run_id is None:
        return
    try:
        await health_crud.record_failure(
            db,
            client_run_id=payload.sync_run_id,
            failure_kind=failure_kind,
            kind=payload.kind,
            device_id=payload.device_id,
            chunks_total=payload.chunks_total,
        )
    except health_crud.DeviceMismatchError:
        # The 422 the caller is about to get already says the chunk was refused.
        await db.rollback()
        return
    await db.commit()


@router.post("/sync-runs/{sync_run_id}/fail", response_model=HealthSyncRunOut)
async def report_sync_failure(
    sync_run_id: uuid.UUID,
    payload: HealthSyncFailureIn,
    db: AsyncSession = Depends(get_db),
) -> HealthSyncRunOut:
    """
    Устройство сообщает, что прогон умер, классом отказа.

    Сеть, из-за которой чанк не дошёл, не даёт серверу увидеть отказ сама, поэтому
    телефон докладывает о нём при следующей связи. Поля с текстом ошибки нет
    намеренно. Прогон, который успел завершиться `ok`, остаётся `ok`.
    """
    try:
        run = await health_crud.record_failure(
            db,
            client_run_id=sync_run_id,
            failure_kind=payload.failure_kind,
            kind=payload.kind,
            device_id=payload.device_id,
            chunks_total=payload.chunks_total,
        )
    except health_crud.DeviceMismatchError as error:
        await db.rollback()
        raise _device_mismatch() from error
    await db.commit()
    return _run_out(run, datetime.now(timezone.utc))


def _run_out(run: HealthSyncRun, now: datetime) -> HealthSyncRunOut:
    return HealthSyncRunOut.model_validate(
        {
            "sync_run_id": run.client_run_id,
            "kind": run.kind,
            "status": run.status,
            "interrupted": health_crud.is_interrupted(run, now),
            "failure_kind": run.failure_kind,
            "device_id": run.device_id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "range_from": run.range_from,
            "range_to": run.range_to,
            "samples_received": run.samples_received,
            "buckets_written": run.buckets_written,
            "chunks_done": run.chunks_done,
            "chunks_total": run.chunks_total,
        }
    )


@router.get("/sync-status", response_model=HealthSyncStatusResponse)
async def get_sync_status(
    db: AsyncSession = Depends(get_db),
) -> HealthSyncStatusResponse:
    """
    Жив ли насос: последний прогон каждого вида и отставание в часах.

    Отставание считается по журналу прогонов, а не по корзинам: пустой вчерашний
    день значит либо «синк не прошёл», либо «человек не двигался». Оборванным
    называется прогон в `running` без новых чанков больше часа.
    """
    now = datetime.now(timezone.utc)
    status_ = await health_crud.sync_status(db, now)
    return HealthSyncStatusResponse(
        last_runs=[_run_out(run, now) for run in status_.last_runs],
        last_success_at=status_.last_success_at,
        lag_hours=status_.lag_hours,
        interrupted=status_.interrupted,
    )


@router.get("/metrics", response_model=HealthMetricsResponse)
async def get_metrics(
    date_from: date = Query(
        ..., description="Start of the range, inclusive (YYYY-MM-DD)"
    ),
    date_to: date = Query(..., description="End of the range, inclusive (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> HealthMetricsResponse:
    """
    Метрики каталога с дневными значениями за период.

    Дневная свёртка идёт `GROUP BY local_date` — час уже записан в календаре,
    который прожил пользователь, и на чтении время не преобразуется. Метрика без
    данных возвращается с пустым списком дней: экран показывает «нет данных», а
    не прячет строку.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )
    range_days = (date_to - date_from).days + 1
    if range_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"date range is too long: {range_days} days requested, "
                f"maximum is {MAX_RANGE_DAYS} days"
            ),
        )

    metrics = await health_crud.get_catalog(db)
    days = await health_crud.daily_values(db, metrics, date_from, date_to)

    return HealthMetricsResponse(
        metrics=[
            HealthMetricSeries(
                identifier=metric.identifier,
                display_name=metric.display_name,
                group=metric.group,
                kind=metric.kind,
                canonical_unit=metric.canonical_unit,
                days=[
                    HealthDayValue(date=day.local_date, value=day.value)
                    for day in days.get(metric.id, [])
                ],
            )
            for metric in metrics
        ]
    )
