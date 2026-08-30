# [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/91, PHASE-03/152
# summary: day DTOs — the day itself, the rule it is judged by, the plan when there is one instead of a 404 when there is not, the marks, task counts and notebook that come with it, the итог with the verdict of the day, and the intervals of work with their sum — and no window title, because the table has no column for one; since #152 also the draft of a new version of the canon (`DayRuleSetPublish`) and the history the rules screen reads
"""
Wire types of the day.

The response carries the rule, not just the day. A screen that shows only the
date and the kind can say what the day *is* but not why it will be judged the
way it will, and the whole reason the canon is a row is that the answer changes
over time: the day of the 14th is read against different numbers than the day of
the 30th, and the reader has to be able to see which.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.mark import MarkResponse, TaskCountsResponse
from app.schemas.plan import PlanResponse
from app.schemas.summary import DaySummaryResponse
from app.schemas.work_interval import WorkDayResponse


class DayRuleSetResponse(BaseModel):
    """The canon in force on a date, as the screen reads it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    valid_from: date
    valid_to: date | None = Field(
        None,
        description="Первая дата, на которую правило уже не действует; null — действует до сих пор",
    )

    timezone: str
    day_start_hour: int = Field(
        ..., description="Час местных суток, с которого начинается день"
    )

    work_cap_min: int
    work_hard_cap_min: int
    work_stop_at: time
    max_work_tasks: int
    tasks_required_ratio: Decimal
    overtime_disqualifies: bool

    workdays: list[int] = Field(
        ..., description="Номера дней недели по ISO, 1 — понедельник"
    )
    nocode_days: list[int]
    required_anchors: list[str]
    note_md: str


# Bounds of the fields a published version may carry. Named rather than typed
# into the `Field(...)` calls twice: the same numbers are the ones the screen
# puts on its inputs, and a bound that exists only inside a decorator is a bound
# nobody can read off the contract.
MIN_DAY_START_HOUR = 0
MAX_DAY_START_HOUR = 23
MINUTES_PER_DAY = 24 * 60
MIN_WORK_TASKS = 1
MAX_WORK_TASKS = 20
ISO_MONDAY = 1
ISO_SUNDAY = 7
# Bounds of the task bar. Whole numbers rather than `Decimal` because pydantic's
# `Field(ge=…, le=…)` takes floats; the value itself stays a `Decimal`, which is
# what the `Numeric(3, 2)` column holds.
MIN_TASKS_RATIO = 0
MAX_TASKS_RATIO = 1
# Lowest ceiling a version may set. Zero minutes of work is not a canon, it is
# a mistyped field.
MIN_WORK_CAP_MIN = 1


class DayRuleSetPublish(BaseModel):
    """
    A new version of the canon, in force from `valid_from` onwards.

    Every field is required except the note: the screen sends the version it is
    replacing with the numbers the person changed, so an omitted field is a
    typo in a client rather than "keep whatever was there". `extra="forbid"`
    for the same reason — a request carrying `valid_to` or `id` would be a
    caller expecting to edit a row, and silently dropping those fields would
    let it believe it had.

    There is no `valid_to`: a published version is in force until the next one
    closes it. Handing the end of the interval to the client would let it write
    a hole into the canon, and a date with no rule has no verdict.
    """

    model_config = ConfigDict(extra="forbid")

    valid_from: date = Field(
        ...,
        description=(
            "Первый день, который живёт по новой версии. Не раньше завтрашнего: "
            "по сегодняшнему и прошедшим дням вердикты уже считаются"
        ),
    )

    timezone: str = Field(..., description="Зона IANA, например Europe/Berlin")
    day_start_hour: int = Field(
        ...,
        ge=MIN_DAY_START_HOUR,
        le=MAX_DAY_START_HOUR,
        description="Час местных суток, с которого начинается день",
    )

    work_cap_min: int = Field(..., ge=MIN_WORK_CAP_MIN, le=MINUTES_PER_DAY)
    work_hard_cap_min: int = Field(..., ge=MIN_WORK_CAP_MIN, le=MINUTES_PER_DAY)
    work_stop_at: time

    max_work_tasks: int = Field(..., ge=MIN_WORK_TASKS, le=MAX_WORK_TASKS)
    tasks_required_ratio: Decimal = Field(
        ..., ge=MIN_TASKS_RATIO, le=MAX_TASKS_RATIO, decimal_places=2
    )
    overtime_disqualifies: bool

    workdays: list[int] = Field(
        ..., description="Номера дней недели по ISO, 1 — понедельник"
    )
    nocode_days: list[int]
    required_anchors: list[str]
    note_md: str = Field("", description="Зачем правило поменяли — читает человек")

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        """
        Refuse a zone the machine cannot resolve.

        The zone of the rule is what `app.core.daytime` answers "какое сегодня
        число" by. A typo in it does not fail here and then: it fails on the
        next request that asks about a day, everywhere at once.
        """
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(
                f"«{value}» не зона IANA. Ожидается что-то вроде Europe/Berlin: "
                "по этой зоне считается, какому дню принадлежит момент."
            ) from error
        return value

    @field_validator("workdays", "nocode_days")
    @classmethod
    def _iso_weekdays(cls, value: list[int]) -> list[int]:
        """ISO numbers, each at most once — the list is a set with an order."""
        for number in value:
            if not ISO_MONDAY <= number <= ISO_SUNDAY:
                raise ValueError(
                    f"{number} — не номер дня недели по ISO: ожидается "
                    f"{ISO_MONDAY} (понедельник) … {ISO_SUNDAY} (воскресенье)."
                )
        if len(set(value)) != len(value):
            raise ValueError("День недели назван дважды.")
        return value

    @field_validator("required_anchors")
    @classmethod
    def _named_anchors(cls, value: list[str]) -> list[str]:
        """Anchors are named once each, and an empty name names nothing."""
        cleaned = [anchor.strip() for anchor in value]
        if any(anchor == "" for anchor in cleaned):
            raise ValueError("Пустой якорь: у обязательного пункта дня есть имя.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Якорь назван дважды.")
        return cleaned

    @model_validator(mode="after")
    def _hard_cap_is_the_higher_one(self) -> DayRuleSetPublish:
        """
        The exception ceiling cannot sit below the everyday one.

        Two ceilings mean "восемь часов норма, девять — исключение". Swapped,
        they describe a day where the exception is stricter than the rule, and
        the verdict then depends on which of the two `evaluate_day` happens to
        read first.
        """
        if self.work_hard_cap_min < self.work_cap_min:
            raise ValueError(
                f"Потолок-исключение ({self.work_hard_cap_min} мин) ниже "
                f"обычного ({self.work_cap_min} мин): исключение не бывает "
                "строже правила."
            )
        return self


class DayRuleSetHistoryResponse(BaseModel):
    """
    Every version of the canon, plus what the screen needs to publish the next.

    `today` and `earliest_valid_from` come from the server rather than from the
    browser's calendar: the day turns at the rule's own boundary hour, so at
    00:30 the browser's «завтра» is the server's «сегодня» — and «сегодня» is
    exactly the date publishing is not allowed to start on.
    """

    today: date = Field(
        ..., description="Сегодня по границе суток действующего правила"
    )
    earliest_valid_from: date = Field(
        ..., description="Самая ранняя дата, с которой можно выпустить новую версию"
    )
    current_id: int | None = Field(
        None, description="id действующей версии; null — таблица правил пуста"
    )
    rules: list[DayRuleSetResponse] = Field(
        default_factory=list, description="Все версии, старая первой"
    )


class DayResponse(BaseModel):
    """
    One day: what it is, and by which rule it will be judged.

    Built by hand from the model rather than by `from_attributes`: the column is
    `date` but the mapped attribute is `day_date` (a class body cannot own an
    attribute named `date` and resolve `datetime.date` annotations at the same
    time), and an alias to paper over that would hide the reason.
    """

    date: date
    kind: str = Field(..., description="work | off — зафиксировано при создании дня")
    is_nocode: bool
    opened_at: datetime | None = Field(
        None, description="Когда день открыли впервые; null — не открывали ни разу"
    )
    last_touched_at: datetime | None = None


class DayDetailResponse(BaseModel):
    """
    The whole answer for one date: the day, its canon, and its plan.

    A day without a plan answers with `plan: null` and `has_plan: false` rather
    than 404ing. "Нет плана" is a fact about the day and arrives with the date
    and the rule attached; a 404 would leave the reader unable to tell an empty
    day from a mistyped URL.

    `has_plan` is redundant with `plan is not null` on purpose: it is the field a
    screen branches on, and one boolean is harder to get wrong in JSX than a
    null check on a nested object.
    """

    day: DayResponse
    rule: DayRuleSetResponse
    plan: PlanResponse | None = Field(
        None, description="План дня с расписанием и наложениями; null — плана нет"
    )
    has_plan: bool = Field(False, description="Есть ли план на этот день")
    marks: list[MarkResponse] = Field(
        default_factory=list,
        description=(
            "Отметки пунктов. Пункта здесь нет — отметки нет, «не дошёл»; "
            "не открывали ли день вообще, говорит `day.opened_at`"
        ),
    )
    task_counts: TaskCountsResponse = Field(
        default_factory=lambda: TaskCountsResponse(
            planned=0, done=0, failed=0, skipped=0, pending=0
        ),
        description="Рабочие задачи дня по состояниям — счётчик в шапке",
    )
    notebook: str | None = Field(
        None, description="Блокнот дня из journal_entries; null — не писали"
    )
    summary: DaySummaryResponse = Field(
        ...,
        description=(
            "Итог дня: вердикт, невыполненное условие, счётчики, стрик и проза. "
            "День не закрыт — `closed: false`, `verdict: null` и живой пересчёт, "
            "а не «проиграл»"
        ),
    )
    work: WorkDayResponse = Field(
        ...,
        description=(
            "Интервалы работы дня и их сумма. `work_minutes: null` — ни одного "
            "интервала, то есть «не измерено», а не ноль. Заголовков окон здесь "
            "нет: `work_interval` их не хранит"
        ),
    )
