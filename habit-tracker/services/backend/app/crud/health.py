# [review:need-review] PHASE-02/64-health-vertical-two-metrics, PHASE-03/245
# summary: Health persistence — catalogue seed/read, natural-key upsert of hourly buckets, daily fold by local_date, and the one comparison of a metric against the window before it that the week review and the advice share
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
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.health.aggregate import HourBucket, MetricKind, fold_daily
from app.health.catalog import SEED_METRICS
from app.models.health import HealthHourBucket, HealthMetric


# Знаков после запятой в среднем за день: шаги и минуты читаются целыми, но
# сон в часах, переведённый из минут, без округления тащил бы хвост из десятков.
AVERAGE_DIGITS = 1


@dataclass(frozen=True)
class DailyValue:
    """One day of one metric, already folded by the metric's kind."""

    local_date: date
    value: float


class HealthSpec(NamedTuple):
    """Метрика, о которой пишут обзор недели и совет: ключ ответа и место в каталоге."""

    key: str
    name: str
    identifier: str


# Ключ в ответе, подпись на случай отсутствия метрики и идентификатор каталога.
# Имя метрики, которая в каталоге есть, берётся у каталога: «тренировки» было бы
# подменой названия `Минуты тренировки`. Метрика, которой в каталоге нет, едет с
# `available=false`, а не нулями. Когда #238 заведёт сон, правка — только здесь.
HEALTH_SPECS: tuple[HealthSpec, ...] = (
    HealthSpec("sleep", "Сон", "HKCategoryTypeIdentifierSleepAnalysis"),
    HealthSpec("steps", "Шаги", "HKQuantityTypeIdentifierStepCount"),
    HealthSpec(
        "workouts", "Минуты тренировки", "HKQuantityTypeIdentifierAppleExerciseTime"
    ),
    HealthSpec("resting_hr", "Пульс покоя", "HKQuantityTypeIdentifierRestingHeartRate"),
)


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


@dataclass(frozen=True)
class MetricDays:
    """Одна метрика из `HEALTH_SPECS` с её дневными значениями; `metric` пуст, если в каталоге её нет."""

    spec: HealthSpec
    metric: HealthMetric | None
    by_day: dict[date, float]

    @property
    def available(self) -> bool:
        return self.metric is not None

    @property
    def name(self) -> str:
        return self.metric.display_name if self.metric else self.spec.name

    @property
    def unit(self) -> str | None:
        return self.metric.canonical_unit if self.metric else None


async def metric_days(
    db: AsyncSession, keys: Sequence[str], date_from: date, date_to: date
) -> list[MetricDays]:
    """
    Метрики `keys` с дневными значениями за отрезок, в порядке `HEALTH_SPECS`.

    Каталог и дни читаются по одному запросу, сколько бы метрик ни просили.
    """
    catalog = {metric.identifier: metric for metric in await get_catalog(db)}
    specs = [spec for spec in HEALTH_SPECS if spec.key in keys]
    present = [catalog[spec.identifier] for spec in specs if spec.identifier in catalog]
    daily = await daily_values(db, present, date_from, date_to)
    result: list[MetricDays] = []
    for spec in specs:
        metric = catalog.get(spec.identifier)
        by_day = (
            {point.local_date: point.value for point in daily.get(metric.id, [])}
            if metric
            else {}
        )
        result.append(MetricDays(spec=spec, metric=metric, by_day=by_day))
    return result


@dataclass(frozen=True)
class WindowComparison:
    """Метрика за окно против окна до него; пустое окно — `None`, а не ноль."""

    days_with_data: int
    total: float | None
    avg_per_day: float | None
    previous_days_with_data: int
    previous_avg_per_day: float | None
    delta_avg_per_day: float | None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), AVERAGE_DIGITS) if values else None


def compare_windows(
    by_day: dict[date, float], current: Sequence[date], earlier: Sequence[date]
) -> WindowComparison:
    """
    Среднее за день в окне `current` против окна `earlier`.

    **Знаменатель — дни с данными.** День без корзин не входит ни в числитель, ни
    в знаменатель: «нет данных» — не нуль шагов и не нуль минут тренировки. Среднее
    за день, в котором ничего не записано, не определено, а не равно нулю. Сколько
    дней стоит за средним, говорит `days_with_data`, и промпты называют его вслух.
    """
    now = [by_day[d] for d in current if d in by_day]
    before = [by_day[d] for d in earlier if d in by_day]
    avg, previous_avg = _average(now), _average(before)
    return WindowComparison(
        days_with_data=len(now),
        total=sum(now) if now else None,
        avg_per_day=avg,
        previous_days_with_data=len(before),
        previous_avg_per_day=previous_avg,
        delta_avg_per_day=(
            None
            if avg is None or previous_avg is None
            else round(avg - previous_avg, AVERAGE_DIGITS)
        ),
    )
