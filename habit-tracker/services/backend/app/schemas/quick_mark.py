# [review:need-review] PHASE-03/121, PHASE-03/124, PHASE-03/125, PHASE-03/130
# summary: wire types of the quick mark — the button as it is created, patched and as it is read with the day's state on it, and the tap, whose body carries an id and an intent but never a category, a field or a display mode; the answer to an undo and the split of taps by source
"""
Wire types of the quick mark.

**The client sends an id, not a decision.** The body of a tap has no
`category_id`, no `field_id` and no `display_mode`: what the button means and
where the value lands is the server's answer, which is the whole point of
ADR-0018. The second client — the floating window of the macOS agent — then
needs to know nothing about the EAV underneath.

**The answer carries the new state.** `today_total` and `done` come back with
the created event so that a window can repaint without a second request. That is
one network call per tap, and it is what the acceptance case measures.

**`entry_date` is a guard, not a destination.** Which day a tap belongs to is
answered by `app.core.daytime.local_date()` and by nothing else. A client may
still send the date it believes it is marking; if the two disagree the write is
refused rather than silently moved, so a stale tab at 04:00 finds out instead of
writing into yesterday.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.quick_mark import (
    QUICK_MARK_KINDS,
    QUICK_MARK_SOURCES,
    SOURCE_WEB,
)

# The widest offset any IANA zone has ever had, in minutes; the same bound the
# health intake uses for the same field.
MAX_UTC_OFFSET_MINUTES = 18 * 60


class QuickMarkCreate(BaseModel):
    """
    A button as it is entered by hand.

    Shape only: that the field belongs to the category and that the kind fits
    the field's type are semantic questions, checked in `app.crud.quick_mark`
    against the rows themselves and answered as a list of reasons rather than as
    the first one found.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, max_length=60)
    category_id: int
    field_id: int
    kind: str = Field(..., description=f"Одно из: {', '.join(QUICK_MARK_KINDS)}")
    step: float | None = Field(
        None, description="Сколько стоит один тап; обязателен для increment/set_value"
    )
    unit_label: str | None = Field(
        None,
        max_length=20,
        description="Подпись единицы на кнопке; у поля единицы пока нет (#176)",
    )
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=7)
    hotkey: str | None = Field(
        None, min_length=1, max_length=1, description="Одна клавиша, без модификаторов"
    )
    order: int = 0
    show_in_agent: bool = True
    is_active: bool = True

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in QUICK_MARK_KINDS:
            raise ValueError(f"одно из {', '.join(QUICK_MARK_KINDS)}")
        return value


class QuickMarkResponse(BaseModel):
    """One button of the directory, without the state of any particular day."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    category_id: int
    field_id: int
    kind: str
    step: float | None = None
    unit_label: str | None = None
    icon: str | None = None
    color: str | None = None
    hotkey: str | None = None
    order: int
    show_in_agent: bool
    is_active: bool


class QuickMarkTodayResponse(QuickMarkResponse):
    """
    A button plus what the day it is read for already says.

    `today_total` is null for a tick — a box is not a quantity — and `done` is
    the one field both kinds answer: ticked, or the number has moved off zero.
    Together they are everything a screen needs to draw the button in its two
    states without fetching entries of its own.
    """

    entry_date: date
    today_total: float | None = None
    done: bool
    planned: bool = Field(
        False,
        description=(
            "Кнопку называет план на запрошенный день. Плановые стоят первыми "
            "и помечены на экране"
        ),
    )
    plan_item_id: UUID | None = Field(
        None,
        description=(
            "Пункт плана, который назвал кнопку. Его закрывает отметка, чтобы "
            "не отмечать дважды — на Today и в плане"
        ),
    )


class QuickMarkEventRequest(BaseModel):
    """One tap."""

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(
        None,
        description=(
            "Сколько записать вместо шага кнопки; для check — 0 снимает галку, "
            "любое другое ставит"
        ),
    )
    entry_date: date | None = Field(
        None,
        description=(
            "День, который клиент считает текущим. День отметки решает сервер "
            "(`local_date()`); несовпадение — 409, а не тихая запись в другой день"
        ),
    )
    utc_offset_minutes: int = Field(
        0,
        ge=-MAX_UTC_OFFSET_MINUTES,
        le=MAX_UTC_OFFSET_MINUTES,
        description="Смещение часов клиента в момент тапа; хранится, не решает день",
    )
    source: str = Field(
        SOURCE_WEB, description=f"Откуда тап: {', '.join(QUICK_MARK_SOURCES)}"
    )

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in QUICK_MARK_SOURCES:
            raise ValueError(f"одно из {', '.join(QUICK_MARK_SOURCES)}")
        return value


class QuickMarkEventResponse(BaseModel):
    """
    The recorded tap and the state it produced.

    A repeated `Idempotency-Key` answers with this same body and the same
    `event_id`: the caller cannot tell a replay from the original except by the
    status code, which is what makes a retried request safe.
    """

    event_id: int
    quick_mark_id: int
    entry_id: int | None
    entry_date: date
    occurred_at: datetime
    today_total: float | None = None
    done: bool


class QuickMarkUndoResponse(BaseModel):
    """
    A tap taken back, and what the day says once it is gone.

    The same two state fields a tap answers with (`today_total`, `done`), for
    the same reason: undo is one call, and the screen repaints from its answer
    rather than fetching the directory again.
    """

    event_id: int
    quick_mark_id: int
    entry_date: date
    undone_at: datetime
    today_total: float | None = None
    done: bool


class QuickMarkSourceUsage(BaseModel):
    """
    How many taps came from one client over the period asked about.

    `undone` counts separately rather than being subtracted: a client whose taps
    get taken back half the time is a finding about that client, and a single
    net number would hide it.
    """

    source: str
    events: int
    undone: int


# Кто спрашивает справочник. Веб показывает всё, окно агента — только то, что
# помечено `show_in_agent`, iOS пока читает как веб. Неизвестное значение —
# 422, а не молчаливый полный список: опечатка в клиенте иначе выглядит как
# рабочее поведение и находится через месяц.
SURFACE_WEB = "web"
SURFACE_AGENT = "agent"
SURFACE_IOS = "ios"
SURFACES: tuple[str, ...] = (SURFACE_WEB, SURFACE_AGENT, SURFACE_IOS)


class QuickMarkUpdate(BaseModel):
    """
    Правка кнопки: только присланные поля.

    Как и патч пункта плана (#110), различает «не прислали» и «обнулили»:
    `null` в `hotkey` снимает клавишу, отсутствие ключа её не трогает. Склеить
    их значило бы отбирать клавишу на каждом переименовании кнопки.
    """

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(None, min_length=1, max_length=60)
    category_id: int | None = None
    field_id: int | None = None
    kind: str | None = Field(
        None, description=f"Одно из: {', '.join(QUICK_MARK_KINDS)}"
    )
    step: float | None = None
    unit_label: str | None = Field(None, max_length=20)
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=7)
    hotkey: str | None = Field(None, min_length=1, max_length=1)
    order: int | None = None
    show_in_agent: bool | None = None
    is_active: bool | None = None


class QuickMarkOrderIn(BaseModel):
    """
    Новый порядок справочника: список id сверху вниз.

    Списком, а не парами «id и номер»: порядок — свойство списка, и клиент,
    присылающий номера, рано или поздно пришлёт два одинаковых. Сервер
    нумерует то, что получил, ровно как приём плана нумерует его секции (#87).
    """

    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(..., min_length=1)


class HotkeyTaken(BaseModel):
    """
    Тело 409: клавиша занята, и названа кнопка, которая её держит.

    Имя занявшей кнопки здесь намеренно. В остальном модуле сообщения строятся
    из id, чтобы в лог не попадало ничего, что человек напечатал; это сообщение
    в лог не идёт — оно отвечает на вопрос «а кто её занял», ради которого
    человек иначе полезет в базу.
    """

    error: str = Field("hotkey_taken", description="Машинный код отказа")
    message: str
    hotkey: str
    quick_mark_id: int = Field(..., description="Кнопка, которая держит клавишу")
    label: str = Field(..., description="Её подпись — по ней её и находят")
