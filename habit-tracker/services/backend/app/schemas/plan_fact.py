# [review:need-review] PHASE-03/200
# summary: wire types of a fact typed into a plan line — the write (values by field id, typed: a number, seconds, or a box; an optional unit that has to match the field; an optional date and mark), and the read: the link with its state, the entries the line wrote, their total on the linked field and how that compares with the target
"""
Wire types of the facts a plan line writes into a category (ADR-0023).

**A value is typed by what it is, not by a string.** `300` is a number, `true`
is a box, a duration is whole seconds. The EAV column underneath is text, but a
client that sends `"300"` into a box or `1` into a checkbox is told so with a
422, rather than having the server guess which of the two it meant.

**A unit is a check, not a conversion.** The client may send the unit it showed
the person; if that is not the field's unit, the write is refused. 3000 typed
next to «м» into a field kept in «км» is a different fact from 3000 km, and the
server does not convert between units it does not own.

**The answer is the line's whole state.** Every write answers with all facts of
the line, their total and the progress against the target, so the card redraws
from one response — on the phone as on the desktop.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.day.plan_links import LinkState
from app.models.mark import MARK_SOURCES, MARK_STATES, SOURCE_WEB
from app.schemas.mark import MarkResponse

# How a line's facts stand against its target. `none` — nothing recorded yet;
# `partial` — recorded, below the target; `met` — the target reached, or the
# box ticked; `recorded` — recorded, and there is no target to compare with.
Progress = Literal["none", "partial", "met", "recorded"]


class PlanFactValueIn(BaseModel):
    """One field of the fact."""

    model_config = ConfigDict(extra="forbid")

    field_id: int
    value: StrictBool | float = Field(
        ...,
        description=(
            "Число — для числового поля, целые секунды — для длительности, "
            "true/false — для галочки"
        ),
    )
    unit: str | None = Field(
        None,
        description=(
            "Единица, которую видел человек. Должна совпасть с единицей поля; "
            "у длительности — `s`"
        ),
    )


class PlanFactIn(BaseModel):
    """
    The fact as the plan card sends it.

    `mark` is applied in the same transaction as the fact, so "сделано" never
    stands without the entry it claims; `null` leaves the mark as it is. A
    partial fact is sent without a mark — the card decides that, not the server,
    because only the person knows whether 100 of 300 is "сделано на сегодня".
    """

    model_config = ConfigDict(extra="forbid")

    values: list[PlanFactValueIn] = Field(..., min_length=1)
    entry_date: date | None = Field(
        None,
        description="День записи. По умолчанию — день плана, а не сегодня",
    )
    mark: str | None = Field(
        None, description=f"Отметка пункта вместе с фактом: {', '.join(MARK_STATES)}"
    )
    source: str = Field(SOURCE_WEB, description=f"Одно из: {', '.join(MARK_SOURCES)}")

    @field_validator("mark")
    @classmethod
    def _known_mark(cls, value: str | None) -> str | None:
        if value is not None and value not in MARK_STATES:
            raise ValueError(f"mark must be one of: {', '.join(MARK_STATES)}")
        return value

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in MARK_SOURCES:
            raise ValueError(f"source must be one of: {', '.join(MARK_SOURCES)}")
        return value


class PlanLinkFieldResponse(BaseModel):
    """A field of the linked category the card can offer an input for."""

    id: int
    name: str
    field_type: str
    unit: str | None


class PlanLinkResponse(BaseModel):
    """What a line is linked to, and whether a fact can be written into it."""

    category_id: int
    category_name: str
    category_active: bool
    field_id: int | None = Field(
        ..., description="Поле, в которое пишется факт; `null` — поле удалено"
    )
    field_name: str | None
    field_type: str | None
    unit: str | None
    target_value: float | None
    state: LinkState = Field(
        ..., description="`ok` — факт записывается; иное — почему нет"
    )
    fields: list[PlanLinkFieldResponse] = Field(
        default_factory=list,
        description="Поля категории, которые можно заполнить из плана",
    )


class PlanFactValueResponse(BaseModel):
    """One stored value of a fact, as text — the way the entry stores it."""

    field_id: int
    value: str | None


class PlanFactEntryResponse(BaseModel):
    """One entry the line wrote, read from the category history as it is now."""

    entry_id: int
    entry_date: date
    values: list[PlanFactValueResponse]
    created_at: datetime
    updated_at: datetime


class PlanItemFactsResponse(BaseModel):
    """
    A linked line: the link, the entries it wrote and how they add up.

    `total` sums the linked field across the line's entries and is null for a
    box. Entries of the same category the line did not write — typed by hand,
    imported — are not counted: the plan shows what the plan recorded.
    """

    item_id: UUID
    link: PlanLinkResponse
    entries: list[PlanFactEntryResponse]
    total: float | None
    done: bool = Field(
        ..., description="Что-то из записанного значит «было»: число выше нуля, галочка"
    )
    progress: Progress


class PlanFactWriteResponse(BaseModel):
    """The answer to a write: the entry it touched, the line, the mark."""

    entry_id: int = Field(..., description="Запись, которую тронула эта операция")
    facts: PlanItemFactsResponse | None = Field(
        ..., description="Факты пункта после записи; `null` — пункт уже не связан"
    )
    mark: MarkResponse
