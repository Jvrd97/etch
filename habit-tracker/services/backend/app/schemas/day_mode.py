# [review:need-review] PHASE-03/228
# summary: wire types of the day mode — a manual decision (kind as a closed Literal, nocode a strict boolean, optional note) and the weekly schedule as exactly seven distinct weekdays; the calendar the path date must stay in
"""
Wire types of `PUT /day-mode/{date}` and `GET|PUT /mode-schedule`.

**`kind` и `nocode` приходят оба.** The two are orthogonal (вторник is `work` and
`nocode` at once), so a decision names both: a body that named only one would have
to guess the other from the schedule, and the guess is the thing a manual switch
exists to replace.

**Расписание — ровно семь дней.** A week with a hole would quietly turn that
weekday into «work, no nocode» (`activity_crud.day_mode` falls back to it), so the
shape that can lose a row is refused at the door.

**`nocode` — настоящий boolean.** Pydantic in lax mode reads `"yes"`, `"true"` and
`1` as `True`; a flag that gates the work of a whole day does not take a guess.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, model_validator

from app.models.activity import WEEKDAY_MAX, WEEKDAY_MIN
from app.schemas.activity import DayModeResponse

DAYS_IN_WEEK = WEEKDAY_MAX - WEEKDAY_MIN + 1
NOTE_MAX_LENGTH = 500

# Same four words as `app.models.activity.DAY_MODE_KINDS`; a test holds them together.
DayModeKind = Literal["work", "dayoff", "vacation", "sick"]

# A typo in the year must not mint a row for a date nobody will live to see.
DAY_MODE_MIN_DATE = date(2000, 1, 1)
DAY_MODE_MAX_DATE = date(2100, 12, 31)


class DayModeIn(BaseModel):
    """A person's decision about one date."""

    kind: DayModeKind
    nocode: StrictBool
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)


class ModeScheduleDay(BaseModel):
    """What one weekday is by default. 0 = Sunday … 6 = Saturday."""

    weekday: int = Field(ge=WEEKDAY_MIN, le=WEEKDAY_MAX)
    kind: DayModeKind
    nocode: StrictBool


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


__all__ = [
    "DayModeIn",
    "DayModeKind",
    "DayModeResponse",
    "ModeScheduleDay",
    "ModeScheduleWeek",
]
