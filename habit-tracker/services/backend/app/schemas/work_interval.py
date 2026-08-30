# [review:need-review] PHASE-03/91
# summary: wire types of work intervals — a start that has to carry its offset, an end that may be absent because the interval is running, `corrected` reachable only by editing, and a day block that carries the intervals with their sum but no window title, because the table has no such column
"""
Wire types of the time a day of work took.

**`corrected` нельзя объявить, в него можно только попасть.** `POST` accepts
`manual` and `agent` and nothing else: a corrected interval is an agent's
proposal that a person moved, and a writer able to claim the word directly
would make "исправлено человеком" a label anyone can print rather than a fact
the server witnessed.

**Момент едет со смещением, а не голым.** `AwareDatetime` refuses
`2026-08-24T09:30:00` without a `+02:00`, because reading it as UTC would move
the interval by two hours and — near the boundary hour — into another day. The
same refusal `local_date()` makes on a naive datetime, one layer earlier and
with a message a person sees.

**Ни одного поля под заголовок окна.** `extra="forbid"` means a client that
sends one is refused rather than silently ignored, and the model has nowhere to
put it if it were not.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.day.work import MODE_WORK, SOURCE_MANUAL

# What a client may declare. `corrected` is deliberately absent — see the module
# docstring.
DeclaredSource = Literal["manual", "agent"]
Mode = Literal["work", "off"]

END_BEFORE_START = (
    "интервал не может кончиться раньше, чем начался: ended_at должен быть "
    "строго позже started_at"
)


class WorkIntervalIn(BaseModel):
    """One interval as it is created."""

    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime = Field(
        ...,
        description=(
            "Начало интервала со смещением. День интервала считается по нему — "
            "интервал 23:00-01:00 принадлежит дню начала"
        ),
    )
    ended_at: AwareDatetime | None = Field(
        None, description="Конец интервала; null — интервал идёт прямо сейчас"
    )

    source: DeclaredSource = Field(
        SOURCE_MANUAL,
        description=(
            "manual — руками, agent — посчитал локальный агент. `corrected` "
            "объявить нельзя: в него переводит правка агентского интервала"
        ),
    )
    mode: Mode = Field(
        MODE_WORK,
        description="work — работа, off — записанная пауза; в сумму идёт work",
    )

    auto_started_at: AwareDatetime | None = None
    auto_ended_at: AwareDatetime | None = None

    app_bundle_id: str | None = Field(
        None,
        description=(
            "Идентификатор приложения вида com.apple.dt.Xcode. Заголовков окон "
            "здесь нет и не будет: под них нет колонки"
        ),
    )
    note: str | None = None

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> WorkIntervalIn:
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValueError(END_BEFORE_START)
        return self


class WorkIntervalPatch(BaseModel):
    """
    What an edit of an interval may change.

    Only the named fields move: `model_fields_set` is what tells «конец убрали,
    интервал снова идёт» (`ended_at: null` прислали) from «конца не касались»
    (поля нет в теле), which a plain default could not.
    """

    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = Field(
        None,
        description="Прислать null — снова открыть интервал; не прислать — не трогать",
    )
    mode: Mode | None = None
    app_bundle_id: str | None = None
    note: str | None = None


class WorkIntervalResponse(BaseModel):
    """
    One interval as the screen reads it.

    Carries `minutes` and `running` although neither is a column: the length of
    an open interval depends on the moment it is asked about, and a screen that
    computed it itself would disagree with the sum beside it.
    """

    id: UUID
    day_date: date

    started_at: datetime
    ended_at: datetime | None
    running: bool = Field(..., description="Интервал идёт прямо сейчас — конца нет")
    minutes: int = Field(
        ..., description="Длина интервала в минутах; для паузы (mode=off) — 0"
    )

    source: str = Field(..., description="manual | agent | corrected")
    mode: str

    auto_started_at: datetime | None = Field(
        None, description="Что предлагал агент до правки; null — никто не правил"
    )
    auto_ended_at: datetime | None = None

    app_bundle_id: str | None = None
    note: str | None = None
    edited_at: datetime | None = Field(
        None, description="Когда человек вмешался; null — не вмешивался"
    )


class WorkDayResponse(BaseModel):
    """
    The work of one day: its intervals and what they add up to.

    `work_minutes` is `null` when the day has no intervals at all — «не
    измерено», а не ноль. `evaluate_day` reads the same null and skips the
    overtime check instead of calling the day comfortably short.
    """

    day_date: date
    intervals: list[WorkIntervalResponse] = Field(default_factory=list)
    work_minutes: int | None = Field(
        None, description="Сумма минут работы за день; null — ни одного интервала"
    )
    running: bool = Field(False, description="Есть ли незакрытый интервал")
