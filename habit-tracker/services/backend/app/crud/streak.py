# [review:need-review] PHASE-01/27-streak-mode-endpoint, PHASE-03/107, PHASE-03/90, PHASE-03/127, PHASE-01/207
# summary: avoid-streak calculation over full entry history (current/best/last relapse, relapse days, tracked-since) on the one day boundary `today_local()`; the one rule of what makes an entry a relapse whatever fields the category has, and the one-tap relapse writer that a repeated tap within a minute cannot double
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.daytime import today_local
from app.crud import entry as entry_crud
from app.crud.quick_mark import IMPLICIT_AMOUNT
from app.crud.values import format_number, is_true_value, parse_number
from app.models import Category, Entry, EntryValue, Field
from app.models.field import FieldType

# `is_relapse_value` is exported deliberately: «что такое сорвавшееся значение»
# has two consumers now — the avoid streak here and the `abstain` rule of a
# challenge (`app.challenge.rules`) — and one definition. `compute_streak` is
# *not* shared with them: a day with no entries is clean for a streak and a miss
# for an obligation, and that difference is the point of the second module.
__all__ = [
    "StreakStats",
    "compute_streak",
    "get_category_streak",
    "get_category_streaks",
    "is_relapse_value",
    "record_relapse",
]

# The field types whose value can say whether the avoided thing happened: a
# ticked box, a count above zero, time spent above zero. A category with none of
# them has no way to record a clean day, so every entry it gets is a relapse.
RELAPSE_FIELD_TYPES: tuple[FieldType, ...] = (
    FieldType.BOOLEAN,
    FieldType.NUMBER,
    FieldType.DURATION,
)

_NUMERIC_RELAPSE_TYPES: tuple[FieldType, ...] = (FieldType.NUMBER, FieldType.DURATION)

# A second relapse of the same category this soon after the first is the same
# tap twice — a double click, a retried request without its key — not a second
# cigarette.
RELAPSE_REPEAT_WINDOW = timedelta(minutes=1)


@dataclass(frozen=True)
class StreakStats:
    """Streak numbers for one category, computed over its whole history."""

    current_streak: int
    best_streak: int
    last_relapse_date: date | None
    # Every day that held a relapse, ascending — what the history chart draws.
    relapse_dates: tuple[date, ...] = ()
    # The first tracked day: where the timeline of the streak starts.
    tracked_since: date | None = None


def is_relapse_value(
    field_type: FieldType,
    value: str | None,
    *,
    field_id: int | None = None,
    entry_id: int | None = None,
) -> bool:
    """
    A single stored value marks the day as a relapse.

    Boolean true and a number or a duration above zero count as a relapse; zero
    (or negative), an empty value and any other field type leave the day clean.
    `field_id`/`entry_id` only localize the warning `parse_number` logs for
    unparsable text — they never affect the verdict.
    """
    if field_type == FieldType.BOOLEAN:
        return is_true_value(value)
    if field_type in _NUMERIC_RELAPSE_TYPES:
        return (parse_number(value, field_id=field_id, entry_id=entry_id) or 0) > 0
    return False


def is_relapse_entry(
    values: Iterable[tuple[int, FieldType, str | None]],
    *,
    category_can_say_no: bool,
    entry_id: int | None = None,
) -> bool:
    """
    One entry of an avoid category is a relapse.

    The verdict reads only what the entry holds, so an entry from the Today tap,
    a quick mark, the day plan or an import is judged the same way. A category
    that can say «не было» (it has a field of `RELAPSE_FIELD_TYPES`) relapses on
    a value that says so; a category that cannot relapses on every entry,
    because an entry is the only thing such a category can record.
    `values` are `(field_id, field_type, value)`; the ids only localize a warning.
    """
    if not category_can_say_no:
        return True
    return any(
        is_relapse_value(field_type, value, field_id=field_id, entry_id=entry_id)
        for field_id, field_type, value in values
    )


def relapse_field(category: Category) -> Field | None:
    """
    The field a one-tap relapse is written into, or None when there is none.

    The primary field when it can say «случилось», else the first checkbox, else
    the first count or duration, in field order. A box beats a count because
    «случилось» is a fact and the count is a detail the tap does not know.
    """
    fields = category.fields
    primary = next((f for f in fields if f.id == category.primary_field_id), None)
    if primary is not None and primary.field_type in RELAPSE_FIELD_TYPES:
        return primary
    boolean = next((f for f in fields if f.field_type == FieldType.BOOLEAN), None)
    if boolean is not None:
        return boolean
    return next((f for f in fields if f.field_type in _NUMERIC_RELAPSE_TYPES), None)


def _relapse_value(target: Field) -> str:
    """What one tap writes: a ticked box, or one of whatever is being counted."""
    if target.field_type == FieldType.BOOLEAN:
        return "true"
    return format_number(IMPLICIT_AMOUNT)


def _can_say_no(category: Category) -> bool:
    return any(f.field_type in RELAPSE_FIELD_TYPES for f in category.fields)


def compute_streak(
    entry_dates: set[date], relapse_dates: set[date], today: date
) -> StreakStats:
    """
    Turn the day sets into current/best streak lengths.

    The timeline starts at the first tracked day and ends at `today`
    (or later, if entries were logged for future dates). A day without
    entries is clean, so gaps extend the streak instead of breaking it.
    The current streak is the trailing run of clean days; a relapse today
    means a current streak of zero.
    """
    if not entry_dates:
        return StreakStats(current_streak=0, best_streak=0, last_relapse_date=None)

    start = min(entry_dates)
    end = max(today, max(entry_dates))

    current = 0
    best = 0
    day = start
    while day <= end:
        if day in relapse_dates:
            current = 0
        else:
            current += 1
            best = max(best, current)
        day += timedelta(days=1)

    return StreakStats(
        current_streak=current,
        best_streak=best,
        last_relapse_date=max(relapse_dates) if relapse_dates else None,
        relapse_dates=tuple(sorted(relapse_dates)),
        tracked_since=start,
    )


@dataclass
class _History:
    """The days of one category, gathered entry by entry."""

    can_say_no: bool
    entry_dates: set[date] = field(default_factory=set)
    relapse_dates: set[date] = field(default_factory=set)


async def _load_histories(
    db: AsyncSession, condition: ColumnElement[bool]
) -> dict[int, _History]:
    """
    Read the full history of every category matching `condition`, in one query.

    «Can this category say no» rides along as a correlated EXISTS, not as a
    second query per category: the bulk read on Today and the dashboard must not
    grow with the number of avoid categories.
    """
    verdict_field = aliased(Field)
    can_say_no = (
        exists()
        .where(
            verdict_field.category_id == Category.id,
            verdict_field.field_type.in_(RELAPSE_FIELD_TYPES),
        )
        .label("can_say_no")
    )
    result = await db.execute(
        select(
            Category.id,
            can_say_no,
            Entry.id,
            Entry.entry_date,
            EntryValue.value,
            Field.id,
            Field.field_type,
        )
        .join(Entry, Entry.category_id == Category.id, isouter=True)
        .join(EntryValue, EntryValue.entry_id == Entry.id, isouter=True)
        .join(Field, Field.id == EntryValue.field_id, isouter=True)
        .where(condition)
        .order_by(Category.name, Category.id)
    )

    histories: dict[int, _History] = {}
    entries: dict[int, tuple[int, date, list[tuple[int, FieldType, str | None]]]] = {}
    for row in result.all():
        category_id, says_no, entry_id, entry_date, value, field_id, field_type = row
        histories.setdefault(category_id, _History(can_say_no=bool(says_no)))
        if entry_id is None or entry_date is None:
            continue
        _, _, values = entries.setdefault(entry_id, (category_id, entry_date, []))
        if field_id is not None and field_type is not None:
            values.append((field_id, field_type, value))

    for entry_id, (category_id, entry_date, values) in entries.items():
        history = histories[category_id]
        history.entry_dates.add(entry_date)
        if is_relapse_entry(
            values, category_can_say_no=history.can_say_no, entry_id=entry_id
        ):
            history.relapse_dates.add(entry_date)
    return histories


async def get_category_streak(
    db: AsyncSession, category_id: int, today: date | None = None
) -> StreakStats:
    """
    Compute the streak of a category from every entry it ever had.

    "Сегодня" is `today_local()` — the one boundary of `app.core.daytime`, read
    from the `day_rule_set` row in force. It used to be `datetime.now(utc).date()`,
    which was the last second arithmetic of days left in `app/` and meant that a
    mark made at 00:30 landed in one day for the plan and in the next one for the
    streak. `today` can still be passed in to pin the timeline.

    The frontend needs no matching change: `lib/streak-format.ts` renders
    `last_relapse_date`, a date-only string with no time in it, and there is no
    day boundary on that side to move.
    """
    histories = await _load_histories(db, Category.id == category_id)
    history = histories.get(category_id)
    if history is None:
        return compute_streak(set(), set(), today or today_local())
    return compute_streak(
        history.entry_dates, history.relapse_dates, today or today_local()
    )


async def get_category_streaks(
    db: AsyncSession, streak_mode: str, today: date | None = None
) -> list[tuple[int, StreakStats]]:
    """Compute every category of one mode from one joined history query."""
    histories = await _load_histories(db, Category.streak_mode == streak_mode)
    reference_day = today or today_local()
    return [
        (category_id, compute_streak(h.entry_dates, h.relapse_dates, reference_day))
        for category_id, h in histories.items()
    ]


async def _recent_relapse(
    db: AsyncSession, category: Category, on: date
) -> Entry | None:
    """
    The relapse of `category` on `on` written within the repeat window, if any.

    The day matters: an entry written a moment ago for last week is a record of
    the past, not the same tap as this one.
    """
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.values))
        .where(
            Entry.category_id == category.id,
            Entry.entry_date == on,
            Entry.created_at >= func.now() - RELAPSE_REPEAT_WINDOW,
        )
        .order_by(Entry.created_at.desc(), Entry.id.desc())
    )
    field_types = {f.id: f.field_type for f in category.fields}
    can_say_no = _can_say_no(category)
    for entry in result.scalars():
        values = [
            (v.field_id, field_types[v.field_id], v.value)
            for v in entry.values
            if v.field_id in field_types
        ]
        if is_relapse_entry(values, category_can_say_no=can_say_no, entry_id=entry.id):
            return entry
    return None


async def _write_relapse(
    db: AsyncSession, category: Category, on: date, idempotency_key: str | None
) -> Entry:
    entry = Entry(
        category_id=category.id,
        entry_date=on,
        idempotency_key=idempotency_key,
    )
    db.add(entry)
    await db.flush()
    target = relapse_field(category)
    if target is not None:
        db.add(
            EntryValue(
                entry_id=entry.id, field_id=target.id, value=_relapse_value(target)
            )
        )
    await db.commit()
    written = await entry_crud.get_entry(db, entry.id)
    if written is None:
        raise RuntimeError(f"relapse entry {entry.id} vanished right after commit")
    return written


async def record_relapse(
    db: AsyncSession, category: Category, idempotency_key: str | None = None
) -> tuple[Entry, bool]:
    """
    Record that the avoided thing happened today; return the entry and whether it is new.

    One rule for every avoid category, whatever its fields: the value goes into
    `relapse_field` (a ticked box, or one of a count or a duration), and a
    category without such a field gets an entry with no values, which
    `is_relapse_entry` reads as a relapse all the same. The amount and a note
    are details the caller adds to the returned entry afterwards.

    Not new — and nothing written — when `idempotency_key` names an entry that
    already exists (a replayed request), or when the category already got a
    relapse within `RELAPSE_REPEAT_WINDOW` (a double tap).
    """
    if idempotency_key is not None:
        replayed = await entry_crud.get_entry_by_idempotency_key(db, idempotency_key)
        if replayed is not None:
            return replayed, False

    today = today_local()
    recent = await _recent_relapse(db, category, today)
    if recent is not None:
        return recent, False

    try:
        return await _write_relapse(db, category, today, idempotency_key), True
    except IntegrityError:
        # A concurrent replay of the same key won the race between the lookup
        # and the insert; the unique constraint is the backstop.
        await db.rollback()
        if idempotency_key is None:
            raise
        winner = await entry_crud.get_entry_by_idempotency_key(db, idempotency_key)
        if winner is None:
            raise
        return winner, False
