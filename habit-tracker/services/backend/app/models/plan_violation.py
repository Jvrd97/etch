# [review:need-review] PHASE-03/147
# summary: `plan_violation` — one row per broken rule of a draft, carrying the rule code, who broke it, how much it costs and a jsonb of ids and numbers; the text of the offending line is deliberately absent, because these rows outlive the plan
"""
The record of a rule a plan broke.

A row rather than a log line, for two reasons. A blocked draft has to be able to
explain itself to the model that produced it, and a log is not a thing an API
can hand back. And a `warn` on a person's own edit has to survive the session
that produced it: the whole point of the asymmetry is that the edit stands and
the note stays beside it.

**No text of the plan lives here.** `detail` holds item ids, rule codes and
numbers, and that is checked by a test rather than left to discipline. A task
can be named after a diagnosis, and a violation row has a longer life than the
plan it describes — the plan gets replaced whole by the next `POST`, the
violations of the days before it stay.

`plan_revision_id` and `job_id` are nullable and unreferenced here. The
revisions of `#150` and the background runs of `#149` are what will fill them;
the columns are part of this migration so that neither ticket needs a second
one, which is the same reason `#121` shipped `undone_at` unused.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# The three vocabularies, spelled here rather than imported from
# `app.day.constraints`. Not duplication for its own sake: `constraints` imports
# `app.models.day` for the rule row, `app.models` imports this module to register
# the mapper, and an import the other way closes the circle. The migration spells
# them out for the same reason a migration always does — it has to keep meaning
# what it meant on the day it ran — and `test_day_skeleton` asserts all three
# spellings agree, so a ninth rule cannot be added to one of them alone.
RULE_CODES: tuple[str, ...] = (
    "hard_edges_only",
    "free_evening_empty",
    "work_cap",
    "task_cap",
    "health_before_work",
    "relationship_anchor_required",
    "no_overlap",
    "target_day_only",
)
SEVERITIES: tuple[str, ...] = ("block", "warn")
ORIGINS: tuple[str, ...] = ("ai", "fallback", "human")

# Widths of the three vocabularies. The CHECKs below are the real guard; the
# lengths only keep a typo from becoming a paragraph.
RULE_CODE_LENGTH = 40
SEVERITY_LENGTH = 8
ORIGIN_LENGTH = 8


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`severity IN ('block', 'warn')` — spelled once for model and migration."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class PlanViolation(Base):
    """One rule broken by one draft of one day."""

    __tablename__ = "plan_violation"
    __table_args__ = (
        CheckConstraint(
            _in_list("rule_code", RULE_CODES), name="ck_plan_violation_rule_code"
        ),
        CheckConstraint(
            _in_list("severity", SEVERITIES), name="ck_plan_violation_severity"
        ),
        CheckConstraint(_in_list("origin", ORIGINS), name="ck_plan_violation_origin"),
        # The one query this table exists to answer: what went wrong on this day,
        # and how often does this particular rule get broken.
        Index("ix_plan_violation_day_rule", "day_date", "rule_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # No foreign key to `day`: a violation of a draft for a date whose `day` row
    # does not exist yet is exactly the case the generator produces, and a
    # constraint here would refuse to record the reason the day was never made.
    day_date: Mapped[date_type] = mapped_column(Date, index=True)

    plan_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    rule_code: Mapped[str] = mapped_column(String(RULE_CODE_LENGTH))
    severity: Mapped[str] = mapped_column(String(SEVERITY_LENGTH))
    origin: Mapped[str] = mapped_column(String(ORIGIN_LENGTH))

    # Ids and numbers. Never the text of a line — see the module docstring.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<PlanViolation(day_date={self.day_date}, rule_code='{self.rule_code}', "
            f"severity='{self.severity}', origin='{self.origin}')>"
        )
