# [review:need-review] PHASE-03/223, PHASE-03/245, PHASE-03/238, PHASE-03/244
# summary: the health summary behind the advice — steps, workout minutes and resting heart rate over a window of 7-14 closed days against the window before it, sleep as minutes asleep of the night by wake date, supplement adherence per day; four statements whatever the window and the number of supplements
"""
The summary of sleep, sport and supplements (`#223`).

**Окно — прошедшие сутки.** Последний день окна — вчерашний по границе суток
(`app.core.daytime`): сегодняшний ещё проживается, и шаги «на сейчас» занизили бы
среднее. Сравнение — столько же дней перед окном.

**Число запросов не зависит ни от окна, ни от числа добавок.** Добавки, отметки,
каталог здоровья и дневные значения здоровья за оба окна читаются по одному
запросу; разбор по дням идёт в питоне.

**Сон — минуты сна ночи по дате пробуждения** (#238). Ночей в окне нет — фигура
`sleep` приходит без среднего и с `days_with_data=0`, а не нулями.

**Соблюдение.** Добавка запланирована на день, если она заведена к этому дню
или раньше и ушла в архив позже него: день архивации в план не входит, потому
что отметить добавку после архивации нельзя. Отметка вне плана всё равно
считается и в плане, иначе «принято» могло бы превысить «запланировано».
Возврат из архива обнуляет `archived_at`, и дни перерыва становятся пропусками
(истории периодов нет).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.crud import health as health_crud
from app.models.supplement import Supplement, SupplementIntake
from app.schemas.supplement_advice import (
    Adherence,
    AdherenceDay,
    HealthFigure,
    HealthSummaryResponse,
    SummaryWindow,
    SupplementAdherenceItem,
)

__all__ = ["MIN_DAYS_WITH_DATA", "adherence_for_days", "build_health_summary"]

# Меньше стольких дней среднее ничего не доказывает: блок «данных мало».
MIN_DAYS_WITH_DATA = 3
FULL_SHARE_PCT = 100

# Ключи метрик здоровья в совете; сами метрики и их расчёт — `app.crud.health`.
ADVICE_METRICS = ("sleep", "steps", "workouts", "resting_hr")


def _dates(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def _figure(
    item: health_crud.MetricDays, current: list[date], earlier: list[date]
) -> HealthFigure:
    if not item.available:
        return HealthFigure(key=item.spec.key, name=item.name, available=False)
    compared = health_crud.compare_windows(item.by_day, current, earlier)
    return HealthFigure(
        key=item.spec.key,
        name=item.name,
        unit=item.unit,
        available=True,
        days_with_data=compared.days_with_data,
        enough_data=compared.days_with_data >= MIN_DAYS_WITH_DATA,
        avg_per_day=compared.avg_per_day,
        previous_days_with_data=compared.previous_days_with_data,
        previous_avg_per_day=compared.previous_avg_per_day,
        delta_avg_per_day=compared.delta_avg_per_day,
    )


async def _figures(
    db: AsyncSession, current: list[date], earlier: list[date]
) -> list[HealthFigure]:
    items = await health_crud.metric_days(db, ADVICE_METRICS, earlier[0], current[-1])
    return [_figure(item, current, earlier) for item in items]


async def adherence_for_days(db: AsyncSession, current: list[date]) -> Adherence:
    """
    Adherence over the given consecutive days, in two statements whatever their
    number: the week review and the advice both count it here, so «принято 4 из 7»
    is one number wherever it is printed.
    """
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
            if created <= on and (archived is None or on < archived)
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
    adherence = await adherence_for_days(db, current)
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
