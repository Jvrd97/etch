# [review:need-review] PHASE-03/296
# summary: the dashboard summary in a fixed number of statements — categories, avoid histories, build entry days, day summaries, health catalogue/nights/buckets, workouts and challenges are each read once for the whole window and folded in python; streaks, windows and baselines come from the existing crud modules
"""
Database access for the dashboard summary (`#296`).

**Число запросов не зависит от данных.** Категории, истории «избегать», дни
привычек «строить», итоги дней, каталог и дни здоровья, тренировки и челленджи
читаются по одному запросу на всё окно, а раскладка по дням и категориям идёт в
питоне. Цикл «запрос на категорию» или «запрос на день» превратил бы дашборд в
десяток запросов; тест на класс ошибки держит число постоянным.

**Расчётов здесь нет, кроме склейки.** Серия считается `app.crud.streak`
(`get_category_streaks` для «избегать», `compute_streak` для «строить»), среднее
окна против личной нормы — `app.crud.health.compare_windows`, пороги нормы — из
`app.health.baseline`. Формулы колец названы в docstring `app.schemas.dashboard_summary`.

**Читает и ничего не пишет.** Статус челленджа читается как записан; вердикты
не материализуются, а текст инсайта собирается правилом из тех же чисел, без модели.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.crud import health as health_crud
from app.crud import streak as streak_crud
from app.health.aggregate import MetricKind
from app.health.baseline import BASELINE_DAYS, MIN_BASELINE_DAYS
from app.health.catalog import SLEEP_IDENTIFIER
from app.models import Category
from app.models.challenge import (
    STATUS_ACTIVE,
    STATUS_FAILED,
    STATUS_WON,
    Challenge,
)
from app.models.health import HealthMetric
from app.models.summary import STAGE_CLOSED, DaySummary
from app.schemas.dashboard_summary import (
    BestMetric,
    ChallengesScore,
    DashboardSummaryResponse,
    HabitsScore,
    HealthLabel,
    HealthScore,
    HealthState,
    Insight,
    Period,
    Scores,
    StreakItem,
    WorkoutsBlock,
    WorkoutWeek,
)

__all__ = ["build_dashboard_summary"]

PERIOD_DAYS: dict[Period, int] = {"week": 7, "month": 30}
# Недель на графике тренировок: четыре на неделю, восемь на месяц.
WORKOUT_WEEKS: dict[Period, int] = {"week": 4, "month": 8}
DAYS_IN_WEEK = 7
FULL_SHARE_PCT = 100
SECONDS_PER_MINUTE = 60

# Рекорд сравнивается с этим числом последних дней.
RECORD_LOOKBACK_DAYS = 90
# Меньше стольких дней с данными ключевых метрик кольцо «Здоровье» не считается.
MIN_SCORE_DAYS = 3
GOOD_FROM = 75
FAIR_FROM = 50

# Статусы челленджей, которые считаются: предложенный ещё не обязательство,
# брошенный человек сам вычеркнул из счёта.
COUNTED_CHALLENGE_STATUSES = (STATUS_ACTIVE, STATUS_WON, STATUS_FAILED)

# Правила инсайта.
SLEEP_GOOD_MINUTES = 7 * 60
MIN_INSIGHT_GROUP_DAYS = 2
MIN_INSIGHT_GAP_PCT = 10
MIN_INSIGHT_STREAK = 3


class KeyMetric(NamedTuple):
    """Ключевая метрика здоровья: идентификатор каталога и что в ней «лучше»."""

    identifier: str
    higher_is_better: bool


KEY_METRICS: tuple[KeyMetric, ...] = (
    KeyMetric(SLEEP_IDENTIFIER, True),
    KeyMetric("HKQuantityTypeIdentifierRestingHeartRate", False),
    KeyMetric("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", True),
    KeyMetric("HKQuantityTypeIdentifierStepCount", True),
    KeyMetric("HKQuantityTypeIdentifierActiveEnergyBurned", True),
)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _pct(part: int | float, whole: int | float) -> int:
    return round(part * FULL_SHARE_PCT / whole)


# --- streaks -----------------------------------------------------------------


def _avoid_item(
    category_id: int,
    name: str,
    stats: streak_crud.StreakStats,
    window: list[date],
) -> StreakItem | None:
    """Серия «избегать»; категория, которую ещё не вели, в сводку не попадает."""
    first = stats.tracked_since
    if first is None:
        return None
    relapses = set(stats.relapse_dates)
    return StreakItem(
        category_id=category_id,
        name=name,
        kind="avoid",
        current=stats.current_streak,
        best=stats.best_streak,
        days=[None if day < first else day not in relapses for day in window],
    )


def _build_item(
    category_id: int,
    name: str,
    entry_days: set[date],
    window: list[date],
    today: date,
) -> StreakItem | None:
    """
    Серия «строить»: подряд идущие дни с отметкой «сделано».

    День выполнен, если `app.crud.streak` назвал его днём с положительной отметкой
    (`is_relapse_entry`: галка `true`, число или длительность больше нуля, запись
    без значений). Снятая галка пишется как `false` и днём не считается.

    Сегодня без записи ещё не пропуск — день не кончился, — поэтому серия
    считается до вчера, а в полоске сегодня остаётся `null`. Расчёт — тот же
    `compute_streak`, которому дни без записи отданы как «сорванные».
    """
    if not entry_days:
        return None
    first = min(entry_days)
    end = today if today in entry_days else today - timedelta(days=1)
    missing = set(_days(first, end)) - entry_days
    stats = streak_crud.compute_streak(entry_days, missing, end)
    return StreakItem(
        category_id=category_id,
        name=name,
        kind="build",
        current=stats.current_streak,
        best=stats.best_streak,
        days=[
            None
            if day < first or (day == today and day not in entry_days)
            else day in entry_days
            for day in window
        ],
    )


async def _streaks(
    db: AsyncSession, window: list[date], today: date
) -> list[StreakItem]:
    categories = (
        await db.execute(
            select(Category.id, Category.name, Category.streak_mode).where(
                Category.is_active.is_(True)
            )
        )
    ).all()
    avoid = dict(await streak_crud.get_category_streaks(db, "avoid", today=today))
    # Для «строить» положительный день, который `app.crud.streak` называет
    # «срывом» у «избегать», и есть выполненный день.
    build = {
        category_id: {day for day in stats.relapse_dates if day <= today}
        for category_id, stats in await streak_crud.get_category_streaks(
            db, "build", today=today
        )
    }
    items: list[StreakItem | None] = []
    for category_id, name, mode in categories:
        if mode == "avoid" and category_id in avoid:
            items.append(_avoid_item(category_id, name, avoid[category_id], window))
        elif mode == "build":
            items.append(
                _build_item(
                    category_id, name, build.get(category_id, set()), window, today
                )
            )
    return sorted(
        (item for item in items if item is not None),
        key=lambda item: (-item.current, item.name),
    )


# --- rings: habits and challenges --------------------------------------------


async def _plan_days(
    db: AsyncSession, start: date, today: date
) -> dict[date, tuple[int, int]]:
    """
    Выполнено и запланировано по дням окна — из итогов закрытых дней.

    Касание «ревью» в 15:40 тоже пишет строку (`stage='reviewed'`) с числами на
    этот момент; незакрытый день в кольцо и в инсайт не входит.
    """
    result = await db.execute(
        select(
            DaySummary.day_date, DaySummary.tasks_done, DaySummary.tasks_total
        ).where(
            DaySummary.day_date.between(start, today),
            DaySummary.stage == STAGE_CLOSED,
        )
    )
    return {day: (done, total) for day, done, total in result.all()}


def _habits(plan: dict[date, tuple[int, int]]) -> HabitsScore:
    done = sum(d for d, _ in plan.values())
    total = sum(t for _, t in plan.values())
    if not total:
        return HabitsScore(value=None, done=None, total=None)
    return HabitsScore(value=_pct(done, total), done=done, total=total)


async def _challenges(db: AsyncSession, start: date, today: date) -> ChallengesScore:
    result = await db.execute(
        select(Challenge.status, func.count())
        .where(
            Challenge.status.in_(COUNTED_CHALLENGE_STATUSES),
            Challenge.starts_on <= today,
            Challenge.ends_on >= start,
        )
        .group_by(Challenge.status)
    )
    counts = {status: count for status, count in result.all()}
    total = sum(counts.values())
    if not total:
        return ChallengesScore(done=None, total=None)
    return ChallengesScore(done=counts.get(STATUS_WON, 0), total=total)


# --- health ------------------------------------------------------------------


@dataclass(frozen=True)
class _Health:
    score: HealthScore
    states: list[HealthState]
    bests: list[BestMetric]
    sleep: dict[date, float]


def _closeness(value: float, norm: float, higher_is_better: bool) -> float | None:
    """Доля 0..1: не хуже нормы — 1, на 10 % хуже — 0,9. Нормы нет — `None`."""
    if norm <= 0:
        return None
    if higher_is_better:
        return min(1.0, max(value, 0.0) / norm)
    return None if value <= 0 else min(1.0, norm / value)


def _label(value: int) -> HealthLabel:
    if value >= GOOD_FROM:
        return "good"
    return "fair" if value >= FAIR_FROM else "poor"


async def _health(db: AsyncSession, window: list[date], today: date) -> _Health:
    start = window[0]
    catalog = {m.identifier: m for m in await health_crud.get_catalog(db)}
    key = [
        (spec, catalog[spec.identifier])
        for spec in KEY_METRICS
        if spec.identifier in catalog
    ]
    daily = await health_crud.daily_values(
        db,
        [metric for _, metric in key],
        today - timedelta(days=RECORD_LOOKBACK_DAYS - 1),
        today,
    )
    earlier = [start - timedelta(days=i) for i in range(1, BASELINE_DAYS + 1)]

    shares: list[float] = []
    basis: set[date] = set()
    states: list[HealthState] = []
    bests: list[BestMetric] = []
    sleep: dict[date, float] = {}
    for spec, metric in key:
        by_day = {p.local_date: p.value for p in daily.get(metric.id, [])}
        if spec.identifier == SLEEP_IDENTIFIER:
            sleep = by_day
        # Сегодняшний неполный день шагов и энергии не сравнивается с целыми.
        cumulative = MetricKind(metric.kind) is MetricKind.CUMULATIVE
        counted = [day for day in window if not (cumulative and day == today)]
        compared = health_crud.compare_windows(by_day, counted, earlier)
        if compared.avg_per_day is None:
            continue
        has_norm = compared.previous_days_with_data >= MIN_BASELINE_DAYS
        if has_norm and compared.previous_avg_per_day is not None:
            share = _closeness(
                compared.avg_per_day,
                compared.previous_avg_per_day,
                spec.higher_is_better,
            )
            if share is not None:
                shares.append(share)
                # Дни метрики без нормы в кольцо не идут, значит, и в основание.
                basis.update(day for day in counted if day in by_day)
        states.append(
            HealthState(
                identifier=metric.identifier,
                label=metric.display_name,
                value=round(compared.avg_per_day),
                unit=metric.canonical_unit,
                baseline_delta=(
                    round(compared.delta_avg_per_day)
                    if has_norm and compared.delta_avg_per_day is not None
                    else None
                ),
                higher_is_better=spec.higher_is_better,
            )
        )
        best = _best_day(metric, spec, by_day, counted, today if cumulative else None)
        if best is not None:
            bests.append(best)

    enough = len(basis) >= MIN_SCORE_DAYS and bool(shares)
    value = round(FULL_SHARE_PCT * fmean(shares)) if enough else None
    return _Health(
        score=HealthScore(
            value=value,
            label=_label(value) if value is not None else None,
            basis_days=len(basis),
        ),
        states=states,
        bests=bests,
        sleep=sleep,
    )


def _best_day(
    metric: HealthMetric,
    spec: KeyMetric,
    by_day: dict[date, float],
    counted: list[date],
    partial_day: date | None,
) -> BestMetric | None:
    """Лучший день окна и признак рекорда за `RECORD_LOOKBACK_DAYS`."""
    shown = sorted(
        ((by_day[day], day) for day in counted if day in by_day),
    )
    if not shown:
        return None
    value, day = shown[-1] if spec.higher_is_better else shown[0]
    others = [
        other
        for other_day, other in by_day.items()
        if other_day != day and other_day != partial_day
    ]
    is_record = len(others) >= MIN_BASELINE_DAYS and (
        value > max(others) if spec.higher_is_better else value < min(others)
    )
    return BestMetric(
        identifier=spec.identifier,
        label=metric.display_name,
        value=round(value),
        unit=metric.canonical_unit,
        date=day,
        is_record=is_record,
    )


# --- workouts ----------------------------------------------------------------


async def _workouts(
    db: AsyncSession, period: Period, start: date, today: date
) -> WorkoutsBlock:
    window_days = PERIOD_DAYS[period]
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(
        days=DAYS_IN_WEEK * (WORKOUT_WEEKS[period] - 1)
    )
    previous_start = start - timedelta(days=window_days)
    rows = await health_crud.workouts_between(
        db, min(first_monday, previous_start), today
    )
    if not rows:
        return WorkoutsBlock(weeks=[], total=None, delta_vs_previous=None)

    weeks = [
        first_monday + timedelta(days=DAYS_IN_WEEK * i)
        for i in range(WORKOUT_WEEKS[period])
    ]
    minutes_by_week: dict[date, list[float]] = {week: [] for week in weeks}
    for workout in rows:
        monday = workout.local_date - timedelta(days=workout.local_date.weekday())
        if monday in minutes_by_week:
            minutes_by_week[monday].append(workout.duration_min)
    chart = [
        WorkoutWeek(week_start=week, count=len(spent), minutes=round(sum(spent)))
        for week, spent in minutes_by_week.items()
    ]
    total = sum(1 for w in rows if start <= w.local_date <= today)
    previous = sum(1 for w in rows if previous_start <= w.local_date < start)
    return WorkoutsBlock(weeks=chart, total=total, delta_vs_previous=total - previous)


# --- insight -----------------------------------------------------------------


def _sleep_insight(
    plan: dict[date, tuple[int, int]], sleep: dict[date, float]
) -> str | None:
    """Доля плана в дни со сном от 7 ч против остальных дней, если разница заметна."""
    rested: list[tuple[int, int]] = []
    short: list[tuple[int, int]] = []
    for day, (done, total) in plan.items():
        if not total or day not in sleep:
            continue
        (rested if sleep[day] >= SLEEP_GOOD_MINUTES else short).append((done, total))
    if min(len(rested), len(short)) < MIN_INSIGHT_GROUP_DAYS:
        return None
    rested_pct = _pct(sum(d for d, _ in rested), sum(t for _, t in rested))
    short_pct = _pct(sum(d for d, _ in short), sum(t for _, t in short))
    if rested_pct - short_pct < MIN_INSIGHT_GAP_PCT:
        return None
    return (
        f"В дни со сном от 7 ч закрыто {rested_pct} % плана ({len(rested)} дн.), "
        f"в остальные — {short_pct} % ({len(short)} дн.)."
    )


def _streak_insight(streaks: list[StreakItem]) -> str | None:
    """Самая длинная текущая серия, если она не короче `MIN_INSIGHT_STREAK`."""
    if not streaks or streaks[0].current < MIN_INSIGHT_STREAK:
        return None
    top = streaks[0]
    run = f"без срывов {top.current}" if top.kind == "avoid" else f"{top.current}"
    return f"«{top.name}» — {run} дн. подряд (лучший результат {top.best})."


def _insight(
    plan: dict[date, tuple[int, int]],
    sleep: dict[date, float],
    streaks: list[StreakItem],
) -> Insight | None:
    text = _sleep_insight(plan, sleep) or _streak_insight(streaks)
    if text is None:
        return None
    boundary = daytime.current_boundary()
    return Insight(
        text=text,
        generated_at=daytime.now_utc().astimezone(ZoneInfo(boundary.timezone)),
    )


# --- the whole answer --------------------------------------------------------


async def build_dashboard_summary(
    db: AsyncSession, period: Period, today: date
) -> DashboardSummaryResponse:
    """
    The dashboard for the last 7 (`week`) or 30 (`month`) days ending `today`.

    `today` is passed in rather than read here, so the one clock stays
    `app.core.daytime` and a test can pin it.
    """
    window = _days(today - timedelta(days=PERIOD_DAYS[period] - 1), today)
    start = window[0]

    plan = await _plan_days(db, start, today)
    streaks = await _streaks(db, window, today)
    health = await _health(db, window, today)
    return DashboardSummaryResponse(
        period=period,
        from_=start,
        to=today,
        today=today,
        scores=Scores(
            health=health.score,
            habits=_habits(plan),
            challenges=await _challenges(db, start, today),
        ),
        streaks=streaks,
        health=health.states,
        bests=health.bests,
        workouts=await _workouts(db, period, start, today),
        insight=_insight(plan, health.sleep, streaks),
    )
