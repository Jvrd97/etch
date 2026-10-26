# [review:need-review] PHASE-03/162
# summary: wire types of the day mode — a manual decision (kind + nocode + optional note, kind from the closed list) and the weekly schedule as exactly seven distinct weekdays
"""
Wire types of `PUT /day-mode/{date}` and `GET|PUT /mode-schedule`.

**`kind` и `nocode` приходят оба.** The two are orthogonal (вторник is `work` and
`nocode` at once), so a decision names both: a body that named only one would have
to guess the other from the schedule, and the guess is the thing a manual switch
exists to replace.

**Расписание — ровно семь дней.** A week with a hole would quietly turn that
weekday into «work, no nocode» (`activity_crud.day_mode` falls back to it), so the
shape that can lose a row is refused at the door.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.activity import DAY_MODE_KINDS, WEEKDAY_MAX, WEEKDAY_MIN
from app.schemas.activity import DayModeResponse

DAYS_IN_WEEK = WEEKDAY_MAX - WEEKDAY_MIN + 1
NOTE_MAX_LENGTH = 500


def _known_kind(value: str) -> str:
    if value not in DAY_MODE_KINDS:
        raise ValueError(
            f"«{value}» — не вид дня. Ожидается одно из: {', '.join(DAY_MODE_KINDS)}."
        )
    return value


class DayModeIn(BaseModel):
    """A person's decision about one date."""

    kind: str = Field(description=f"Одно из: {', '.join(DAY_MODE_KINDS)}")
    nocode: bool
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)

    _kind = field_validator("kind")(_known_kind)


class ModeScheduleDay(BaseModel):
    """What one weekday is by default. 0 = Sunday … 6 = Saturday."""

    weekday: int = Field(ge=WEEKDAY_MIN, le=WEEKDAY_MAX)
    kind: str = Field(description=f"Одно из: {', '.join(DAY_MODE_KINDS)}")
    nocode: bool

    _kind = field_validator("kind")(_known_kind)


class ModeScheduleWeek(BaseModel):
    """The whole week; the web edits and saves it as one."""

    days: list[ModeScheduleDay]

    @model_validator(mode="after")
    def _whole_week(self) -> ModeScheduleWeek:
        weekdays = sorted(day.weekday for day in self.days)
        if weekdays != list(range(WEEKDAY_MIN, WEEKDAY_MAX + 1)):
            raise ValueError(
                f"Расписание — ровно {DAYS_IN_WEEK} разных дней недели "
                f"({WEEKDAY_MIN}..{WEEKDAY_MAX}, 0 — воскресенье)."
            )
        return self


__all__ = ["DayModeIn", "DayModeResponse", "ModeScheduleDay", "ModeScheduleWeek"]
