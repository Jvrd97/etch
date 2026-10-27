# [review:need-review] PHASE-03/223
# summary: wire types of the supplement directory and the intake mark — create/patch bodies with trimmed names and a positive dose, list items with taken_today, the intake request (optional client day for the clock check) and response
"""
Wire types of supplements (`#223`).

**День отметки — не поле запроса.** Клиент может прислать `intake_date`, но это
сверка часов, а не адрес записи: расхождение с днём сервера — 409 (так же, как у
быстрых отметок). Тихая запись во вчера из-за уехавших часов телефона портила
бы соблюдение.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.supplement import NAME_MAX_LENGTH, UNIT_MAX_LENGTH

# Верхняя граница дозы: ловит опечатку «20000000», а не клинический предел.
MAX_DOSE = 1_000_000

Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH),
]
Unit = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=UNIT_MAX_LENGTH),
]
Dose = Annotated[float, Field(gt=0, le=MAX_DOSE)]


class SupplementCreate(BaseModel):
    name: Name
    dose: Dose
    unit: Unit
    intake_time: time | None = Field(
        None, description="Планируемое время приёма; null — в любое время дня"
    )


class SupplementUpdate(BaseModel):
    """Только присланные поля; `intake_time: null` снимает время."""

    name: Name | None = None
    dose: Dose | None = None
    unit: Unit | None = None
    intake_time: time | None = None

    @model_validator(mode="after")
    def _required_fields_are_not_nulled(self) -> SupplementUpdate:
        for field in ("name", "dose", "unit"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} не может быть null")
        return self


class SupplementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    dose: float
    unit: str
    intake_time: time | None
    is_active: bool
    created_at: datetime
    archived_at: datetime | None


class SupplementListItem(SupplementResponse):
    taken_today: bool = Field(
        ..., description="Есть отметка «принял» за текущие логические сутки сервера"
    )


class IntakeRequest(BaseModel):
    intake_date: date | None = Field(
        None,
        description=(
            "День по часам клиента. Не адрес записи: не совпал с днём сервера — 409"
        ),
    )


class IntakeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplement_id: int
    intake_date: date
    taken_at: datetime
