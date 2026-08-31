# [review:need-review] PHASE-03/92
# summary: wire types of training — the state as a derived snapshot that says when it was recomputed, the day's plan/fact/minimum with the minimum carrying its own item id, the gated suggestion with the reason for every exclusion, complaints as symptoms and personal records with the target beyond them
"""
Wire types of training.

**Состояние отдаётся снимком и говорит, когда пересчитано.** `recomputed_at` не
украшение: строка производная, и читатель обязан видеть, насколько она свежа,
иначе снимок неотличим от источника — а именно этим `training/state.md` и был
плох.

**Минимум едет со своим `item_id`.** 29 августа минимум, объявленный внутри
блока тренировки и без собственной галки, не выполнен; 30-го он вынесен
отдельным пунктом. Отдельный пункт — это ссылка на строку плана, и она в
контракте, а не в вёрстке.

**Жалоба — симптом, а не диагноз.** Область, контекст, тяжесть словами человека;
диагнозов, назначений и анализов здесь нет и не будет (ADR-0014, «Не хранится»).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.training import COMPLAINT_STATUSES


class TrainingDayResponse(BaseModel):
    """What one date planned, did and set aside as its minimum."""

    model_config = ConfigDict(from_attributes=True)

    day_date: date
    patterns: list[str]
    heavy_patterns: list[str]
    planned_md: str | None
    done_md: str | None
    skipped: bool
    outdoor_done: bool | None
    near_failure: bool
    note_md: str | None
    minimum_md: str | None
    minimum_item_id: uuid.UUID | None = Field(
        default=None,
        description="Пункт плана, на котором минимум отмечается отдельной галкой",
    )
    sets: dict[str, int]


class TrainingDayIn(BaseModel):
    """
    A write of one date's training; every field is optional.

    Absent means «не трогай», not «сбрось». The morning writes the plan and the
    evening writes the fact, and a whole-row replace would let the second erase
    the first by omission.
    """

    patterns: list[str] | None = None
    heavy_patterns: list[str] | None = None
    planned_md: str | None = None
    done_md: str | None = None
    skipped: bool | None = None
    outdoor_done: bool | None = None
    near_failure: bool | None = None
    note_md: str | None = None
    minimum_md: str | None = None
    minimum_item_id: uuid.UUID | None = None
    sets: dict[str, int] | None = None


class BodyComplaintResponse(BaseModel):
    """One complaint — a symptom that gates a suggestion."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    opened_on: date
    area: str
    context: str | None
    severity: str | None
    status: str
    closed_on: date | None
    closed_reason: str | None


class BodyComplaintIn(BaseModel):
    """Opening a complaint: where it is, what it happened during, how bad."""

    opened_on: date | None = Field(
        default=None, description="По умолчанию — сегодня по границе суток"
    )
    area: str = Field(min_length=1, description="«левое плечо», «поясница»")
    context: str | None = None
    severity: str | None = None


class BodyComplaintPatch(BaseModel):
    """Closing a complaint: the canon asks for a day with load and no symptoms."""

    status: str = Field(description=f"Одно из {list(COMPLAINT_STATUSES)}")
    closed_on: date | None = None
    closed_reason: str | None = None


class PersonalRecordResponse(BaseModel):
    """One personal record, with the date it was reached and the target beyond."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exercise: str
    variant: str | None
    sets: str | None
    best_plain: int | None
    achieved_on: date
    target: str | None


class PersonalRecordIn(BaseModel):
    """A record as it is written down."""

    exercise: str = Field(min_length=1)
    variant: str | None = None
    sets: str | None = None
    best_plain: int | None = None
    achieved_on: date | None = Field(
        default=None, description="По умолчанию — сегодня по границе суток"
    )
    target: str | None = None


class ExcludedResponse(BaseModel):
    """One movement that will not be suggested today, and why."""

    exercise: str
    gate: str
    reason: str


class FiredGateResponse(BaseModel):
    """One gate that fired, in one sentence."""

    code: str
    reason: str


class SuggestionResponse(BaseModel):
    """
    What may be trained today — offer, exclusions, gates, intensity, volume.

    The exclusions travel with the offer rather than being subtracted silently:
    «сегодня без подтягиваний, плечо open с 10.08» is a sentence a person can
    disagree with, and a shorter list with no explanation is the one that gets
    ignored.
    """

    exercises: list[str]
    excluded: list[ExcludedResponse]
    gates: list[FiredGateResponse]
    rir: str
    volume_factor: float


class TrainingStateResponse(BaseModel):
    """The derived snapshot, its suggestion, the complaints and the records."""

    as_of: date
    last_heavy_pull: date | None
    last_heavy_push: date | None
    last_legs: date | None
    last_run: date | None
    last_outdoor: date | None
    last_cardio: date | None
    near_failure_days: list[date]
    week_sets: dict[str, int]
    progression_stage: dict[str, str]
    skipped_days: int
    recomputed_at: datetime
    open_complaints: list[BodyComplaintResponse]
    records: list[PersonalRecordResponse] = Field(
        default_factory=list,
        description="Личные рекорды с датой достижения и целью за ними",
    )
    suggestion: SuggestionResponse


class TrainingStateIn(BaseModel):
    """
    A write of the state — and only of the part a person authors.

    Everything else is recomputed from `training_day` and `body_complaint` the
    moment this lands, which is why the request cannot name `last_heavy_pull`:
    a state that could be typed in would be a second source of truth, and the
    first one to be wrong.
    """

    progression_stage: dict[str, str] = Field(
        default_factory=dict,
        description="«pull: объём 4x6-8 RIR 1-2» — решение на ближайшие недели",
    )
