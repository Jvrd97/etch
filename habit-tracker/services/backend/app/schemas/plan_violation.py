# [review:need-review] PHASE-03/147
# summary: wire types of a broken rule — the violation as the day screen reads it back, and the body a refused skeleton answers with; both carry rule codes, ids and numbers, and neither has a field the text of a plan line could travel in
"""
Wire types of a broken rule.

**There is no field here that could carry the text of a plan line, and that is
the design.** A violation is read by a screen, by a repair prompt and by whoever
looks at the day three months later; a task can be named after a diagnosis, and
the safest place for that name is nowhere in this file. What travels is the rule
code, the ids it was found on and the numbers involved — enough to point at the
line, not enough to quote it.

`message` is built by `app.day.constraints` out of the code and those ids, so it
is safe by construction rather than by review.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.plan_violation import ORIGINS, RULE_CODES, SEVERITIES


class PlanViolationResponse(BaseModel):
    """One recorded violation, as the day screen reads it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    day_date: date
    rule_code: str = Field(..., description=f"Одно из: {', '.join(RULE_CODES)}")
    severity: str = Field(..., description=f"Одно из: {', '.join(SEVERITIES)}")
    origin: str = Field(..., description=f"Одно из: {', '.join(ORIGINS)}")
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Только id пунктов и числа; текста пункта здесь нет",
    )
    created_at: datetime


class ViolationDetail(BaseModel):
    """One broken rule as a refusal reports it, before anything was stored."""

    rule_code: str
    severity: str
    detail: dict[str, Any] = Field(default_factory=dict)
    message: str


class SkeletonRejection(BaseModel):
    """
    Why the skeleton refused to write itself.

    A generator that breaks the canon it is built from is a bug in the
    generator, and answering with the rule codes rather than with a 500 is what
    makes that bug reportable: the same body goes into the repair prompt of
    `#148`.
    """

    error: str
    violations: list[ViolationDetail] = Field(default_factory=list)
