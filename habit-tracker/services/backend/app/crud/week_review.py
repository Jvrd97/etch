# [review:need-review] PHASE-03/221, PHASE-03/245, PHASE-03/239, PHASE-03/255, PHASE-03/244
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

**Сегодняшний день учитывается, только когда он закрыт.** Итог дня появляется
вечером, и до этого строки `day_summary` за сегодня нет: учти мы сегодня, неделя
сравнивалась бы по понедельнику-вторнику против понедельника-среды прошлой, то
есть с лишним днём в знаменателе. Минуты ролей и здоровье сегодняшнего дня тоже
не входят, пока день не закрыт, — окно одно на все блоки.

**Доли ролей считает `app.crud.role`.** Минуты по ролям берутся у
`role_crud.minutes_by_role`, доля — у `share_pct`: вторая реализация разошлась
бы с недельной сводкой ролей на первом округлении.

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
from app.crud import day_profile as profile_crud
from app.crud import health as health_crud
from app.crud import role as role_crud
from app.crud import streak as streak_crud
from app.crud import supplement_advice as advice_crud
from app.crud.values import parse_number
from app.day.debt import week_is_won, week_verdict_line
from app.day.evaluate import VERDICT_LOST, VERDICT_WON
from app.day.week import DAYS_IN_WEEK, iso_code, week_bounds
from app.models import Category, Entry, EntryValue, Field
from app.models.day import Day
from app.models.field import FieldType
from app.models.role import RoleTimeBlock
from app.models.summary import STAGE_CLOSED, DaySummary
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
from app.schemas.supplement_advice import Adherence

__all__ = ["build_week_review", "week_has_data"]

# Знаменатель доли в целых процентах.
FULL_SHARE_PCT = 100
SECONDS_PER_MINUTE = 60
# Метрики здоровья недели: ключи из `app.crud.health.HEALTH_SPECS`. Пульс покоя
# в обзор не входит — он живёт в совете (#223).
WEEK_METRICS = ("sleep", "steps", "workouts")


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
    closed: bool


@dataclass
class _Facts:
    """Всё, что прочитано из базы за четырнадцать дней, ещё не разложенное по неделям."""

    summaries: dict[date, _Summary] = field(default_factory=dict)
    day_minutes: dict[date, int] = field(default_factory=dict)
    day_rows: set[date] = field(default_factory=set)


def _pct(part: int, whole: int) -> int | None:
    """Доля в целых процентах; пустой знаменатель — «не с чем делить», не ноль."""
    return round(part * FULL_SHARE_PCT / whole) if whole else None


def _spans(starts_on: date, today: date, today_closed: bool) -> tuple[_Span, _Span]:
    """
    Учтённые дни этой недели и столько же первых дней прошлой.

    Сегодня входит, только если день закрыт; прошедшие дни — всегда. Законченная
    неделя даёт семь, как бы ни закрыт был её последний день.
    """
    counted = min(
        max((today - starts_on).days + (1 if today_closed else 0), 0), DAYS_IN_WEEK
    )
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
            DaySummary.stage,
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
            closed=row.stage == STAGE_CLOSED,
        )
        for row in result
    }


async def _read_day_minutes(
    db: AsyncSession, start: date, end: date
) -> dict[date, int]:
    """Минуты ролей по дням — только для колонки дней; доли считает `role_crud`."""
    result = await db.execute(
        select(RoleTimeBlock.work_day, func.sum(RoleTimeBlock.minutes))
        .where(RoleTimeBlock.work_day.between(start, end))
        .group_by(RoleTimeBlock.work_day)
    )
    return {day: int(total) for day, total in result.all()}


async def _read_day_rows(db: AsyncSession, start: date, end: date) -> set[date]:
    """Дни, заведённые в базе: знаменатель правила «неделя выиграна»."""
    result = await db.execute(
        select(Day.day_date).where(Day.day_date.between(start, end))
    )
    return set(result.scalars().all())


async def _span_minutes(db: AsyncSession, span: _Span) -> dict[int, int]:
    """Минуты по ролям за учтённые дни отрезка — свёртка недельной сводки ролей."""
    if span.days == 0:
        return {}
    return await role_crud.minutes_by_role(db, span.start, span.end)


def _totals(facts: _Facts, span: _Span, role_minutes: int) -> WeekTotals:
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
        role_minutes=role_minutes,
        days_total=sum(1 for day in _dates(span) if day in facts.day_rows),
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
                role_minutes=facts.day_minutes.get(on, 0) if counted else 0,
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
    db: AsyncSession, now: dict[int, int], before: dict[int, int]
) -> list[WeekRoleSlice]:
    roles = await role_crud.list_roles(db)
    whole = sum(now.values())
    return [
        WeekRoleSlice(
            role_id=role.id,
            role_code=role.code,
            title=role.title,
            minutes=(own := now.get(role.id, 0)),
            share_pct=role_crud.share_pct(own, whole),
            target_share_pct=role.target_share_pct,
            previous_minutes=(previous := before.get(role.id, 0)),
            delta_minutes=own - previous,
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


async def _health(
    db: AsyncSession, now: _Span, before: _Span, starts_on: date, start: date, end: date
) -> list[WeekHealthMetric]:
    metrics: list[WeekHealthMetric] = []
    for item in await health_crud.metric_days(db, WEEK_METRICS, start, end):
        if not item.available:
            metrics.append(
                WeekHealthMetric(
                    key=item.spec.key,
                    name=item.name,
                    available=False,
                    daily=[None] * DAYS_IN_WEEK,
                )
            )
            continue
        compared = health_crud.compare_windows(item.by_day, _dates(now), _dates(before))
        metrics.append(
            WeekHealthMetric(
                key=item.spec.key,
                name=item.name,
                unit=item.unit,
                available=True,
                total=compared.total,
                avg_per_day=compared.avg_per_day,
                days_with_data=compared.days_with_data,
                previous_days_with_data=compared.previous_days_with_data,
                previous_avg_per_day=compared.previous_avg_per_day,
                delta_avg_per_day=compared.delta_avg_per_day,
                daily=[
                    item.by_day.get(starts_on + timedelta(days=i))
                    if now.holds(starts_on + timedelta(days=i))
                    else None
                    for i in range(DAYS_IN_WEEK)
                ],
            )
        )
    return metrics


async def _supplements(db: AsyncSession, now: _Span) -> Adherence | None:
    """
    Приём добавок за учтённые дни — расчёт совета (`advice_crud`), а не второй.

    Добавок на этих днях не планировалось — `None`: у недели без добавок ответ
    остаётся таким, каким был, и экран не рисует пустой блок.
    """
    if now.days == 0:
        return None
    adherence = await advice_crud.adherence_for_days(db, _dates(now))
    return adherence if adherence.planned else None


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
    window_start, window_end = starts_on - timedelta(days=DAYS_IN_WEEK), ends_on

    summaries = await _read_summaries(db, window_start, window_end)
    today_row = summaries.get(today)
    now, before = _spans(starts_on, today, today_row is not None and today_row.closed)

    facts = _Facts(
        summaries=summaries,
        day_minutes=await _read_day_minutes(db, window_start, window_end),
        day_rows=await _read_day_rows(db, window_start, window_end),
    )
    minutes_now, minutes_before = (
        await _span_minutes(db, now),
        await _span_minutes(db, before),
    )
    totals = _totals(facts, now, sum(minutes_now.values()))
    previous_totals = _totals(facts, before, sum(minutes_before.values()))
    # Правило выигранной недели — одно, `app.day.debt.week_is_won`, как у `/weeks`:
    # все дни выиграны, дни есть и долга за переработку нет. Решается только для
    # законченной недели; идущая ещё не выиграна и не проиграна.
    debt = await profile_crud.open_debt_minutes(db, starts_on, ends_on)
    complete = today > ends_on
    is_won = week_is_won(totals.won_days, totals.days_total, debt) if complete else None
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
            is_complete=complete,
            counted_days=now.days,
            today_counted=now.holds(today),
            as_of=now.end if now.days else None,
            previous_iso_code=iso_code(before.start),
            next_iso_code=iso_code(ends_on + timedelta(days=1)),
            compared_days=before.days,
        ),
        totals=totals,
        previous_totals=previous_totals,
        delta=_delta(totals, previous_totals),
        debt_minutes=debt,
        is_won=is_won,
        verdict_line=week_verdict_line(
            is_won, totals.won_days, totals.days_total, debt, as_hours=True
        ),
        days=days,
        best_day=best,
        worst_day=worst,
        roles=await _roles(db, minutes_now, minutes_before),
        categories=await _categories(db, now, before, window_start, window_end),
        habit_streaks=await _habit_streaks(db, now),
        health=await _health(db, now, before, starts_on, window_start, window_end),
        supplements=await _supplements(db, now),
    )


def week_has_data(review: WeekReviewResponse) -> bool:
    """Есть ли в неделе хоть что-то, о чём можно писать итог."""
    return bool(
        review.totals.closed_days
        or review.totals.tasks_total
        or review.totals.role_minutes
        or review.categories
        or review.habit_streaks
        or any(metric.days_with_data for metric in review.health)
    )
