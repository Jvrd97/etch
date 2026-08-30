# [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/92, PHASE-03/142
# summary: day DTOs — the day itself, the rule it is judged by, the map of the day the rule draws (edges, free evening, ceilings, anchors, the order of the verdict), the plan when there is one instead of a 404 when there is not, the marks, task counts and notebook that come with it, the anchors and the training of the day (#92), and the итог with the verdict of the day
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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.anchor import DayAnchorsResponse
from app.schemas.mark import MarkResponse, TaskCountsResponse
from app.schemas.plan import PlanResponse
from app.schemas.summary import DaySummaryResponse
from app.schemas.training import TrainingDayResponse


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
    overtime_lost_min: int = Field(
        ...,
        description="Потолок, выше которого день не планируется никогда, в минутах",
    )
    work_stop_at: time
    max_work_tasks: int
    max_study_items: int
    tasks_required_ratio: Decimal
    overtime_disqualifies: bool

    wake_at: time
    work_start: time
    review_at: time
    bedtime_max: time
    free_evening_start: time
    free_evening_end: time
    relationship_anchor_required: bool = Field(
        ...,
        description="Нужен ли вечер с близкими; снимается новой строкой правила",
    )
    relationship_evening_start: time
    relationship_evening_end: time

    workdays: list[int] = Field(
        ..., description="Номера дней недели по ISO, 1 — понедельник"
    )
    days_off: list[int] = Field(
        ..., description="Выходные — не то же самое, что «не рабочий день»"
    )
    nocode_days: list[int]
    required_anchors: list[str]
    hard_edge_kinds: list[str] = Field(
        ..., description="Виды пунктов, которым канон разрешает жёсткость"
    )
    anchors: list[str] = Field(
        ..., description="Состав якорей, обязательных для выигранного дня"
    )
    verdict_rule: dict[str, Any] = Field(
        ...,
        description="Формула вердикта: какие условия снимают день и в каком порядке",
    )
    note_md: str


class DayEdgeResponse(BaseModel):
    """
    One hard edge of the day: its code, its Russian label and its hour.

    `at` is null for an edge the canon places but does not clock — спорт stands
    before the start of work, and no row says at which minute. Null is the
    honest answer; an invented 06:15 would be a number nobody decided.
    """

    kind: str
    label: str
    at: time | None = None


class IntervalResponse(BaseModel):
    """A stretch of the evening, named by its two wall-clock ends."""

    start: time
    end: time


class DayMapResponse(BaseModel):
    """
    The map of the day: where the hard points stand, which evening stays free.

    Sent beside the plan so the two can be compared by eye. Every number here is
    a column of `day_rule_set`, which is the whole point: «подъём 6:00, спорт,
    старт работы, ревью 15:40, отбой 22:30» lived only in `config.md` until
    `#142`, and a plan could not be checked against a paragraph.
    """

    rule_set_id: int
    edges: list[DayEdgeResponse]
    free_evening: IntervalResponse = Field(
        ..., description="Интервал вечера, который планом не расписывается"
    )
    relationship_evening: IntervalResponse
    relationship_anchor_required: bool
    work_cap_min: int
    work_hard_cap_min: int
    overtime_lost_min: int
    work_stop_at: time
    max_work_tasks: int
    max_study_items: int
    anchors: list[str]
    hard_edge_kinds: list[str]
    workdays: list[int]
    days_off: list[int]
    nocode_days: list[int]
    verdict_reasons: list[str] = Field(
        ...,
        description=(
            "Условия, снимающие день, в порядке проверки — машинные коды, "
            "как их читает `verdict_reason`"
        ),
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
    day_map: DayMapResponse = Field(
        ...,
        description=(
            "Карта дня из той же строки правила: жёсткие точки, свободный "
            "вечер, потолки и состав якорей — числами, а не вёрсткой"
        ),
    )
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
    anchors: DayAnchorsResponse = Field(
        ...,
        description=(
            "Якоря дня по справочнику: по пункту на каждый вид, которым судится "
            "этот день, — включая те, по которым ещё ничего не сказано"
        ),
    )
    training: TrainingDayResponse | None = Field(
        None,
        description=(
            "Тренировка дня: запланированное, сделанное и минимум со своим "
            "пунктом плана; null — на эту дату ничего не записано"
        ),
    )
    summary: DaySummaryResponse = Field(
        ...,
        description=(
            "Итог дня: вердикт, невыполненное условие, счётчики, стрик и проза. "
            "День не закрыт — `closed: false`, `verdict: null` и живой пересчёт, "
            "а не «проиграл»"
        ),
    )
