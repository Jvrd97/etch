# [review:need-review] PHASE-03/92
# summary: the training tables — `training_day` (one row per date, the frontmatter keys `planned_<date>`/`done_<date>`/`skipped_<date>` unrolled into columns), `training_state` as a single derived snapshot with `recomputed_at`, `body_complaint` (a symptom for a gate, never a diagnosis) and `personal_record`
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

__all__ = [
    "COMPLAINT_OPEN",
    "COMPLAINT_STATUSES",
    "PATTERNS",
    "PATTERN_CARDIO",
    "PATTERN_CORE",
    "PATTERN_LEGS",
    "PATTERN_PULL",
    "PATTERN_PUSH",
    "PATTERN_RUN",
    "TRAINING_STATE_ID",
    "BodyComplaint",
    "PersonalRecord",
    "TrainingDay",
    "TrainingState",
]

# The movement patterns the canon rotates. Strings rather than an enum, and
# stored in arrays, because `week_sets` in `training/state.md` has always been a
# map keyed by exactly these words and a seventh pattern must not need a
# migration.
PATTERN_PULL = "pull"
PATTERN_PUSH = "push"
PATTERN_LEGS = "legs"
PATTERN_CORE = "core"
PATTERN_RUN = "run"
PATTERN_CARDIO = "cardio"
PATTERNS: tuple[str, ...] = (
    PATTERN_PULL,
    PATTERN_PUSH,
    PATTERN_LEGS,
    PATTERN_CORE,
    PATTERN_RUN,
    PATTERN_CARDIO,
)

# The single row `training_state` is allowed to have. One person, one body, one
# state — and a second row would be a second answer to «когда была последняя
# тяжёлая тяга», which is the question the whole table exists to answer.
TRAINING_STATE_ID = 1

COMPLAINT_OPEN = "open"
COMPLAINT_CLOSED = "closed"
COMPLAINT_STATUSES: tuple[str, ...] = (COMPLAINT_OPEN, COMPLAINT_CLOSED)


class TrainingDay(Base):
    """
    What was planned and what was done on one date.

    This table is the unrolling of `training/state.md`, where the same facts
    lived as dynamic frontmatter keys — `planned_2026-08-30`, `done_2026-08-30`,
    `skipped_2026-08-14`. A table folded into YAML keys cannot be queried,
    cannot be counted and is corrupted by one mistyped date; that is not a
    stylistic complaint, it is why «pull не подтверждён с 17.08» had to be
    counted by a human reading prose.

    `patterns` is what the day actually trained; `heavy_patterns` is the subset
    done heavy, and the two are separate because the 48-hour gate is about
    heaviness, not about touching a pattern at all — «один подход подтягиваний,
    сколько идёт» is a pull day that must not block tomorrow.

    `minimum_item_id` points at the line of the plan the minimum is marked on.
    29 August is the reason the column exists: a minimum declared inside the
    training block, with no tick of its own, was not done — twice, on two
    different days, once after the wording was fixed.
    """

    __tablename__ = "training_day"

    day_date: Mapped[date_type] = mapped_column(
        Date, ForeignKey("day.date", ondelete="CASCADE"), primary_key=True
    )

    patterns: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    heavy_patterns: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )

    planned_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    done_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    skipped: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # «Улица утром — пункт 1 в КАЖДОЙ тренировке». Nullable, because "не
    # отмечено" is a different fact from "не было": the outdoor line is the one
    # that was silently eaten by the strength block twice in one week.
    outdoor_done: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Whether the day actually reached failure. Two of these in a week put the
    # rest of it in RIR 2-3, which is the third gate of `/train`.
    near_failure: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # The dated paragraph of `training/state.md` — «2026-08-12. Ноги+кор, 36
    # минут…». Prose the coach wrote about that day, kept because it is the only
    # record of *why* a day went the way it did, and it is not derivable from
    # the patterns and the sets beside it.
    note_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    minimum_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    minimum_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_item.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Sets per pattern, `{"pull": 3, "core": 2}`. JSONB rather than a child
    # table: the whole of it is read together, written together and never
    # joined against, and a row per set would be six rows a day of nothing.
    sets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<TrainingDay(date={self.day_date}, skipped={self.skipped})>"


class TrainingState(Base):
    """
    The state of the body as of the last recompute — derived, never authored.

    Everything here except `progression_stage` is a function of `training_day`
    and `body_complaint`, and `app.training.state.recompute` is that function.
    The row exists so that `/train` and the page ask one cheap question instead
    of folding four weeks of rows on every read; `recomputed_at` is what makes
    it honest about being a snapshot rather than a source.

    `progression_stage` is the exception and is marked as such: «объём 4x6-8 RIR
    1-2» is a decision a person made about the next four weeks, not a number
    derivable from what happened. The recompute carries it through untouched,
    which is also what makes two recomputes in a row identical.
    """

    __tablename__ = "training_state"
    __table_args__ = (
        CheckConstraint(
            f"id = {TRAINING_STATE_ID}", name="ck_training_state_singleton"
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    last_heavy_pull: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    last_heavy_push: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    last_legs: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    last_run: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    last_outdoor: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    last_cardio: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    near_failure_days: Mapped[list[date_type]] = mapped_column(
        ARRAY(Date), default=list, server_default="{}"
    )
    # Sets per pattern since Monday — the counter the fifth gate weighs against
    # sixteen. A map, because the patterns are data.
    week_sets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    progression_stage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    # Consecutive skipped days ending at the last recorded one. Two of them and
    # the week is not caught up: the next day is RIR 3 at minus thirty percent.
    skipped_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    recomputed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<TrainingState(recomputed_at={self.recomputed_at})>"


class BodyComplaint(Base):
    """
    A symptom that gates training — «кольнуло левое плечо на третьем подходе».

    Deliberately not a medical record. `area` and `context` are what a gate
    needs in order to take pull-ups out of today's suggestion; diagnoses,
    prescriptions and test results are out of scope by ADR-0014 and by this
    ticket, and nothing here is ever sent to a model or written to a log.

    A complaint closes by a date and a reason rather than by disappearing: the
    canon for closing one is «день с нагрузкой на эту область и без симптомов»,
    and a row that vanished would take with it the eight days the check kept
    being postponed.
    """

    __tablename__ = "body_complaint"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'closed')", name="ck_body_complaint_status"
        ),
        CheckConstraint(
            "status <> 'closed' OR closed_on IS NOT NULL",
            name="ck_body_complaint_closed_has_date",
        ),
        Index("ix_body_complaint_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opened_on: Mapped[date_type] = mapped_column(Date)
    area: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), server_default=COMPLAINT_OPEN)
    closed_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<BodyComplaint(area='{self.area}', status='{self.status}')>"


class PersonalRecord(Base):
    """
    One personal record, with the date it was reached and the target beyond it.

    `sets` is text — «9/10/5/3» is the record and also the diagnosis: the first
    set to failure ate the other three. A single best number would throw away
    exactly the part worth reading, so `best_plain` sits beside it and is
    nullable for the exercises where one number means nothing.
    """

    __tablename__ = "personal_record"
    __table_args__ = (Index("ix_personal_record_exercise", "exercise"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exercise: Mapped[str] = mapped_column(Text)
    variant: Mapped[str | None] = mapped_column(Text, nullable=True)
    sets: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_plain: Mapped[int | None] = mapped_column(Integer, nullable=True)
    achieved_on: Mapped[date_type] = mapped_column(Date)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PersonalRecord(exercise='{self.exercise}', on={self.achieved_on})>"
