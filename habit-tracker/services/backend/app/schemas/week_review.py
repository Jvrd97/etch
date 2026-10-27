# [review:need-review] PHASE-03/221
# summary: wire types of the week review — one answer carrying the window of the week, totals against the previous week, days, role and category time, habit streaks and health, plus the AI narrative response
"""
Wire types of the week review (`#221`).

**Одно имя для счёта «сколько дней учтено».** `counted_days` — это сколько дней
недели уже попало в цифры. У завершённой недели их семь, у текущей — прошедшие
по сегодня включительно. Прошлая неделя берётся за столько же дней (`compared_days`),
иначе вторник текущей недели сравнивался бы с целой прошлой и всегда проигрывал.

**Дельты считает сервер.** Экран и iOS получают готовую разность: второе
вычитание на клиенте разошлось бы с первым на первом же округлении.

**`null` — это «нет данных», не ноль.** `plan_pct`, `work_minutes`, `avg_per_day`
пусты, когда мерить было нечего; ноль утверждал бы, что измерили и получили ноль.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class WeekWindow(BaseModel):
    """Which days the numbers cover and in which clock they were cut."""

    iso_code: str
    starts_on: date
    ends_on: date
    timezone: str = Field(
        ..., description="IANA-пояс, по которому режутся сутки недели"
    )
    day_start_hour: int = Field(
        ..., description="Час, с которого в этом поясе начинается день"
    )
    is_complete: bool = Field(
        ...,
        description=(
            "Неделя закончилась: её воскресенье уже позади. false — неделя идёт "
            "или ещё не началась, и цифры неполные"
        ),
    )
    counted_days: int = Field(
        ..., description="Сколько дней недели учтено в цифрах: 7, если неделя полная"
    )
    as_of: date | None = Field(
        None, description="Последний учтённый день; null — ни один день не наступил"
    )
    previous_iso_code: str
    next_iso_code: str
    compared_days: int = Field(
        ..., description="За сколько первых дней прошлой недели взяты цифры сравнения"
    )


class WeekTotals(BaseModel):
    """What a stretch of days added up to."""

    closed_days: int = Field(0, description="Дни с вердиктом")
    won_days: int = 0
    lost_days: int = 0
    tasks_done: int = 0
    tasks_total: int = 0
    plan_pct: int | None = Field(
        None, description="Доля выполненных рабочих задач, %; null — задач не было"
    )
    anchors_done: int = 0
    anchors_total: int = 0
    work_minutes: int | None = Field(
        None, description="Измеренные рабочие минуты; null — не измерено ни в один день"
    )
    role_minutes: int = Field(0, description="Минуты, разложенные по ролям")
    day_streak_end: int | None = Field(
        None,
        description=(
            "Стрик дней после последнего закрытого дня отрезка; null — "
            "ни один день не закрыт"
        ),
    )


class WeekDelta(BaseModel):
    """Эта неделя минус прошлая за столько же дней."""

    won_days: int
    tasks_done: int
    plan_pct: int | None = Field(
        None,
        description="Разность долей в процентных пунктах; null — не с чем сравнить",
    )
    work_minutes: int | None = None
    role_minutes: int


class WeekDayStat(BaseModel):
    """One day of the week, in the order Monday to Sunday."""

    date: date
    weekday: int = Field(..., description="0 — понедельник, 6 — воскресенье")
    counted: bool = Field(..., description="День уже наступил и учтён в цифрах")
    verdict: str | None = None
    tasks_done: int = 0
    tasks_total: int = 0
    plan_pct: int | None = None
    work_minutes: int | None = None
    role_minutes: int = 0
    streak_after: int | None = None


class WeekRoleSlice(BaseModel):
    """Time of one role: this week, the previous one and the gap."""

    role_id: int
    role_code: str
    title: str
    minutes: int
    share_pct: int
    target_share_pct: int | None = None
    previous_minutes: int
    delta_minutes: int


class WeekCategorySlice(BaseModel):
    """Time of one habit category (`duration` fields), and the days it was logged."""

    category_id: int
    name: str
    minutes: int
    previous_minutes: int
    delta_minutes: int
    entry_days: int = Field(..., description="Дней недели, в которые есть записи")
    previous_entry_days: int


class WeekHabitStreak(BaseModel):
    """Серия категории «избегать» на конец учтённого отрезка недели."""

    category_id: int
    name: str
    current_streak: int
    relapses: int = Field(..., description="Срывов за учтённые дни недели")


class WeekHealthMetric(BaseModel):
    """One health figure of the week against the previous one."""

    key: str = Field(..., description="sleep | steps | workouts")
    name: str
    unit: str | None = Field(
        None, description="Единица из каталога: count, min, …; null — метрики нет"
    )
    available: bool = Field(
        ..., description="Метрика заведена в каталоге; false — данных не может быть"
    )
    total: float | None = None
    avg_per_day: float | None = None
    days_with_data: int = 0
    previous_avg_per_day: float | None = None
    delta_avg_per_day: float | None = None
    daily: list[float | None] = Field(
        default_factory=list, description="Семь значений Пн..Вс; null — нет данных"
    )


class WeekReviewResponse(BaseModel):
    """The week in one answer."""

    window: WeekWindow
    totals: WeekTotals
    previous_totals: WeekTotals
    delta: WeekDelta
    days: list[WeekDayStat]
    best_day: date | None = Field(
        None, description="Лучший из судимых дней: выигранный, затем по доле плана"
    )
    worst_day: date | None = Field(
        None, description="Худший из судимых дней; null, если хуже лучшего нет"
    )
    roles: list[WeekRoleSlice]
    categories: list[WeekCategorySlice]
    habit_streaks: list[WeekHabitStreak]
    health: list[WeekHealthMetric]


class WeekNarrativeResponse(BaseModel):
    """Текст итога недели, написанный моделью по цифрам ответа."""

    iso_code: str
    text: str
    model: str
