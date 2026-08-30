# [review:need-review] PHASE-03/88
# summary: the mark tables — `plan_mark` (at most one per item, hanging off the item's uuid rather than off its position) and the append-only `plan_mark_event`, which outlives the item because git no longer versions marks
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# The three things a mark can say. Absence of a row is the fourth answer —
# `pending` — and it is deliberately not a value here: a row that means "no
# mark" would have to be created by somebody, and the whole point of the
# distinction `#88` draws is that nobody creates it.
MARK_DONE = "done"
MARK_FAILED = "failed"
MARK_SKIPPED = "skipped"
MARK_STATES: tuple[str, ...] = (MARK_DONE, MARK_FAILED, MARK_SKIPPED)

# Who wrote the mark. `web` is a click on the day page, `agent` the floating
# window of the local agent, `import` the migration off `.html` files, `llm` a
# mark proposed while closing the day. Stored because "the day says I trained"
# and "I said I trained" are different facts.
SOURCE_WEB = "web"
MARK_SOURCES: tuple[str, ...] = (SOURCE_WEB, "agent", "import", "llm")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`state IN ('a', 'b')` — spelled once for the model and the migration."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class PlanMark(Base):
    """
    The mark of one plan item: what happened to it, and the note about how.

    Keyed by the item's uuid, one row at most. Until now the key was the item's
    position in the DOM (`i7`, `t3`), so inserting a line above shifted every
    mark below it onto the wrong item silently. A uuid outlives an edit of the
    text, a reorder and a re-import, which is the entire reason the plan became
    rows.

    Absence of a row means `pending`. Together with `day.opened_at` that
    separates the four different kinds of "empty" the files could not tell
    apart: never came (`opened_at IS NULL`), came and did not get to it
    (`pending`), tried and did not do it (`failed`), and stopped being relevant
    (`skipped`).

    `marked_at` moves with the state, `updated_at` with any write. Two tabs
    marking the same line are then resolved by the database — the second write
    is an `ON CONFLICT DO UPDATE`, the last one wins, and `updated_at` says
    which one that was — instead of by the "empty over non-empty" rule
    `plan_server.py` needed because it wrote to a file without a transaction.
    """

    __tablename__ = "plan_mark"
    __table_args__ = (
        CheckConstraint(_in_list("state", MARK_STATES), name="ck_plan_mark_state"),
        CheckConstraint(_in_list("source", MARK_SOURCES), name="ck_plan_mark_source"),
    )

    # The primary key is the item: one mark per item, and no surrogate id for
    # anything to disagree about. Cascade, because a mark of a line that no
    # longer exists in any plan is not a fact about anything — the history of
    # how it got that way is kept by `plan_mark_event`, which does not cascade.
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_item.id", ondelete="CASCADE"),
        primary_key=True,
    )

    state: Mapped[str] = mapped_column(String(16))
    # "как прошло" — the sentence next to the tick. Half the value of a closed
    # day is here and not in the tick.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[str] = mapped_column(String(16), server_default=SOURCE_WEB)

    def __repr__(self) -> str:
        return f"<PlanMark(item_id={self.item_id}, state='{self.state}')>"


class PlanMarkEvent(Base):
    """
    One change of state, appended and never touched again.

    The log exists because the marks stopped being versioned the moment they
    left git: a `.html` in `.gitignore` had no history at all, and a single
    mutable row would have none either. Every transition is a row here,
    including the one that clears a mark — "I unticked it at 23:50" is exactly
    the kind of thing a person rereads a week later.

    `item_id` carries no foreign key on purpose. An item deleted from a plan
    takes its `plan_mark` with it, and that is right; taking the record of what
    was once ticked would make an append-only log that quietly forgets, which is
    not a log. `day_date` is stored for the same reason — it is what the log is
    read by once the item it points at is gone.
    """

    __tablename__ = "plan_mark_event"
    __table_args__ = (
        CheckConstraint(
            f"from_state IS NULL OR {_in_list('from_state', MARK_STATES)}",
            name="ck_plan_mark_event_from_state",
        ),
        CheckConstraint(
            f"to_state IS NULL OR {_in_list('to_state', MARK_STATES)}",
            name="ck_plan_mark_event_to_state",
        ),
        CheckConstraint(
            "from_state IS DISTINCT FROM to_state",
            name="ck_plan_mark_event_is_a_change",
        ),
        CheckConstraint(
            _in_list("source", MARK_SOURCES), name="ck_plan_mark_event_source"
        ),
        Index("ix_plan_mark_event_item_at", "item_id", "at"),
        Index("ix_plan_mark_event_day_at", "day_date", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    day_date: Mapped[date_type] = mapped_column("day_date", Date)

    # NULL on either side means `pending`: NULL -> 'done' is the first tick,
    # 'failed' -> NULL is the third click that takes the mark off again.
    from_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # The note as it stood at this transition, not a pointer to the current one:
    # the log has to read back as what happened, not as what is true now.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), server_default=SOURCE_WEB)

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<PlanMarkEvent(item_id={self.item_id}, "
            f"{self.from_state} -> {self.to_state})>"
        )
