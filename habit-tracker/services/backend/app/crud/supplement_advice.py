# [review:need-review] PHASE-03/223
# summary: the health summary behind the advice — steps, workout minutes and resting heart rate over a window of 7-14 closed days against the window before it, sleep honestly absent, supplement adherence per day; four statements whatever the window and the number of supplements
"""
The summary of sleep, sport and supplements (`#223`).

**Окно — прошедшие сутки.** Последний день окна — вчерашний по границе суток
(`app.core.daytime`): сегодняшний ещё проживается, и шаги «на сейчас» занизили бы
среднее. Сравнение — столько же дней перед окном.

**Число запросов не зависит ни от окна, ни от числа добавок.** Добавки, отметки,
каталог здоровья и дневные значения здоровья за оба окна читаются по одному
запросу; разбор по дням идёт в питоне.

**Сон честно пуст.** Метрики сна в каталоге нет (#238): фигура `sleep` приходит с
`available=false`, а не нулями. Когда метрика появится в каталоге, она заработает
без правок: ключ — идентификатор HealthKit.

**Соблюдение.** Добавка запланирована на день, если она уже заведена к этому
дню и в архив не ушла раньше него. Отметка вне плана всё равно считается и в
плане, иначе «принято» могло бы превысить «запланировано».
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.crud import health as health_crud
from app.models.health import HealthMetric
from app.models.supplement import Supplement, SupplementIntake
from app.schemas.supplement_advice import (
    Adherence,
    AdherenceDay,
    HealthFigure,
    HealthSummaryResponse,
    SummaryWindow,
    SupplementAdherenceItem,
)

__all__ = ["MIN_DAYS_WITH_DATA", "build_health_summary"]

# Меньше стольких дней среднее ничего не доказывает: блок «данных мало».
MIN_DAYS_WITH_DATA = 3
# Знаков после запятой в среднем за день.
AVERAGE_DIGITS = 1
FULL_SHARE_PCT = 100

# Ключ в ответе, подпись на случай отсутствия метрики и идентификатор каталога.
# Имя метрики, которая в каталоге есть, берётся у каталога.
HEALTH_SPECS: tuple[tuple[str, str, str], ...] = (
    ("sleep", "Сон", "HKCategoryTypeIdentifierSleepAnalysis"),
    ("steps", "Шаги", "HKQuantityTypeIdentifierStepCount"),
    ("workouts", "Минуты тренировки", "HKQuantityTypeIdentifierAppleExerciseTime"),
    ("resting_hr", "Пульс покоя", "HKQuantityTypeIdentifierRestingHeartRate"),
)


def _dates(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), AVERAGE_DIGITS) if values else None


def _figure(
    key: str,
    name: str,
    metric: HealthMetric | None,
    by_day: dict[date, float],
    current: list[date],
    earlier: list[date],
) -> HealthFigure:
    if metric is None:
        return HealthFigure(key=key, name=name, available=False)
    now = [by_day[d] for d in current if d in by_day]
    before = [by_day[d] for d in earlier if d in by_day]
    avg, previous_avg = _average(now), _average(before)
    return HealthFigure(
        key=key,
        name=metric.display_name,
        unit=metric.canonical_unit,
        available=True,
        days_with_data=len(now),
        enough_data=len(now) >= MIN_DAYS_WITH_DATA,
        avg_per_day=avg,
        previous_days_with_data=len(before),
        previous_avg_per_day=previous_avg,
        delta_avg_per_day=(
            None
            if avg is None or previous_avg is None
            else round(avg - previous_avg, AVERAGE_DIGITS)
        ),
    )


async def _figures(
    db: AsyncSession, current: list[date], earlier: list[date]
) -> list[HealthFigure]:
    catalog = {
        metric.identifier: metric for metric in await health_crud.get_catalog(db)
    }
    present = [
        catalog[identifier]
        for _, _, identifier in HEALTH_SPECS
        if identifier in catalog
    ]
    daily = await health_crud.daily_values(db, present, earlier[0], current[-1])
    figures: list[HealthFigure] = []
    for key, name, identifier in HEALTH_SPECS:
        metric = catalog.get(identifier)
        by_day = (
            {point.local_date: point.value for point in daily.get(metric.id, [])}
            if metric
            else {}
        )
        figures.append(_figure(key, name, metric, by_day, current, earlier))
    return figures


async def _adherence(db: AsyncSession, current: list[date]) -> Adherence:
    supplements = (
        await db.execute(
            select(
                Supplement.id,
                Supplement.name,
                Supplement.created_at,
                Supplement.archived_at,
            ).order_by(Supplement.created_at, Supplement.id)
        )
    ).all()
    marks = (
        await db.execute(
            select(SupplementIntake.supplement_id, SupplementIntake.intake_date).where(
                SupplementIntake.intake_date.between(current[0], current[-1])
            )
        )
    ).all()
    taken_by_day: dict[date, set[int]] = defaultdict(set)
    for supplement_id, on in marks:
        taken_by_day[on].add(supplement_id)

    spans = {
        row.id: (
            local_date(row.created_at),
            local_date(row.archived_at) if row.archived_at else None,
        )
        for row in supplements
    }
    planned_days: dict[int, int] = defaultdict(int)
    taken_days: dict[int, int] = defaultdict(int)
    days: list[AdherenceDay] = []
    for on in current:
        taken = taken_by_day.get(on, set())
        planned = {
            supplement_id
            for supplement_id, (created, archived) in spans.items()
            if created <= on and (archived is None or on <= archived)
        } | taken
        for supplement_id in planned:
            planned_days[supplement_id] += 1
        for supplement_id in taken:
            taken_days[supplement_id] += 1
        days.append(AdherenceDay(date=on, planned=len(planned), taken=len(taken)))

    planned_total = sum(day.planned for day in days)
    taken_total = sum(day.taken for day in days)
    return Adherence(
        planned=planned_total,
        taken=taken_total,
        pct=(
            round(taken_total * FULL_SHARE_PCT / planned_total)
            if planned_total
            else None
        ),
        enough_data=sum(1 for day in days if day.planned) >= MIN_DAYS_WITH_DATA,
        days=days,
        supplements=[
            SupplementAdherenceItem(
                supplement_id=row.id,
                name=row.name,
                planned_days=planned_days[row.id],
                taken_days=taken_days[row.id],
            )
            for row in supplements
            if planned_days[row.id]
        ],
    )


async def build_health_summary(
    db: AsyncSession, days: int, today: date
) -> HealthSummaryResponse:
    """
    The `days` closed days before `today` and the same number before them.

    `today` is passed in rather than read here, so the one clock stays
    `app.core.daytime` and a test can pin it.
    """
    ends_on = today - timedelta(days=1)
    starts_on = ends_on - timedelta(days=days - 1)
    previous_ends_on = starts_on - timedelta(days=1)
    previous_starts_on = previous_ends_on - timedelta(days=days - 1)
    current = _dates(starts_on, days)

    figures = await _figures(db, current, _dates(previous_starts_on, days))
    adherence = await _adherence(db, current)
    return HealthSummaryResponse(
        window=SummaryWindow(
            starts_on=starts_on,
            ends_on=ends_on,
            days=days,
            previous_starts_on=previous_starts_on,
            previous_ends_on=previous_ends_on,
        ),
        figures=figures,
        adherence=adherence,
        enough_data=adherence.enough_data or any(f.enough_data for f in figures),
    )
