# [review:need-review] PHASE-03/86
# summary: day DTOs — the day itself, the rule it is judged by (so the screen can explain the verdict before there is one), and an explicit "no plan" instead of a 404
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
    The whole answer for one date.

    `plan` is null and `has_plan` is false for every day right now: plan rows are
    `#87`'s subject. The pair is here rather than absent so that the screen has
    one shape to render from the start, and so that "нет плана" arrives as an
    answer with a day and a rule attached — a 404 would leave the reader unable
    to tell an empty day from a wrong URL.
    """

    day: DayResponse
    rule: DayRuleSetResponse
    plan: None = Field(None, description="План дня; появится в #87, сейчас всегда null")
    has_plan: bool = Field(
        False, description="Есть ли план на этот день. Пока всегда false"
    )
