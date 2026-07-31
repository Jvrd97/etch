# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: Health persistence — catalogue seed/read, natural-key upsert of hourly buckets, daily fold by local_date
"""
Database access for the Health contour.

The two things worth reading closely: `upsert_buckets`, which is the reason no
`Idempotency-Key` is needed anywhere in this contour, and `daily_values`, which
groups straight off `local_date` — no timezone arithmetic on read, because the
bucket was already written in the calendar the user lived.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.health.aggregate import HourBucket, MetricKind, fold_daily
from app.health.catalog import SEED_METRICS
from app.models.health import HealthHourBucket, HealthMetric


@dataclass(frozen=True)
class DailyValue:
    """One day of one metric, already folded by the metric's kind."""

    local_date: date
    value: float


async def seed_catalog(db: AsyncSession) -> None:
    """
    Ensure every seeded metric exists, without disturbing the ones that do.

    Runs on an existing catalogue as happily as an empty one, so a test database
    built by `create_all` (which never sees the migration's seed) starts from the
    same rows as a migrated one.
    """
    existing = set((await db.execute(select(HealthMetric.identifier))).scalars().all())
    for seed in SEED_METRICS:
        if seed.identifier in existing:
            continue
        db.add(
            HealthMetric(
                identifier=seed.identifier,
                kind=seed.kind.value,
                canonical_unit=seed.canonical_unit,
                display_name=seed.display_name,
                group=seed.group,
            )
        )
    await db.flush()


async def get_catalog(db: AsyncSession) -> list[HealthMetric]:
    """Every known metric, in a stable order for the screen."""
    result = await db.execute(
        select(HealthMetric).order_by(HealthMetric.group, HealthMetric.id)
    )
    return list(result.scalars().all())


async def upsert_buckets(
    db: AsyncSession, metric_id: int, buckets: Sequence[HourBucket]
) -> int:
    """
    Write hourly buckets on their natural key, overwriting what was there.

    Overwrite rather than accumulate is the point: a chunk carries *every* sample
    of the hours it covers, so the freshly computed bucket is the truth and the
    stored one is a previous answer to the same question. That is what makes
    re-sending a chunk — after a dropped connection, or to pick up an edit Apple
    made after the fact — leave the table exactly as it was.
    """
    if not buckets:
        return 0

    rows = [
        {
            "metric_id": metric_id,
            "local_date": bucket.local_date,
            "hour": bucket.hour,
            "value": bucket.value,
            "sample_count": bucket.sample_count,
            "min": bucket.min_value,
            "max": bucket.max_value,
            "utc_offset_minutes": bucket.utc_offset_minutes,
        }
        for bucket in buckets
    ]

    statement = pg_insert(HealthHourBucket).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_health_hour_bucket_natural_key",
        set_={
            "value": statement.excluded.value,
            "sample_count": statement.excluded.sample_count,
            "min": statement.excluded.min,
            "max": statement.excluded.max,
            "utc_offset_minutes": statement.excluded.utc_offset_minutes,
            "updated_at": func.now(),
        },
    )
    await db.execute(statement)
    return len(rows)


async def daily_values(
    db: AsyncSession, metrics: Sequence[HealthMetric], date_from: date, date_to: date
) -> dict[int, list[DailyValue]]:
    """
    Daily numbers per metric id over an inclusive date range.

    The database contributes the three sums a fold can need; which one becomes
    the day's value is decided by `app.health.aggregate.fold_daily`, so the
    weighted-average rule is stated in exactly one place and is testable without
    a database. Days with no buckets simply do not appear — "нет данных" is not a
    zero.
    """
    kinds = {metric.id: MetricKind(metric.kind) for metric in metrics}
    if not kinds:
        return {}

    result = await db.execute(
        select(
            HealthHourBucket.metric_id,
            HealthHourBucket.local_date,
            func.sum(HealthHourBucket.value),
            func.sum(HealthHourBucket.value * HealthHourBucket.sample_count),
            func.sum(HealthHourBucket.sample_count),
        )
        .where(
            HealthHourBucket.metric_id.in_(kinds),
            HealthHourBucket.local_date >= date_from,
            HealthHourBucket.local_date <= date_to,
        )
        .group_by(HealthHourBucket.metric_id, HealthHourBucket.local_date)
        .order_by(HealthHourBucket.metric_id, HealthHourBucket.local_date)
    )

    days: dict[int, list[DailyValue]] = {metric_id: [] for metric_id in kinds}
    for metric_id, local_date, value_sum, weighted_sum, count_sum in result.all():
        value = fold_daily(
            kinds[metric_id],
            value_sum=float(value_sum),
            weighted_sum=float(weighted_sum),
            count_sum=int(count_sum),
        )
        if value is None:
            continue
        days[metric_id].append(DailyValue(local_date=local_date, value=value))
    return days
