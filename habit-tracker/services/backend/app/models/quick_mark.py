# [review:need-review] PHASE-03/121
# summary: the quick-mark directory (`quick_marks`) and its journal (`quick_mark_events`) — one row per button, one row per tap, with the vocabularies of `kind` and `source` spelled once for the model, the migration and the validator
"""
The two tables behind a button that records something in one tap.

**The directory holds intent, never a measurement.** A row of `quick_marks` says
"there is a button «+250 мл», it belongs to this field of this category, and a
tap on it adds 250". The number itself still lives in `entry_values`, where it
has always lived; nothing here is a second source of truth about how much water
was drunk.

**The journal explains how a number got that way.** `quick_mark_events` gets a
row per tap: the delta applied, the moment, the client it came from, and the
entry it landed in. Three things come out of that which the EAV cannot answer —
where the marks actually come from, what the last tap was (so `#124` can undo
it), and what time of day a relapse happened. The sum of deltas is allowed to
drift away from the stored value, because a person may edit the value by hand;
that is named in ADR-0018 and is not reconciled.

`kind` and `source` are `String(20)` with a CHECK, not a PG enum: the project has
exactly one enum type (`fieldtype`) and extending it costs a migration with an
`autocommit_block()`. A fifth kind of button is not worth that price, and
`display_mode`/`streak_mode` are already spelled the same way.

Related: ADR-0018 (challenges and quick marks), ADR-0007 (one entry per
`(category_id, entry_date)` — the invariant `kind='increment'` extends).
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.core.database import Base

# What a button does when it is tapped.
#
# `increment` adds its step to the day's entry, `set_value` overwrites it,
# `check` ticks a box, `relapse` records that an avoided thing happened. The
# first three converge on the one entry of `(category_id, entry_date)`; the
# fourth deliberately does not — a relapse is an event with its own time, and
# collapsing two of them into a counter would lose the only fact worth keeping.
KIND_INCREMENT = "increment"
KIND_CHECK = "check"
KIND_SET_VALUE = "set_value"
KIND_RELAPSE = "relapse"
QUICK_MARK_KINDS: tuple[str, ...] = (
    KIND_INCREMENT,
    KIND_CHECK,
    KIND_SET_VALUE,
    KIND_RELAPSE,
)

# The kinds that write a number and therefore need a `step`.
NUMERIC_KINDS: tuple[str, ...] = (KIND_INCREMENT, KIND_SET_VALUE)

# Which client the tap came from. Stored because "я отмечаю из окна агента" and
# "я отмечаю из браузера" are different facts about the same habit, and after a
# month of them one of the two paths can be closed on evidence.
SOURCE_WEB = "web"
QUICK_MARK_SOURCES: tuple[str, ...] = (SOURCE_WEB, "ios", "agent", "plan")

# Precision of everything numeric here: three decimals is enough for 0.5 of a
# set and for 0.25 of a litre, and the column is the same shape as the ones
# ADR-0018 draws for challenges.
AMOUNT_PRECISION = 12
AMOUNT_SCALE = 3

# The uniqueness of a hotkey, named once for the model and the migration.
HOTKEY_UNIQUE_INDEX = "uq_quick_mark_hotkey"
HOTKEY_PRESENT = "hotkey IS NOT NULL"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`kind IN ('a', 'b')` — spelled once for the model and the migration."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class QuickMark(Base):
    """
    One button of the quick-mark directory.

    The directory starts empty and that is a valid state: Today simply shows no
    quick-mark section. There are no seeds, because a seeded button points at a
    category that may not exist on this installation.

    `unit_label` is a caption, not a unit of measurement: `Field` has no unit
    yet (`#176`), and the button carries "мл" so that the screen can say
    something true before that ticket lands. When the field gets a real unit,
    this column becomes an override and then goes away.
    """

    __tablename__ = "quick_marks"
    __table_args__ = (
        CheckConstraint(_in_list("kind", QUICK_MARK_KINDS), name="ck_quick_mark_kind"),
        Index("ix_quick_marks_order", "order", "id"),
        # A partial unique index rather than a UNIQUE constraint: postgres has
        # no `UNIQUE (...) WHERE ...` constraint form at all, and the predicate
        # is what keeps the hotkey optional. It is named the way ADR-0018 names
        # it so that growing it to `(user_id, hotkey)` for a second user stays a
        # drop and a create of one object, not a rebuild of the model.
        Index(
            HOTKEY_UNIQUE_INDEX,
            "hotkey",
            unique=True,
            postgresql_where=text(HOTKEY_PRESENT),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    label: Mapped[str] = mapped_column(String(60))
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))

    kind: Mapped[str] = mapped_column(String(20))
    # How much one tap is worth. Required for `increment`/`set_value` by the
    # validator rather than by the column, because `check` has nothing to put
    # here and a NOT NULL would force a meaningless 0 into every tick button.
    step: Mapped[Decimal | None] = mapped_column(
        Numeric(AMOUNT_PRECISION, AMOUNT_SCALE), nullable=True
    )
    unit_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # One character, no modifiers — the keyboard of `#122`. Unique across the
    # directory, and null for a button that has none.
    hotkey: Mapped[str | None] = mapped_column(String(1), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    show_in_agent: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<QuickMark(id={self.id}, kind='{self.kind}')>"


class QuickMarkEvent(Base):
    """
    One tap, appended and never rewritten.

    `entry_id` is nullable and detaches rather than cascades: an entry deleted
    from the editor takes its values with it, and that is right, but a log that
    forgets the tap ever happened is not a log. `entry_date` is stored for the
    same reason — it is what the journal is read by once the row it points at is
    gone.

    `undone_at` belongs to `#124` and is written by nothing here; the column is
    part of this migration so that undo does not need a second one.
    """

    __tablename__ = "quick_mark_events"
    __table_args__ = (
        CheckConstraint(
            _in_list("source", QUICK_MARK_SOURCES), name="ck_quick_mark_event_source"
        ),
        Index("ix_quick_mark_events_mark_date", "quick_mark_id", "entry_date"),
        Index("ix_quick_mark_events_date", "entry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    quick_mark_id: Mapped[int] = mapped_column(
        ForeignKey("quick_marks.id", ondelete="CASCADE")
    )
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), nullable=True
    )

    entry_date: Mapped[date_type] = mapped_column(Date)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # What the client's own clock was offset by. Kept next to `occurred_at`
    # rather than folded into it: the day the tap belongs to is decided by
    # `app.core.daytime`, and this column exists to explain a tap made abroad,
    # not to compete with that decision.
    utc_offset_minutes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )

    # How much the tap moved the stored value, and what a tick set the box to.
    # Exactly one of the two is filled: a number button has no boolean and a
    # tick has no delta.
    delta: Mapped[Decimal | None] = mapped_column(
        Numeric(AMOUNT_PRECISION, AMOUNT_SCALE), nullable=True
    )
    bool_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    source: Mapped[str] = mapped_column(String(20), server_default=SOURCE_WEB)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<QuickMarkEvent(id={self.id}, quick_mark_id={self.quick_mark_id}, "
            f"date={self.entry_date})>"
        )
