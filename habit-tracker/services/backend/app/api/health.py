# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: POST /health/samples (raw intake, server-side aggregation, one transaction per chunk) and GET /health/metrics (daily values)
from datetime import date

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
from app.schemas.health import (
    HealthDayValue,
    HealthMetricSeries,
    HealthMetricsResponse,
    HealthSamplesRequest,
    HealthSamplesResponse,
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
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{identifier}: {error}",
            ) from error
        buckets_written += await health_crud.upsert_buckets(db, metric.id, buckets)

    # One commit for the chunk: it lands whole or not at all, and an earlier
    # chunk of the same backfill stays valid regardless.
    await db.commit()

    return HealthSamplesResponse(
        samples_received=len(payload.samples), buckets_written=buckets_written
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
