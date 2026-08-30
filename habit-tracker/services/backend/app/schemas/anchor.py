# [review:need-review] PHASE-03/92
# summary: wire types of the anchors — one entry per kind the canon of that day names, carrying the title a person reads, whether the day closed it and the line of the plan it is written on; a write names the kind and the state, never a position in a list
"""
Wire types of the anchors of a day.

**Отвечает справочник, а не строки.** Ответ содержит по одному пункту на каждый
вид якоря, которым судится этот день, — включая те, по которым ещё ничего не
сказано. Иначе «вечера с близкими сегодня не было» было бы неотличимо от «про
вечер с близкими сегодня не спрашивали», а на этом различии стоит весь смысл
третьего приоритета.

**Пишется вид, а не позиция.** Тело запроса называет `kind`; порядковый номер в
списке — свойство отображения, и запрос, который на него опирается, ломается от
`INSERT`-а в справочник.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.anchor import ANCHOR_STATES


class AnchorKindResponse(BaseModel):
    """One row of the catalogue."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    ord: int
    counts_for_verdict: bool
    required_in_nonwork_evening: bool = Field(
        description="Ждёт ли канон этот якорь в нерабочий вечер — у `relationship` да"
    )


class DayAnchorResponse(BaseModel):
    """One anchor of one day: what it is, whether it closed, where it is written."""

    kind: str
    title: str
    ord: int
    counts_for_verdict: bool
    required_in_nonwork_evening: bool
    state: str | None = Field(
        default=None,
        description="`done`, `failed`, `skipped` или null — «ещё ничего не сказано»",
    )
    note: str | None = None
    item_id: uuid.UUID | None = Field(
        default=None, description="Пункт плана, на котором записан этот якорь"
    )
    # Whether this day is judged by this anchor at all: the canon of a day in
    # July names five kinds, the catalogue holds six.
    required_today: bool = True


class DayAnchorsResponse(BaseModel):
    """Every anchor of one day, in the order of the catalogue."""

    day_date: str
    anchors: list[DayAnchorResponse]
    done: int
    total: int
    missing: list[str] = Field(
        description="Названия якорей, которые день не закрыл и не отложил"
    )


class AnchorMarkIn(BaseModel):
    """One anchor of one day, as a write names it."""

    kind: str
    state: str | None = Field(
        default=None,
        description=f"Одно из {list(ANCHOR_STATES)} или null — снять отметку",
    )
    note: str | None = None


class DayAnchorsIn(BaseModel):
    """
    A write of the anchors of a day: one entry, or several at once.

    Several, because the evening closes three anchors in one gesture and three
    requests would leave the screen showing two of them for a moment. Each entry
    is independent — nothing here is a whole-day replace, and an anchor not
    named keeps whatever it had.
    """

    anchors: list[AnchorMarkIn] = Field(min_length=1)
