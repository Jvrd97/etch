# [review:need-review] PHASE-03/94
# summary: wire types of the week — the snapshot with `computed_at` beside its counters, the sunday checklist as items, and the write that replaces the prose without ever being allowed to set the numbers
"""
Wire types of the week and of a range of days.

**Счётчики нельзя прислать.** `WeekIn` carries prose and checklist items and
nothing else: `won_days`, `total_days` and `streak_end` are read off
`day_summary` by the server, and a client able to send them would be a second
opinion about how many days of the week were won.

**`computed_at` едет наружу.** It is the field that makes the snapshot readable:
«0 из 7» written in August stays «0 из 7» in November, and the reader can see
that the numbers were last taken in August rather than wonder whether the prose
went stale.

**Форма `DayListItem` — прежняя форма `/api/days`.** `date`, `title`, `verdict`,
`done`, `total`, in those names. The old timeline and the old sidebar parsed
prose out of files to build exactly this; keeping the shape is what lets them be
pointed at the API instead of rewritten.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.day.evaluate import VERDICTS


class DayListItem(BaseModel):
    """
    One day of a range, in the shape the timeline and the sidebar already read.

    `verdict` carries three states, not two: `won`, `lost` and `null` — «день не
    закрыт». `life.py` painted by a regular expression over prose and could only
    tell the first two apart, so a day nobody closed looked exactly like a day
    that was lost.
    """

    date: date
    title: str = Field(
        "",
        description=(
            "Заголовок плана дня; пусто — плана нет или он без заголовка. "
            "Прежний `/api/days` доставал его регуляркой из первой строки файла"
        ),
    )
    verdict: str | None = Field(
        None,
        description=(
            f"Одно из: {', '.join(VERDICTS)}; null — день не закрыт. "
            "Три состояния квадрата различаются по этому полю"
        ),
    )
    done: int = Field(0, description="Закрытых рабочих задач дня")
    total: int = Field(0, description="Рабочих задач в плане дня")


class WeekReviewItemIn(BaseModel):
    """One line of the sunday checklist, as it is sent."""

    model_config = ConfigDict(extra="forbid")

    text_md: str
    done: bool = False


class WeekReviewItemResponse(BaseModel):
    """One line of the sunday checklist, as it is read."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ord: int
    text_md: str
    done: bool


class WeekIn(BaseModel):
    """
    What a person writes about a week: the prose and the checklist.

    Deliberately without the counters. Ретро утверждает то, что было верно на
    момент письма; how many days were won is read from the days themselves, and
    a client that could send `won_days` would let the two disagree without
    anything saying which is right.
    """

    model_config = ConfigDict(extra="forbid")

    retro_md: str = ""
    blockers_md: str = Field("", description="«Что мешало» — блокеры недели")
    mgmt_retro_md: str = Field("", description="Mgmt-ретро: средний горизонт")
    weekly_number_md: str = Field(
        "", description="Пятничный якорь: недельный отчёт и цифра уравнения"
    )
    review_items: list[WeekReviewItemIn] = Field(
        default_factory=list, description="«На разбор в воскресенье», по порядку"
    )


class WeekResponse(BaseModel):
    """The week as the screen reads it: the snapshot, its date and its prose."""

    iso_code: str
    starts_on: date
    ends_on: date

    won_days: int
    total_days: int = Field(
        ..., description="Сколько дней недели заведено — знаменатель «0 из 7»"
    )
    streak_end: int | None = Field(
        None,
        description=(
            "Стрик после последнего закрытого дня недели; null — ни один день "
            "недели не закрыт, что не то же самое, что стрик 0"
        ),
    )

    retro_md: str = ""
    blockers_md: str = ""
    mgmt_retro_md: str = ""
    weekly_number_md: str = ""
    review_items: list[WeekReviewItemResponse] = Field(default_factory=list)

    computed_at: datetime = Field(
        ..., description="Когда счётчики выше были сняты в последний раз"
    )
