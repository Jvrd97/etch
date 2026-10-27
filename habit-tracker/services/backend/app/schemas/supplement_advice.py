# [review:need-review] PHASE-03/223
# summary: wire types of the health summary (sleep, steps, workouts, resting heart rate against the previous window, supplement adherence per day) and of the advice written from it
"""
Wire types of the health summary and the advice (`#223`).

**`null` — это «нет данных», не ноль.** У фигуры без дней с данными `avg_per_day`
пуст; `available=false` говорит, что метрики нет в каталоге вовсе (сон до #238).
`enough_data` — один порог для сводки и совета: на меньшем числе дней среднее
ничего не доказывает, и совет по нему не пишется.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

MIN_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 14


class SummaryWindow(BaseModel):
    starts_on: date
    ends_on: date = Field(
        ..., description="Последний прошедший логический день; сегодня не входит"
    )
    days: int
    previous_starts_on: date
    previous_ends_on: date


class HealthFigure(BaseModel):
    """Одна метрика здоровья за окно против такого же окна до него."""

    key: str = Field(..., description="sleep | steps | workouts | resting_hr")
    name: str
    unit: str | None = None
    available: bool = Field(
        ..., description="Метрика есть в каталоге; false — данных не будет вовсе"
    )
    days_with_data: int = 0
    enough_data: bool = False
    avg_per_day: float | None = None
    previous_days_with_data: int = 0
    previous_avg_per_day: float | None = None
    delta_avg_per_day: float | None = None


class AdherenceDay(BaseModel):
    date: date
    planned: int
    taken: int


class SupplementAdherenceItem(BaseModel):
    supplement_id: int
    name: str
    planned_days: int
    taken_days: int


class Adherence(BaseModel):
    """Принято из запланированного; приём вне плана считается и в плане."""

    planned: int
    taken: int
    pct: int | None = Field(None, description="null, если планировать было нечего")
    enough_data: bool
    days: list[AdherenceDay]
    supplements: list[SupplementAdherenceItem]


class HealthSummaryResponse(BaseModel):
    window: SummaryWindow
    figures: list[HealthFigure]
    adherence: Adherence
    enough_data: bool = Field(
        ..., description="Хоть один блок набрал достаточно дней для совета"
    )


class HealthAdviceRequest(BaseModel):
    days: int = Field(MIN_WINDOW_DAYS, ge=MIN_WINDOW_DAYS, le=MAX_WINDOW_DAYS)


class HealthAdviceResponse(BaseModel):
    text: str
    model: str
    starts_on: date
    ends_on: date
    days: int
