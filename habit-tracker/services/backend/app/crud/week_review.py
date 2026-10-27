# [review:need-review] PHASE-03/221
# summary: the week review in a fixed number of statements — day summaries, role minutes, duration entries, avoid histories and health buckets of both weeks are read as 14-day ranges and folded in python, so the count does not move with days or habits
"""
Database access for the week review (`#221`).

**Число запросов не зависит от недели.** Роли, итоги дней, записи привычек, истории
«избегать» и корзины здоровья читаются по одному запросу на оба отрезка сразу
(четырнадцать дней), а разбор по дням и неделям идёт в питоне. Цикл «запрос на
день» или «запрос на привычку» превратил бы экран недели в сотню запросов; тест на
класс ошибки держит число постоянным.

**Читает и ничего не пишет.** `/weeks/{iso}` хранит снимок со ретро и пересчитывает
его на чтении; обзор — это чтение. Источники те же, что у дня: `day_summary`
(вердикт, задачи, якоря, рабочие минуты, стрик), `role_time_block` (#138),
записи категорий с полями `duration` и корзины здоровья (#209). Нового сборщика
данных здесь нет.

**Прошлая неделя берётся за столько же дней.** Среда текущей недели сравнивается
с понедельником-средой прошлой, а не со всей прошлой неделей: иначе неполная
неделя всегда проигрывала бы.

**Сутки — логические.** Дни недели — `day_date`, посчитанные границей суток
(`app.core.daytime`); здоровье лежит по календарной дате устройства, и на границе
04:00 они могут разойтись на запись глубокой ночи.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import current_boundary
from app.crud import health as health_crud
from app.crud import role as role_crud
from app.crud import streak as streak_crud
from app.crud.values import parse_number
from app.day.evaluate import VERDICT_LOST, VERDICT_WON
from app.day.week import DAYS_IN_WEEK, iso_code, week_bounds
from app.models import Category, Entry, EntryValue, Field
from app.models.field import FieldType
from app.models.health import HealthMetric
from app.models.role import RoleTimeBlock
from app.models.summary import DaySummary
from app.schemas.week_review import (
    WeekCategorySlice,
    WeekDayStat,
    WeekDelta,
    WeekHabitStreak,
    WeekHealthMetric,
    WeekReviewResponse,
    WeekRoleSlice,
    WeekTotals,
    WeekWindow,
)

__all__ = ["build_week_review", "week_has_data"]

# Знаменатель доли в целых процентах.
FULL_SHARE_PCT = 100
SECONDS_PER_MINUTE = 60
# Знаков после запятой в среднем за день: шаги и минуты читаются целыми, но
# сон в часах, переведённый из минут, без округления тащил бы хвост из десятков.
AVERAGE_DIGITS = 1

# Метрики здоровья недели: ключ в ответе, подпись и идентификатор каталога.
# Сон и тренировки в каталоге названы так, как их называет HealthKit; метрики,
# которой в каталоге нет, ответ даёт с `available=false`, а не нулями.
HEALTH_SPECS: tuple[tuple[str, str, str], ...] = (
    ("sleep", "Сон", "HKCategoryTypeIdentifierSleepAnalysis"),
    ("steps", "Шаги", "HKQuantityTypeIdentifierStepCount"),
    ("workouts", "Тренировки", "HKQuantityTypeIdentifierAppleExerciseTime"),
)


@dataclass(frozen=True)
class _Span:
    """Первый и последний учтённый день отрезка; `days` пуст, если день не наступил."""

    start: date
    days: int

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)

    def holds(self, on: date) -> bool:
        return self.days > 0 and self.start <= on <= self.end


@dataclass(frozen=True)
class _Summary:
    verdict: str | None
    tasks_done: int
    tasks_total: int
    anchors_done: int
    anchors_total: int
    work_minutes: int | None
    streak_after: int | None


@dataclass
class _Facts:
    """Всё, что прочитано из базы за четырнадцать дней, ещё не разложенное по неделям."""

    summaries: dict[date, _Summary] = field(default_factory=dict)
    role_minutes: dict[tuple[date, int], int] = field(default_factory=dict)


def _pct(part: int, whole: int) -> int | None:
    """Доля в целых процентах; пустой знаменатель — «не с чем делить», не ноль."""
    return round(part * FULL_SHARE_PCT / whole) if whole else None


def _share(part: int, whole: int) -> int:
    return _pct(part, whole) or 0


def _spans(starts_on: date, today: date) -> tuple[_Span, _Span]:
    """Учтённые дни этой недели и столько же первых дней прошлой."""
    counted = min(max((today - starts_on).days + 1, 0), DAYS_IN_WEEK)
    return _Span(starts_on, counted), _Span(
        starts_on - timedelta(days=DAYS_IN_WEEK), counted
    )


def _dates(span: _Span) -> list[date]:
    return [span.start + timedelta(days=i) for i in range(span.days)]


async def _read_summaries(
    db: AsyncSession, start: date, end: date
) -> dict[date, _Summary]:
    result = await db.execute(
        select(
            DaySummary.day_date,
            DaySummary.verdict,
            DaySummary.tasks_done,
            DaySummary.tasks_total,
            DaySummary.anchors_done,
            DaySummary.anchors_total,
            DaySummary.work_minutes,
            DaySummary.streak_after,
        ).where(DaySummary.day_date.between(start, end))
    )
    return {
        row.day_date: _Summary(
            verdict=row.verdict,
            tasks_done=row.tasks_done,
            tasks_total=row.tasks_total,
            anchors_done=row.anchors_done,
            anchors_total=row.anchors_total,
            work_minutes=row.work_minutes,
            streak_after=row.streak_after,
        )
        for row in result
    }


async def _read_role_minutes(
    db: AsyncSession, start: date, end: date
) -> dict[tuple[date, int], int]:
    result = await db.execute(
        select(
            RoleTimeBlock.work_day,
            RoleTimeBlock.role_id,
            func.sum(RoleTimeBlock.minutes),
        )
        .where(RoleTimeBlock.work_day.between(start, end))
        .group_by(RoleTimeBlock.work_day, RoleTimeBlock.role_id)
    )
    return {(day, role_id): int(total) for day, role_id, total in result.all()}


def _totals(facts: _Facts, span: _Span) -> WeekTotals:
    rows = [facts.summaries[day] for day in _dates(span) if day in facts.summaries]
    judged = [row for row in rows if row.verdict is not None]
    done = sum(row.tasks_done for row in rows)
    total = sum(row.tasks_total for row in rows)
    measured = [row.work_minutes for row in rows if row.work_minutes is not None]
    return WeekTotals(
        closed_days=len(judged),
        won_days=sum(1 for row in judged if row.verdict == VERDICT_WON),
        lost_days=sum(1 for row in judged if row.verdict == VERDICT_LOST),
        tasks_done=done,
        tasks_total=total,
        plan_pct=_pct(done, total),
        anchors_done=sum(row.anchors_done for row in rows),
        anchors_total=sum(row.anchors_total for row in rows),
        work_minutes=sum(measured) if measured else None,
        role_minutes=sum(
            minutes
            for (day, _), minutes in facts.role_minutes.items()
            if span.holds(day)
        ),
        day_streak_end=judged[-1].streak_after if judged else None,
    )


def _delta(now: WeekTotals, before: WeekTotals) -> WeekDelta:
    def diff(a: int | None, b: int | None) -> int | None:
        return None if a is None or b is None else a - b

    return WeekDelta(
        won_days=now.won_days - before.won_days,
        tasks_done=now.tasks_done - before.tasks_done,
        plan_pct=diff(now.plan_pct, before.plan_pct),
        work_minutes=diff(now.work_minutes, before.work_minutes),
        role_minutes=now.role_minutes - before.role_minutes,
    )


def _days(facts: _Facts, starts_on: date, span: _Span) -> list[WeekDayStat]:
    stats: list[WeekDayStat] = []
    for offset in range(DAYS_IN_WEEK):
        on = starts_on + timedelta(days=offset)
        counted = span.holds(on)
        row = facts.summaries.get(on) if counted else None
        stats.append(
            WeekDayStat(
                date=on,
                weekday=offset,
                counted=counted,
                verdict=row.verdict if row else None,
                tasks_done=row.tasks_done if row else 0,
                tasks_total=row.tasks_total if row else 0,
                plan_pct=_pct(row.tasks_done, row.tasks_total) if row else None,
                work_minutes=row.work_minutes if row else None,
                role_minutes=sum(
                    minutes
                    for (day, _), minutes in facts.role_minutes.items()
                    if day == on and counted
                ),
                streak_after=row.streak_after if row else None,
            )
        )
    return stats


def _rank(day: WeekDayStat) -> tuple[int, int]:
    """Выигранный день выше проигранного, при равенстве — полнее план."""
    return (1 if day.verdict == VERDICT_WON else 0, day.plan_pct or 0)


def _best_and_worst(days: list[WeekDayStat]) -> tuple[date | None, date | None]:
    """
    Лучший и худший из судимых дней.

    При равенстве лучшим считается более ранний день, худшим — более поздний.
    Худший назван только тогда, когда он действительно хуже лучшего: у двух
    одинаково выигранных дней «худшего» нет, и выдумывать его значило бы
    подписать ничью как провал.
    """
    judged = [day for day in days if day.counted and day.verdict is not None]
    if not judged:
        return None, None
    best = min(judged, key=lambda d: (-_rank(d)[0], -_rank(d)[1], d.date))
    worst = min(judged, key=lambda d: (*_rank(d), -d.date.toordinal()))
    return best.date, (worst.date if _rank(worst) < _rank(best) else None)


async def _roles(
    db: AsyncSession, facts: _Facts, now: _Span, before: _Span
) -> list[WeekRoleSlice]:
    roles = await role_crud.list_roles(db)

    def minutes_of(role_id: int, span: _Span) -> int:
        return sum(
            minutes
            for (day, rid), minutes in facts.role_minutes.items()
            if rid == role_id and span.holds(day)
        )

    own = {role.id: minutes_of(role.id, now) for role in roles}
    whole = sum(own.values())
    return [
        WeekRoleSlice(
            role_id=role.id,
            role_code=role.code,
            title=role.title,
            minutes=own[role.id],
            share_pct=_share(own[role.id], whole),
            target_share_pct=role.target_share_pct,
            previous_minutes=(previous := minutes_of(role.id, before)),
            delta_minutes=own[role.id] - previous,
        )
        for role in roles
    ]


async def _categories(
    db: AsyncSession, now: _Span, before: _Span, start: date, end: date
) -> list[WeekCategorySlice]:
    """Время категорий по полям `duration`: секунды суммируются, минуты — вывод."""
    result = await db.execute(
        select(
            Category.id,
            Category.name,
            Entry.id,
            Entry.entry_date,
            Field.id,
            EntryValue.value,
        )
        .join(Entry, Entry.category_id == Category.id)
        .join(EntryValue, EntryValue.entry_id == Entry.id)
        .join(Field, Field.id == EntryValue.field_id)
        .where(
            Field.field_type == FieldType.DURATION,
            Entry.entry_date.between(start, end),
        )
    )
    names: dict[int, str] = {}
    seconds: dict[tuple[int, str], float] = {}
    logged: dict[tuple[int, str], set[date]] = {}
    for category_id, name, entry_id, entry_date, field_id, value in result.all():
        spent = parse_number(value, field_id=field_id, entry_id=entry_id)
        if not spent:
            continue
        names[category_id] = name
        for label, span in (("now", now), ("before", before)):
            if span.holds(entry_date):
                key = (category_id, label)
                seconds[key] = seconds.get(key, 0.0) + spent
                logged.setdefault(key, set()).add(entry_date)

    slices = [
        WeekCategorySlice(
            category_id=category_id,
            name=name,
            minutes=(
                spent := round(
                    seconds.get((category_id, "now"), 0.0) / SECONDS_PER_MINUTE
                )
            ),
            previous_minutes=(
                earlier := round(
                    seconds.get((category_id, "before"), 0.0) / SECONDS_PER_MINUTE
                )
            ),
            delta_minutes=spent - earlier,
            entry_days=len(logged.get((category_id, "now"), set())),
            previous_entry_days=len(logged.get((category_id, "before"), set())),
        )
        for category_id, name in names.items()
    ]
    return sorted(
        (s for s in slices if s.minutes or s.previous_minutes),
        key=lambda s: (-s.minutes, s.name),
    )


async def _habit_streaks(db: AsyncSession, now: _Span) -> list[WeekHabitStreak]:
    """
    Серии «избегать» на последний учтённый день недели.

    Серия из `compute_streak` тянется до сегодняшнего дня, и срыв после недели
    укоротил бы серию самой недели; поэтому длина берётся из дат срывов: дней
    от последнего срыва не позже конца отрезка, а без срывов — от первого
    отслеженного дня. Категория, которую к концу отрезка ещё не вели, не попадает.
    """
    if now.days == 0:
        return []
    names = {
        category_id: name
        for category_id, name in (
            await db.execute(
                select(Category.id, Category.name).where(
                    Category.streak_mode == "avoid", Category.is_active.is_(True)
                )
            )
        ).all()
    }
    streaks: list[WeekHabitStreak] = []
    for category_id, stats in await streak_crud.get_category_streaks(
        db, "avoid", today=now.end
    ):
        if category_id not in names:
            continue
        if stats.tracked_since is None or stats.tracked_since > now.end:
            continue
        before_end = [d for d in stats.relapse_dates if d <= now.end]
        current = (
            (now.end - before_end[-1]).days
            if before_end
            else (now.end - stats.tracked_since).days + 1
        )
        streaks.append(
            WeekHabitStreak(
                category_id=category_id,
                name=names[category_id],
                current_streak=current,
                relapses=sum(1 for d in before_end if now.holds(d)),
            )
        )
    return sorted(streaks, key=lambda s: (-s.current_streak, s.name))


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), AVERAGE_DIGITS) if values else None


async def _health(
    db: AsyncSession, now: _Span, before: _Span, starts_on: date, start: date, end: date
) -> list[WeekHealthMetric]:
    catalog = {
        metric.identifier: metric for metric in await health_crud.get_catalog(db)
    }
    present: list[HealthMetric] = [
        catalog[identifier]
        for _, _, identifier in HEALTH_SPECS
        if identifier in catalog
    ]
    daily = await health_crud.daily_values(db, present, start, end)

    metrics: list[WeekHealthMetric] = []
    for key, name, identifier in HEALTH_SPECS:
        metric = catalog.get(identifier)
        if metric is None:
            metrics.append(
                WeekHealthMetric(
                    key=key,
                    name=name,
                    available=False,
                    daily=[None] * DAYS_IN_WEEK,
                )
            )
            continue
        by_day = {point.local_date: point.value for point in daily.get(metric.id, [])}
        current = [by_day[d] for d in _dates(now) if d in by_day]
        earlier = [by_day[d] for d in _dates(before) if d in by_day]
        avg, previous_avg = _average(current), _average(earlier)
        metrics.append(
            WeekHealthMetric(
                key=key,
                name=name,
                unit=metric.canonical_unit,
                available=True,
                total=sum(current) if current else None,
                avg_per_day=avg,
                days_with_data=len(current),
                previous_avg_per_day=previous_avg,
                delta_avg_per_day=(
                    None
                    if avg is None or previous_avg is None
                    else round(avg - previous_avg, AVERAGE_DIGITS)
                ),
                daily=[
                    by_day.get(starts_on + timedelta(days=i))
                    if now.holds(starts_on + timedelta(days=i))
                    else None
                    for i in range(DAYS_IN_WEEK)
                ],
            )
        )
    return metrics


async def build_week_review(
    db: AsyncSession, iso: str, today: date
) -> WeekReviewResponse:
    """
    The review of the week `iso`, as of the logical day `today`.

    `week_bounds` raises `BadWeekCode` for a string that names no week; the API
    turns that into a 404. `today` is passed in rather than read here, so the one
    clock stays `app.core.daytime` and a test can pin it.
    """
    starts_on, ends_on = week_bounds(iso)
    now, before = _spans(starts_on, today)
    window_start, window_end = before.start, ends_on

    facts = _Facts(
        summaries=await _read_summaries(db, window_start, window_end),
        role_minutes=await _read_role_minutes(db, window_start, window_end),
    )
    totals, previous_totals = _totals(facts, now), _totals(facts, before)
    days = _days(facts, starts_on, now)
    best, worst = _best_and_worst(days)
    boundary = current_boundary()

    return WeekReviewResponse(
        window=WeekWindow(
            iso_code=iso,
            starts_on=starts_on,
            ends_on=ends_on,
            timezone=boundary.timezone,
            day_start_hour=boundary.day_start_hour,
            is_complete=today > ends_on,
            counted_days=now.days,
            as_of=now.end if now.days else None,
            previous_iso_code=iso_code(before.start),
            next_iso_code=iso_code(ends_on + timedelta(days=1)),
            compared_days=before.days,
        ),
        totals=totals,
        previous_totals=previous_totals,
        delta=_delta(totals, previous_totals),
        days=days,
        best_day=best,
        worst_day=worst,
        roles=await _roles(db, facts, now, before),
        categories=await _categories(db, now, before, window_start, window_end),
        habit_streaks=await _habit_streaks(db, now),
        health=await _health(db, now, before, starts_on, window_start, window_end),
    )


def week_has_data(review: WeekReviewResponse) -> bool:
    """Есть ли в неделе хоть что-то, о чём можно писать итог."""
    return bool(
        review.totals.closed_days
        or review.totals.tasks_total
        or review.totals.role_minutes
        or review.categories
        or any(metric.days_with_data for metric in review.health)
    )
