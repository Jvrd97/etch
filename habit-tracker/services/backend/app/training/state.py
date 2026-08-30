# [review:need-review] PHASE-03/92
# summary: the state of the body as one pure function — `recompute(days, complaints, as_of)` folds `training_day` and `body_complaint` into the snapshot `training_state` stores, so the snapshot is derived and two recomputes in a row differ only by `recomputed_at`
"""
Состояние тренировок как чистая функция, без базы.

`training/state.md` держал эти факты динамическими ключами frontmatter —
`planned_2026-08-30`, `done_2026-08-30`, `skipped_2026-08-14`. Свёрнутая в YAML
таблица не запрашивается, не считается и портится одной опечаткой в дате: «pull
не подтверждён с 17.08» приходилось считать человеку, читая прозу. Ключи
развёрнуты в строки `training_day`, а `training_state` стал **снимком**, а не
источником: всё, что в нём есть, — значение этой функции от строк.

**Снимок не хранит ничего, чего не выводит.** Единственное исключение —
`progression_stage`: «объём 4x6-8 RIR 1-2» это решение человека про ближайшие
четыре недели, а не следствие того, что было. Оно живёт в той же строке, но
сюда не приходит и пересчётом не трогается — поэтому два пересчёта подряд дают
то же самое и двигают только `recomputed_at`.

**Дни позже даты пересчёта не считаются.** Запись на завтра — план, а не факт:
она не делает завтрашний паттерн последним тяжёлым и не обрывает серию
пропусков, которая идёт по сегодня. Именно поэтому дата передаётся аргументом.

**Неделя считается от понедельника.** `week_sets` в файле всегда был «счётчик с
понедельника», и гейт недельного объёма сравнивает с шестнадцатью именно его.
Календарная неделя, а не «последние семь дней»: канон ротации написан по дням
недели.

**Жалобы участвуют.** Открытые области тела — часть ответа на «в каком
состоянии тело сейчас», и `/train` читает их вместе с датами последних
паттернов. В самой строке `training_state` колонки для них нет и не нужно:
`body_complaint` — своя таблица, а снимок называет только области, чтобы гейт
жалобы (`app.training.gates`) не ходил за ними отдельно.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models.training import (
    COMPLAINT_OPEN,
    PATTERN_CARDIO,
    PATTERN_LEGS,
    PATTERN_PULL,
    PATTERN_PUSH,
    PATTERN_RUN,
)

__all__ = [
    "ComplaintFact",
    "TrainingDayFact",
    "TrainingSnapshot",
    "recompute",
    "week_start",
]


@dataclass(frozen=True)
class TrainingDayFact:
    """
    One day of training as plain values — one row of `training_day`.

    A record rather than the ORM object so the whole fold is testable without a
    session, by the same reasoning as `app.day.evaluate`: the truth table of
    «два пропуска подряд дают skipped_days = 2» runs in milliseconds.
    """

    day_date: date
    patterns: tuple[str, ...] = ()
    heavy_patterns: tuple[str, ...] = ()
    sets: Mapping[str, int] = field(default_factory=dict)
    skipped: bool = False
    outdoor_done: bool | None = None
    near_failure: bool = False


@dataclass(frozen=True)
class ComplaintFact:
    """One row of `body_complaint`, reduced to what the state has to know."""

    area: str
    opened_on: date
    status: str = COMPLAINT_OPEN


@dataclass(frozen=True)
class TrainingSnapshot:
    """
    The answer to «в каком состоянии тело сейчас», as of one date.

    Everything here is derived. `open_complaints` carries the areas rather than
    the rows because that is what a gate weighs, and because a complaint is a
    symptom for a gate and not a medical record — the context and the severity
    stay in their own table and never travel with the state.
    """

    as_of: date
    week_starts_on: date
    last_heavy_pull: date | None = None
    last_heavy_push: date | None = None
    last_legs: date | None = None
    last_run: date | None = None
    last_outdoor: date | None = None
    last_cardio: date | None = None
    near_failure_days: tuple[date, ...] = ()
    week_sets: Mapping[str, int] = field(default_factory=dict)
    skipped_days: int = 0
    open_complaints: tuple[str, ...] = ()


def week_start(on: date) -> date:
    """The Monday of the ISO week `on` belongs to."""
    return on - timedelta(days=on.isoweekday() - 1)


def _latest(days: Iterable[TrainingDayFact], of: str, *, heavy: bool) -> date | None:
    """
    The most recent day that trained `of`, or None if none did.

    `heavy` picks `heavy_patterns` over `patterns`, and the distinction is the
    whole of the 48-hour gate: «один подход подтягиваний, сколько идёт» is a
    pull day that must not block tomorrow's pull day.
    """
    found = [
        one.day_date
        for one in days
        if of in (one.heavy_patterns if heavy else one.patterns)
    ]
    return max(found) if found else None


def _trailing_skips(days: Sequence[TrainingDayFact]) -> int:
    """
    Consecutive skipped days ending at the last recorded one.

    Contiguity is required: two skipped days a week apart are two separate
    lapses, and calling them a streak would put a returning week at minus thirty
    percent for no reason. A day that is present and not skipped ends the run,
    and so does a gap in the dates — nothing is known about a date with no row.
    """
    count = 0
    previous: date | None = None
    for one in reversed(days):
        if not one.skipped:
            break
        if previous is not None and previous - one.day_date != timedelta(days=1):
            break
        count += 1
        previous = one.day_date
    return count


def _week_sets(days: Iterable[TrainingDayFact], since: date) -> dict[str, int]:
    """Sets per pattern from `since` onwards — the counter of the week."""
    totals: dict[str, int] = {}
    for one in days:
        if one.day_date < since:
            continue
        for pattern, count in one.sets.items():
            totals[pattern] = totals.get(pattern, 0) + int(count)
    return totals


def recompute(
    days: Iterable[TrainingDayFact],
    complaints: Iterable[ComplaintFact],
    as_of: date,
) -> TrainingSnapshot:
    """
    Fold the days and the complaints into the state as of `as_of`.

    Deterministic in its arguments and free of `today`: the date is passed in,
    the same way `app.day.evaluate` is handed the rule instead of loading it.
    That is what makes a recompute of a past week reproducible, and what stops a
    test from depending on the day it runs on.
    """
    # Дни позже `as_of` в расчёт не входят. Запись на завтра — это план, а не
    # факт: она не делает завтрашний паттерн последним тяжёлым и не обрывает
    # серию пропусков, которая идёт по сегодня.
    ordered = sorted(
        (one for one in days if one.day_date <= as_of), key=lambda one: one.day_date
    )
    monday = week_start(as_of)
    outdoor = [one.day_date for one in ordered if one.outdoor_done]
    return TrainingSnapshot(
        as_of=as_of,
        week_starts_on=monday,
        last_heavy_pull=_latest(ordered, PATTERN_PULL, heavy=True),
        last_heavy_push=_latest(ordered, PATTERN_PUSH, heavy=True),
        last_legs=_latest(ordered, PATTERN_LEGS, heavy=False),
        last_run=_latest(ordered, PATTERN_RUN, heavy=False),
        last_outdoor=max(outdoor) if outdoor else None,
        last_cardio=_latest(ordered, PATTERN_CARDIO, heavy=False),
        near_failure_days=tuple(
            one.day_date
            for one in ordered
            if one.near_failure and one.day_date >= monday
        ),
        week_sets=_week_sets(ordered, monday),
        skipped_days=_trailing_skips(ordered),
        open_complaints=tuple(
            one.area
            for one in sorted(complaints, key=lambda c: (c.opened_on, c.area))
            if one.status == COMPLAINT_OPEN
        ),
    )
