# [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90
# summary: day DTOs — the day itself, the rule it is judged by, the plan when there is one instead of a 404 when there is not, the marks, task counts and notebook that come with it, and the итог with the verdict of the day
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

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.mark import MarkResponse, TaskCountsResponse
from app.schemas.plan import PlanResponse
from app.schemas.summary import DaySummaryResponse


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
