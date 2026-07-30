# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: write-only day-plan DTOs — numeric metrics resolved by id, the day's journal text with its append/create collision mode (JournalOp for apply, JournalOpPreview for draft), draft/apply requests
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class JournalDraft(BaseModel):
    """
    The day written out as text — the journal fields, exactly as the model wrote them.

    This is the model's half of the journal operation. It carries no decision
    about *where* the text goes: whether the day already has an entry is a fact
    about the database, not about the retelling, so the model is never asked.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=200)
    content: str = Field(..., min_length=1)
    mood: str | None = Field(None, max_length=50)
    tags: str | None = Field(None, max_length=500)


# How the day's text meets whatever the day already holds. `append` and `create`
# are the two halves of the same intent — keep what is there — and differ only in
# whether there is anything to keep. `replace` is the one that loses text, which
# is why it is never chosen for the user: the draft never emits it.
JournalMode = Literal["append", "create", "replace"]


class JournalOp(JournalDraft):
    """
    The journal operation as the apply receives it: the text plus the mode.

    `mode` is the collision decision the preview made. It is an intent, not a
    command — the apply resolves the day's entry again, because the day can gain
    or lose text between the preview and the button.

    Extra keys are tolerated here, unlike everywhere else in this module: the
    preview sends back the operation it was given, `existing_entry_id` and all,
    and that field is deliberately absent from this DTO. The server never reads
    it, so accepting and dropping it keeps the input contract honest about what
    is used without breaking a client that echoes the whole object.
    """

    model_config = ConfigDict(extra="ignore")

    op: Literal["write_journal"] = "write_journal"
    mode: JournalMode = "append"


class JournalOpPreview(JournalOp):
    """
    The journal operation as the preview shows it: the operation plus context.

    The draft fills `mode` in from what the date already holds and hands the
    client an operation it can display honestly — "дополнить запись за 30 июля"
    is a different promise from "создать запись", and a preview that cannot tell
    them apart is asking for blind approval. `existing_entry_id` is that context:
    shown, never trusted, and never read back off an apply request.
    """

    existing_entry_id: int | None = None


class DailySummaryPlan(BaseModel):
    """
    What the model proposes to write for a day — nothing else is expressible.

    The schema is write-only by construction: there is no operation for
    deleting, renaming or retyping anything, so the plan cannot instruct a
    destructive change however the prompt is answered. Metrics the model could
    not place land in `unresolved` and create nothing. The journal text is the
    one free-form thing here, and it too can only be added.
    """

    model_config = ConfigDict(extra="forbid")

    metrics: list[LogMetricOp] = Field(default_factory=list)
    unresolved: list[UnresolvedMetric] = Field(default_factory=list)
    journal: JournalDraft | None = None


class DailySummaryDraftResponse(BaseModel):
    """
    The plan as the client receives it: the model's proposal plus the collision.

    Differs from `DailySummaryPlan` in one place — the journal arrives as a
    `JournalOpPreview`, with the append/create decision already made from the
    database.
    """

    metrics: list[LogMetricOp] = Field(default_factory=list)
    unresolved: list[UnresolvedMetric] = Field(default_factory=list)
    journal: JournalOpPreview | None = None


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
    """What the user left checked, applied to `entry_date` in one transaction."""

    entry_date: date
    metrics: list[LogMetricOp] = Field(default_factory=list)
    journal: JournalOp | None = None

    @model_validator(mode="after")
    def _must_write_something(self) -> DailySummaryApplyRequest:
        """An apply that writes nothing is a mistake on the client, not a no-op.

        Either half may be empty on its own — a day of numbers without a text, a
        text without a number both happen — but an empty request means the
        screen let a dead button through, and answering 201 would hide it.
        """
        if not self.metrics and self.journal is None:
            raise ValueError("apply needs at least one metric or a journal operation")
        return self


class DailySummaryApplyResponse(BaseModel):
    """What the apply wrote: one entry per category touched, plus the day's text."""

    entry_ids: list[int]
    journal_entry_id: int | None = None
