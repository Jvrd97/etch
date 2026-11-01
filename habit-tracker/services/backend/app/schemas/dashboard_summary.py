# [review:need-review] PHASE-03/296
# summary: wire types of GET /dashboard/summary — the three rings, streaks with their day strips, health state, bests, workout weeks and one ready-made insight, with the formulas of the health and habits rings in the docstring
# [review:need-review] 309
# summary: `Part` — the part of the summary a screen can ask for alone (`health`, #309)
"""
Wire types of the dashboard summary (`#296`).

One answer for the whole dashboard, so that the web and iOS do not glue ten
requests together. The window is cut on the day of the server (`today_local()`),
not on UTC and not on the client's clock: `week` is the last 7 days and `month`
the last 30, both ending today.

**`null` — это «нет данных», не ноль.** Блок без данных приходит `null` или
пустым списком. Исключение одно: счётчик дней `basis_days` — это число, и ноль в
нём честный.

**Кольцо «Здоровье» (`scores.health`).** Ключевые метрики: сон, пульс покоя, ВСР,
шаги, активная энергия. Для каждой, у которой есть данные в окне и личная норма,
считается доля `s`:

- норма — среднее за день по 30 дням *до* окна, если в них не меньше 7 дней с
  данными (то же правило, что у `app.health.baseline`);
- значение — среднее за день в окне, по дням с данными; у накопительных метрик
  (шаги, энергия) сегодняшний неполный день не входит;
- у метрики, где больше — лучше (сон, ВСР, шаги, энергия), `s = min(1, значение / норма)`;
  у пульса покоя, где меньше — лучше, `s = min(1, норма / значение)`.

Метрика не хуже нормы даёт 1, на 10 % хуже — 0,9: вес идёт по близости к норме, а не
«прошла или нет». `value = round(100 * среднее s)`. Метрика без нормы в кольцо не
входит, но видна в `health`. `value` — `null`, если основание (`basis_days`)
меньше `MIN_SCORE_DAYS` (3) дней или ни у одной метрики нет нормы;
`basis_days` — на скольких днях окна посчитано: дни метрик, давших долю `s`
(метрика без нормы в основание не входит). `label`:
`good` от 75, `fair` от 50, иначе `poor`.

**Блок `health`.** Только ключевые метрики, у которых в окне есть данные: метрики
без данных в списке нет, клиент показывает то, что пришло.

**Кольцо «Привычки» (`scores.habits`).** Доля выполненных пунктов плана за окно:
`done` и `total` — суммы `tasks_done` и `tasks_total` из итогов дней (`day_summary`),
`value = round(100 * done / total)`. В кольцо входят только закрытые дни
(`stage='closed'`): касание «ревью» в 15:40 пишет строку с неполными числами, и она
не считается. Нет ни одного пункта плана — всё `null`.

**Кольцо «Челленджи» (`scores.challenges`).** `total` — обязательства, чьё окно
пересекает окно сводки, в статусах `active`, `won`, `failed` (предложенные и
брошенные не считаются); `done` — из них `won`. Статус читается как записан:
сводка ничего не пересчитывает и не пишет.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import CategoryStreakMode

Period = Literal["week", "month"]
# A part of the summary a screen can ask for alone; absent is the whole summary.
Part = Literal["health"]
HealthLabel = Literal["good", "fair", "poor"]


class HealthScore(BaseModel):
    """Кольцо «Здоровье»: 0..100 и подпись, `null` при менее чем 3 днях данных."""

    value: int | None
    label: HealthLabel | None
    basis_days: int = Field(
        ..., description="Дней окна, на которых посчитано кольцо (дни метрик с нормой)"
    )


class HabitsScore(BaseModel):
    """Кольцо «Привычки»: доля выполненных пунктов плана за окно."""

    value: int | None
    done: int | None
    total: int | None


class ChallengesScore(BaseModel):
    """Кольцо «Челленджи»: сколько выполнено из тех, что шли в окне."""

    done: int | None
    total: int | None


class Scores(BaseModel):
    health: HealthScore
    habits: HabitsScore
    challenges: ChallengesScore


class StreakItem(BaseModel):
    """Серия одной категории и полоска дней окна."""

    category_id: int
    name: str
    kind: CategoryStreakMode
    current: int
    best: int
    days: list[bool | None] = Field(
        ...,
        description=(
            "Последние 7 (week) или 30 (month) дней, старые первыми: true — "
            "выполнено / чисто, false — пропуск / срыв, null — нет данных"
        ),
    )


class HealthState(BaseModel):
    """Ключевая метрика с данными в окне: среднее за день и сдвиг от личной нормы."""

    identifier: str
    label: str
    value: int
    unit: str
    baseline_delta: int | None
    higher_is_better: bool = Field(
        ...,
        description="true — больше лучше (сон, ВСР, шаги, энергия); false — пульс покоя",
    )


class BestMetric(BaseModel):
    """Лучший день окна по метрике и признак личного рекорда."""

    identifier: str
    label: str
    value: int
    unit: str
    date: date
    is_record: bool = Field(
        ...,
        description=(
            "Лучше любого другого дня за последние 90 дней; без хотя бы 7 других "
            "дней для сравнения — false"
        ),
    )


class WorkoutWeek(BaseModel):
    week_start: date
    count: int
    minutes: int


class WorkoutsBlock(BaseModel):
    """Динамика тренировок по неделям (с понедельника) и счёт окна против предыдущего."""

    weeks: list[WorkoutWeek]
    total: int | None
    delta_vs_previous: int | None


class Insight(BaseModel):
    """Готовый текст из данных сводки: правило, а не вызов модели."""

    text: str
    generated_at: datetime


class DashboardSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    period: Period
    from_: date = Field(..., alias="from")
    to: date
    today: date
    scores: Scores
    streaks: list[StreakItem]
    health: list[HealthState]
    bests: list[BestMetric]
    workouts: WorkoutsBlock
    insight: Insight | None
