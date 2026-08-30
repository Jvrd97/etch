# [review:need-review] PHASE-03/121
# summary: the quick mark from button to database — the validation the directory owes (`field_id` belongs to the category, `kind` fits the field type), the tap that accumulates into the day's entry through `entry_crud.checklist_entry_id` instead of adding a row, the relapse that deliberately does add one, and the journal row beside every write
"""
What a quick mark means and where its value lands.

Three decisions live here and nowhere else.

**The day is asked, never computed.** `record_event` takes the moment of the tap
and calls `app.core.daytime.local_date()` on it. There is no timezone setting in
this module, no clock read inside the write path and no second arithmetic of
days: a tap at 00:30 lands in the same day a work interval at 00:30 lands in,
because both ask the same function.

**An increment accumulates, it does not append.** `kind='increment'` finds the
canonical entry of `(category_id, entry_date)` with the existing
`entry_crud.checklist_entry_id` and adds its step to the value already there,
rendering the result with `values.format_number`. Five taps are one row of
`entries` and one row of `entry_values`, which is ADR-0007's invariant reaching
the quick path. `kind='relapse'` is the exception on purpose: a relapse is an
event with its own time, and two of them collapsed into a counter would lose the
only thing worth keeping about them.

**The directory validates what `POST /entries` never has.** A button pointing at
a field of somebody else's category, a tick on a number, a relapse on a
`build` category — all three are refused at creation with a reason naming ids,
never values. The shape of the answer is `validate_metric_ops` in
`crud/daily_summary.py`: every reason at once, so one repair pass sees them all.

PII: every message and every log line here is built from ids. `label`, the
stored value and the note are never formatted into either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.crud import entry as entry_crud
from app.crud.values import format_number, parse_number
from app.models import Category, Entry, EntryValue, FieldType
from app.models.quick_mark import (
    KIND_CHECK,
    KIND_INCREMENT,
    KIND_RELAPSE,
    NUMERIC_KINDS,
    QuickMark,
    QuickMarkEvent,
)
from app.schemas.quick_mark import QuickMarkCreate

__all__ = [
    "DayState",
    "RecordedEvent",
    "create_quick_mark",
    "day_state",
    "event_by_idempotency_key",
    "get_quick_mark",
    "list_quick_marks",
    "record_event",
    "replayed_event",
    "validate_quick_mark",
]

# The category mode a relapse button is allowed on. A `build` category counts
# days it happened; "сорвался" has no meaning there.
AVOID_STREAK_MODE = "avoid"

# Field types that can hold a number one tap moves.
NUMERIC_FIELD_TYPES: tuple[FieldType, ...] = (FieldType.NUMBER, FieldType.DURATION)

# What one tap is worth when the button has no step and the caller named no
# value — a cigarette, a glass, one of whatever is being counted.
IMPLICIT_AMOUNT = 1.0


@dataclass(frozen=True)
class DayState:
    """What a button's day looks like after (or before) a tap."""

    today_total: float | None
    done: bool


@dataclass(frozen=True)
class RecordedEvent:
    """
    A tap as it was written, carried as values rather than as ORM rows.

    The API answers from this without touching the session again, which is what
    keeps "one call per tap" true on the wire and in the code.
    """

    event_id: int
    quick_mark_id: int
    entry_id: int | None
    entry_date: date
    occurred_at: datetime
    state: DayState


async def get_quick_mark(db: AsyncSession, quick_mark_id: int) -> QuickMark | None:
    """One button by id, or None."""
    result = await db.execute(select(QuickMark).where(QuickMark.id == quick_mark_id))
    return result.scalar_one_or_none()


def _ordered() -> Select[tuple[QuickMark]]:
    """
    The directory in the order the buttons are drawn in.

    `id` is the tie-break: buttons entered in one sitting share an `order`, and
    without it the row order of the table would decide which hotkey is `1`.
    """
    return select(QuickMark).order_by(QuickMark.order, QuickMark.id)


async def list_quick_marks(
    db: AsyncSession, *, on: date, active_only: bool = True
) -> list[tuple[QuickMark, DayState]]:
    """
    The directory with the state of the day `on` attached to every button.

    One query per button for the state is deliberate: the directory is nine to
    twenty rows by design (`hotkey` is one character), and a hand-written join
    over the EAV would be a second implementation of "what does today say" next
    to `day_state`.
    """
    query = _ordered()
    if active_only:
        query = query.where(QuickMark.is_active.is_(True))
    result = await db.execute(query)
    marks = list(result.scalars().all())
    return [(mark, await day_state(db, mark, on)) for mark in marks]


async def _day_total(db: AsyncSession, mark: QuickMark, on: date) -> float | None:
    """
    Everything the day holds for this button's field, summed.

    Sums across every entry of `(category_id, on)` rather than reading the
    canonical one: an increment keeps its number in that single entry, but a
    relapse writes a row per event, and both have to report the same way or the
    two kinds of button would count differently on the same screen.
    """
    result = await db.execute(
        select(EntryValue.value, EntryValue.entry_id)
        .join(Entry, Entry.id == EntryValue.entry_id)
        .where(
            Entry.category_id == mark.category_id,
            Entry.entry_date == on,
            EntryValue.field_id == mark.field_id,
        )
    )
    rows = result.all()
    if not rows:
        return None
    numbers = [
        parse_number(value, field_id=mark.field_id, entry_id=entry_id)
        for value, entry_id in rows
    ]
    return float(sum(number for number in numbers if number is not None))


async def day_state(db: AsyncSession, mark: QuickMark, on: date) -> DayState:
    """
    What the day says about this button right now.

    A tick answers with `today_total=None`: a box is not a quantity, and a 1
    there would be read as "one litre" by whatever draws the number. Everything
    else answers with the sum, and `done` is that sum having moved off zero.
    """
    if mark.kind == KIND_CHECK:
        ticks = await entry_crud.get_checklist_state(db, mark.category_id, on)
        return DayState(today_total=None, done=ticks.get(mark.field_id, False))

    total = await _day_total(db, mark, on)
    return DayState(today_total=total, done=total is not None and total > 0)


def validate_quick_mark(data: QuickMarkCreate, category: Category | None) -> list[str]:
    """
    Every reason the button cannot be created, so one repair pass sees them all.

    Semantic, not formal: Pydantic already knows the shape. Checked here is that
    the ids point somewhere real and agree with each other — the category
    exists, the field is that category's own, the kind fits what the field can
    hold, and a button that writes a number knows how much one tap is worth.
    """
    if category is None:
        return [f"unknown category_id {data.category_id}"]

    errors: list[str] = []
    field = next((f for f in category.fields if f.id == data.field_id), None)
    if field is None:
        errors.append(
            f"field_id {data.field_id} does not belong to "
            f"category_id {data.category_id}"
        )
    elif data.kind in NUMERIC_KINDS and field.field_type not in NUMERIC_FIELD_TYPES:
        errors.append(
            f"kind {data.kind!r} needs a number field, but field_id "
            f"{data.field_id} has field_type {field.field_type.value!r}"
        )
    elif data.kind == KIND_CHECK and field.field_type is not FieldType.BOOLEAN:
        errors.append(
            f"kind {KIND_CHECK!r} needs a checkbox, but field_id "
            f"{data.field_id} has field_type {field.field_type.value!r}"
        )

    if data.kind == KIND_RELAPSE and category.streak_mode != AVOID_STREAK_MODE:
        errors.append(
            f"kind {KIND_RELAPSE!r} needs an avoid category, but category_id "
            f"{data.category_id} has streak_mode {category.streak_mode!r}"
        )

    if data.kind in NUMERIC_KINDS and data.step is None:
        errors.append(
            f"kind {data.kind!r} needs a step: one tap has to be worth something"
        )

    return errors


async def create_quick_mark(db: AsyncSession, data: QuickMarkCreate) -> QuickMark:
    """
    Store a validated button.

    Validation is the caller's, not this function's: the API answers a list of
    reasons with 422, and doing it here would make the reasons an exception the
    endpoint has to translate back into the same list.
    """
    mark = QuickMark(
        label=data.label,
        category_id=data.category_id,
        field_id=data.field_id,
        kind=data.kind,
        step=None if data.step is None else Decimal(str(data.step)),
        unit_label=data.unit_label,
        icon=data.icon,
        color=data.color,
        hotkey=data.hotkey,
        order=data.order,
        show_in_agent=data.show_in_agent,
        is_active=data.is_active,
    )
    db.add(mark)
    await db.commit()
    await db.refresh(mark)
    return mark


async def event_by_idempotency_key(
    db: AsyncSession, idempotency_key: str
) -> QuickMarkEvent | None:
    """The tap already recorded under this key, or None."""
    result = await db.execute(
        select(QuickMarkEvent).where(QuickMarkEvent.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


def _amount(mark: QuickMark, value: float | None) -> float:
    """
    How much this tap writes.

    The caller's value wins over the button's step — that is how "250" typed by
    hand goes through the same path as the button — and a button with neither is
    worth one of whatever it counts.
    """
    if value is not None:
        return value
    if mark.step is not None:
        return float(mark.step)
    return IMPLICIT_AMOUNT


async def _entry_value(
    db: AsyncSession, entry_id: int, field_id: int
) -> EntryValue | None:
    result = await db.execute(
        select(EntryValue).where(
            EntryValue.entry_id == entry_id, EntryValue.field_id == field_id
        )
    )
    return result.scalar_one_or_none()


async def _write_number(
    db: AsyncSession, mark: QuickMark, on: date, amount: float, *, accumulate: bool
) -> tuple[int, float]:
    """
    Put `amount` into the day's entry, adding to what is there or replacing it.

    Returns the entry it landed in and how far the stored value moved, which is
    what the journal records. The entry is chosen by
    `entry_crud.checklist_entry_id` — the one rule for "which row is the day" —
    so a quick mark, a tick and the day-summary apply all deepen the same row
    instead of racing to create three.
    """
    entry_id = await entry_crud.checklist_entry_id(db, mark.category_id, on)
    if entry_id is None:
        entry = Entry(category_id=mark.category_id, entry_date=on)
        db.add(entry)
        await db.flush()
        entry_id = entry.id

    existing = await _entry_value(db, entry_id, mark.field_id)
    previous = 0.0
    if existing is not None:
        parsed = parse_number(existing.value, field_id=mark.field_id, entry_id=entry_id)
        previous = 0.0 if parsed is None else parsed

    updated = previous + amount if accumulate else amount
    rendered = format_number(updated)
    if existing is None:
        db.add(EntryValue(entry_id=entry_id, field_id=mark.field_id, value=rendered))
    else:
        existing.value = rendered

    await db.flush()
    return entry_id, updated - previous


async def _write_relapse(
    db: AsyncSession, mark: QuickMark, on: date, amount: float
) -> int:
    """
    Append one relapse: a new entry, with its own `created_at` and its own row.

    The only writer here that does not converge on the day's entry, and the
    reason is in ADR-0018: the history has to show every relapse with its time,
    not a counter that says three.
    """
    entry = Entry(category_id=mark.category_id, entry_date=on)
    db.add(entry)
    await db.flush()
    db.add(
        EntryValue(
            entry_id=entry.id, field_id=mark.field_id, value=format_number(amount)
        )
    )
    await db.flush()
    return entry.id


async def record_event(
    db: AsyncSession,
    mark: QuickMark,
    *,
    at: datetime,
    value: float | None = None,
    utc_offset_minutes: int = 0,
    source: str,
    idempotency_key: str | None = None,
) -> RecordedEvent:
    """
    Apply one tap of `mark` made at the moment `at`, and journal it.

    `at` is a required, timezone-aware moment rather than a default of "now":
    the day it belongs to is `local_date(at)`, and a test that wants to know
    where 00:30 lands has to be able to say which 00:30 it means. `local_date`
    refuses a naive datetime, so a caller that forgets the timezone fails loudly
    instead of shifting the day by the local offset.
    """
    on = local_date(at)
    entry_id: int | None
    delta: float | None = None
    bool_value: bool | None = None

    if mark.kind == KIND_CHECK:
        # Zero means "снять галку" — the one value a tick reads as false, and
        # the only way a button can untick without a second endpoint.
        bool_value = value is None or value != 0
        entry = await entry_crud.upsert_checklist_values(
            db, mark.category_id, on, {mark.field_id: bool_value}
        )
        entry_id = entry.id
    elif mark.kind == KIND_RELAPSE:
        amount = _amount(mark, value)
        entry_id = await _write_relapse(db, mark, on, amount)
        delta = amount
    else:
        amount = _amount(mark, value)
        entry_id, delta = await _write_number(
            db, mark, on, amount, accumulate=mark.kind == KIND_INCREMENT
        )

    event = QuickMarkEvent(
        quick_mark_id=mark.id,
        entry_id=entry_id,
        entry_date=on,
        occurred_at=at,
        utc_offset_minutes=utc_offset_minutes,
        delta=None if delta is None else Decimal(str(delta)),
        bool_value=bool_value,
        source=source,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    await db.flush()

    state = await day_state(db, mark, on)
    recorded = RecordedEvent(
        event_id=event.id,
        quick_mark_id=mark.id,
        entry_id=entry_id,
        entry_date=on,
        occurred_at=event.occurred_at,
        state=state,
    )
    await db.commit()
    return recorded


async def replayed_event(
    db: AsyncSession, mark: QuickMark, event: QuickMarkEvent
) -> RecordedEvent:
    """
    The answer to a tap that was already recorded under this idempotency key.

    Reads the day again rather than replaying anything: the caller is entitled
    to the current state, and the point of the key is that the second request
    changed nothing.
    """
    return RecordedEvent(
        event_id=event.id,
        quick_mark_id=event.quick_mark_id,
        entry_id=event.entry_id,
        entry_date=event.entry_date,
        occurred_at=event.occurred_at,
        state=await day_state(db, mark, event.entry_date),
    )
