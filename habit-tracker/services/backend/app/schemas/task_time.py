# [review:need-review] PHASE-03/166
# summary: wire types of `GET /day/{date}/task-time` — minutes per task of the day, tasks ticked done with no trace, untasked stretches of half an hour or more, and the thirty-day share of untasked intervals with the days actually observed
"""Wire types of the measured time read against the plan of one day."""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field


class TaskMinutes(BaseModel):
    """Minutes on one task: the union of the ranges that name it, never their sum."""

    plan_item_id: uuid.UUID
    title: str
    minutes: int


class TracelessTask(BaseModel):
    """A task ticked done with no interval naming it and no commit."""

    plan_item_id: uuid.UUID
    title: str


class LongUntaskedInterval(BaseModel):
    """Work outside the plan: an untasked stretch long enough to be a piece of work."""

    interval_id: int
    started_at: datetime
    ended_at: datetime
    minutes: int
    app_name: str


class UntaskedShareResponse(BaseModel):
    """
    The share of intervals that name no task, over the last `window_days` days.

    `observed_days` is how many of them the data covers. While it is below
    `window_days` the number is a short-window number and must be captioned as
    such. `share` is null when there are no intervals at all.
    """

    window_days: int
    observed_days: int
    intervals: int
    untasked: int
    share: float | None


class TaskTimeResponse(BaseModel):
    date: date_type
    tasks: list[TaskMinutes]
    today: date_type = Field(
        description="День сервера: только он ещё растёт, и только его экран перечитывает"
    )
    untasked_minutes: int = Field(
        description=(
            "Минуты без привязки любого вида, за вычетом минут, покрытых привязанными "
            "интервалами: таймер на задаче поверх замера агента оставляет их задаче. "
            "`tasks` + `untasked_minutes` + `other_linked_minutes` равно объединению "
            "всех интервалов дня, кроме минут, в которых идут две разные задачи сразу"
        )
    )
    other_linked_minutes: int = Field(
        description=(
            "Время интервалов, привязанных не к пункту плана, а по `plan_task_id` или "
            "`clickup_task_id` (так пишет редактор интервала), за вычетом минут, которые "
            "уже учтены в `tasks`. Не «без задачи» и не «задача дня»"
        )
    )
    long_untasked: list[LongUntaskedInterval]
    done_without_traces: list[TracelessTask]
    commits_checked: bool = Field(
        description=(
            "Передан ли список задач с коммитами. false — коммиты не смотрели, и "
            "«следов нет» значит «нет интервалов», а не «нет и коммитов»"
        )
    )
    untasked_share: UntaskedShareResponse


__all__ = [
    "LongUntaskedInterval",
    "TaskMinutes",
    "TaskTimeResponse",
    "TracelessTask",
    "UntaskedShareResponse",
]
