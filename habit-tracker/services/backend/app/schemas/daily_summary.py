# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: write-only day-plan DTOs — numeric metrics resolved by id, unresolved wording, draft/apply requests
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LogMetricOp(BaseModel):
    """
    One numeric value the day-plan proposes to record.

    Resolution is by id only: `category_id` and `field_id` are required and
    names never take part. A field match by name was tried in this project and
    removed (#57) — it silently hits the wrong field, and a model guessing the
    name is the same mistake with more confidence behind it.
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal["log_metric"] = "log_metric"
    category_id: int
    field_id: int
    value: float
    # The wording this metric was read from, shown next to the checkbox so the
    # user can tell what the model thought it heard. Never logged.
    source_text: str = Field(..., min_length=1)
    # Set by the model when it placed the metric without confidence; the UI
    # brings such a row in unchecked.
    uncertain: bool = False
    # Set by the model when the value itself looks wrong (300 push-ups).
    implausible: bool = False


class UnresolvedMetric(BaseModel):
    """Something numeric the model heard but could not place in any category."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1)
    reason: str | None = None


class DailySummaryPlan(BaseModel):
    """
    What the model proposes to write for a day — nothing else is expressible.

    The schema is write-only by construction: there is no operation for
    deleting, renaming or retyping anything, so the plan cannot instruct a
    destructive change however the prompt is answered. Metrics the model could
    not place land in `unresolved` and create nothing.
    """

    model_config = ConfigDict(extra="forbid")

    metrics: list[LogMetricOp] = Field(default_factory=list)
    unresolved: list[UnresolvedMetric] = Field(default_factory=list)


class DailySummaryDraftRequest(BaseModel):
    """
    Free-text retelling of a day plus the date it belongs to.

    `entry_date` is not just carried to the apply step by the client: it goes
    into the prompt, because a retelling says "вчера" and "утром" freely and a
    model that does not know which day it is reading may try to date a metric
    itself. Stating the day makes those words a time inside it.
    """

    transcript: str = Field(..., min_length=1)
    entry_date: date


class DailySummaryApplyRequest(BaseModel):
    """The metrics the user left checked, applied to `entry_date` in one go."""

    entry_date: date
    metrics: list[LogMetricOp] = Field(..., min_length=1)


class DailySummaryApplyResponse(BaseModel):
    """Ids of the entries the apply created — one per category touched."""

    entry_ids: list[int]
