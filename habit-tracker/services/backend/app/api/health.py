# [review:need-review] PHASE-02/64-health-vertical-two-metrics, PHASE-03/238, PHASE-02/68, PHASE-02/70
# summary: POST /health/samples (raw intake of quantity, category samples and workouts, server-side aggregation, one transaction per chunk, sync-run journal), POST /health/sync-runs/{id}/fail, GET /health/sync-status, GET /health/metrics (daily values), GET /health/metrics/{identifier}/days and /hours (one metric's series and the hours of one day) GET /health/sleep (nights by wake date) and GET /health/workouts (workouts by start date)
import uuid
from datetime import date, datetime, timedelta, timezone

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
from app.health.sleep import SleepValueError
from app.health.workouts import activity_label
from app.models.health import (
    HealthMetric,
    HealthSleepNight,
    HealthSyncRun,
    HealthWorkout,
)
from app.schemas.health import (
    HealthDayValue,
    HealthHourValue,
    HealthMetricDaysResponse,
    HealthMetricHoursResponse,
    HealthMetricSeries,
    HealthMetricsResponse,
    HealthSamplesRequest,
    HealthSamplesResponse,
    HealthSleepNightOut,
    HealthSleepResponse,
    HealthSyncFailureIn,
    HealthSyncRunOut,
    HealthSyncStatusResponse,
    HealthWorkoutOut,
    HealthWorkoutsResponse,
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

    Категорийные типы приходят в `category_samples`: сон сводится в ночи по дате
    пробуждения и перезаписывает каждую ночь, которую чанк несёт целиком.

    Чанк обрабатывается целиком: незнакомый идентификатор или единица отвергают
    весь запрос с 422. Прерванный бэкфилл лечится повторной отправкой, а тихо
    пропущенный час не замечает никто.
    """
    catalog = {
        metric.identifier: metric for metric in await health_crud.get_catalog(db)
    }

    sent = {s.identifier for s in payload.samples} | {
        s.identifier for s in payload.category_samples
    }
    unknown = sorted(sent - catalog.keys())
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

    # Hourly buckets and nights alike: the rows this chunk wrote.
    buckets_written = 0
    try:
        for identifier, raw in by_identifier.items():
            metric = catalog[identifier]
            kind = MetricKind(metric.kind)
            if kind is MetricKind.SLEEP:
                raise UnitError(f"{identifier} is a category type")
            buckets = aggregate_samples(raw, kind, metric.canonical_unit)
            buckets_written += await health_crud.upsert_buckets(db, metric.id, buckets)
        buckets_written += await health_crud.ingest_category_samples(
            db, catalog, payload.category_samples
        )
        buckets_written += await health_crud.upsert_workouts(db, payload.workouts)
    except (UnitError, SleepValueError) as error:
        await _fail_run(db, payload, "unit")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

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
            samples_received=payload.sample_count,
            buckets_written=buckets_written,
        )
    except health_crud.DeviceMismatchError as error:
        await db.rollback()
        raise _device_mismatch() from error

    # One commit for the chunk: it lands whole or not at all, and an earlier
    # chunk of the same backfill stays valid regardless.
    await db.commit()

    return HealthSamplesResponse(
        samples_received=payload.sample_count, buckets_written=buckets_written
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
    _check_range(date_from, date_to)
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


async def _known_metric(db: AsyncSession, identifier: str) -> HealthMetric:
    metric = await health_crud.get_metric(db, identifier)
    if metric is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown health metric: {identifier}",
        )
    return metric


@router.get("/metrics/{identifier}/days", response_model=HealthMetricDaysResponse)
async def get_metric_days(
    identifier: str,
    date_from: date = Query(..., description="Start of the range, inclusive"),
    date_to: date = Query(..., description="End of the range, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> HealthMetricDaysResponse:
    """
    Дневной ряд одной метрики — те же числа, что в `GET /health/metrics`.

    День без данных в ответ не попадает. Для сна день — минуты сна ночи,
    закончившейся в этот день; ночи по фазам отдаёт `GET /health/sleep`.
    """
    _check_range(date_from, date_to)
    metric = await _known_metric(db, identifier)
    days = await health_crud.daily_values(db, [metric], date_from, date_to)
    return HealthMetricDaysResponse(
        identifier=metric.identifier,
        display_name=metric.display_name,
        kind=metric.kind,
        canonical_unit=metric.canonical_unit,
        days=[
            HealthDayValue(date=day.local_date, value=day.value)
            for day in days.get(metric.id, [])
        ],
    )


@router.get("/metrics/{identifier}/hours", response_model=HealthMetricHoursResponse)
async def get_metric_hours(
    identifier: str,
    day: date = Query(..., alias="date", description="Local day (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> HealthMetricHoursResponse:
    """
    Часы одного локального дня метрики.

    Час записан в календаре устройства, поэтому день читается без пересчёта
    времени и день перехода на зимнее время не даёт ни дыр, ни дублей. Часы без
    данных не возвращаются: «нет данных» — не ноль, пустые ячейки рисует экран.
    Сон часов не имеет (его ночи — `GET /health/sleep`) и отвечает 422.
    """
    metric = await _known_metric(db, identifier)
    if MetricKind(metric.kind) is MetricKind.SLEEP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{identifier} has nights, not hours: use GET /health/sleep",
        )
    buckets = await health_crud.metric_hours(db, metric.id, day)
    return HealthMetricHoursResponse(
        identifier=metric.identifier,
        display_name=metric.display_name,
        kind=metric.kind,
        canonical_unit=metric.canonical_unit,
        date=day,
        hours=[
            HealthHourValue(
                hour=bucket.hour,
                value=bucket.value,
                min=bucket.min_value,
                max=bucket.max_value,
                sample_count=bucket.sample_count,
            )
            for bucket in buckets
        ],
    )


def _check_range(date_from: date, date_to: date) -> None:
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


@router.get("/sleep", response_model=HealthSleepResponse)
async def get_sleep(
    date_from: date = Query(..., description="First wake date, inclusive (YYYY-MM-DD)"),
    date_to: date = Query(..., description="Last wake date, inclusive (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> HealthSleepResponse:
    """
    Ночи сна за период по дате пробуждения.

    Ночь — минуты по фазам, время отбоя и подъёма. Отбой и подъём отдаются со
    смещением, в котором жило устройство, поэтому «23:40» читается из самой
    строки. Ночь без данных в ответ не попадает: это «нет данных», а не ноль.
    """
    _check_range(date_from, date_to)
    return HealthSleepResponse(
        nights=[
            _night_out(night)
            for night in await health_crud.sleep_nights(db, date_from, date_to)
        ]
    )


def _night_out(night: HealthSleepNight) -> HealthSleepNightOut:
    lived = timezone(timedelta(minutes=night.utc_offset_minutes))
    return HealthSleepNightOut(
        date=night.wake_date,
        bedtime=night.bedtime.astimezone(lived),
        wake_time=night.wake_time.astimezone(lived),
        in_bed_min=night.in_bed_min,
        asleep_min=night.asleep_min,
        awake_min=night.awake_min,
        core_min=night.core_min,
        deep_min=night.deep_min,
        rem_min=night.rem_min,
        unspecified_min=night.unspecified_min,
    )


@router.get("/workouts", response_model=HealthWorkoutsResponse)
async def get_workouts(
    date_from: date = Query(
        ..., description="First start date, inclusive (YYYY-MM-DD)"
    ),
    date_to: date = Query(..., description="Last start date, inclusive (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> HealthWorkoutsResponse:
    """
    Тренировки за период по дате начала.

    Тренировка через полночь — одна запись на день старта. Начало и конец отдаются
    со смещением, в котором жило устройство. Число, которого у HealthKit не было
    (нет часов, нет доступа к пульсу), приходит `null`, а не нулём.
    """
    _check_range(date_from, date_to)
    return HealthWorkoutsResponse(
        workouts=[
            _workout_out(workout)
            for workout in await health_crud.workouts_between(db, date_from, date_to)
        ]
    )


def _workout_out(workout: HealthWorkout) -> HealthWorkoutOut:
    lived = timezone(timedelta(minutes=workout.utc_offset_minutes))
    return HealthWorkoutOut(
        id=workout.workout_uuid,
        activity_type=workout.activity_type,
        activity_label=activity_label(workout.activity_type),
        date=workout.local_date,
        start=workout.started_at.astimezone(lived),
        end=workout.ended_at.astimezone(lived),
        duration_min=workout.duration_min,
        energy_kcal=workout.energy_kcal,
        distance_m=workout.distance_m,
        avg_heart_rate=workout.avg_heart_rate,
        max_heart_rate=workout.max_heart_rate,
    )
