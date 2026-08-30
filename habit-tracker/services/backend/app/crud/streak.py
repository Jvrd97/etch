# [review:need-review] PHASE-01/27-streak-mode-endpoint, PHASE-03/107
# summary: avoid-streak calculation over full entry history (current/best/last relapse)
# summary: its UTC day boundary is now documented as the one debt left over from the single boundary, closed by #90
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.values import is_true_value, parse_number
from app.models import Entry, EntryValue, Field
from app.models.field import FieldType


@dataclass(frozen=True)
class StreakStats:
    """Streak numbers for one category, computed over its whole history."""

    current_streak: int
    best_streak: int
    last_relapse_date: date | None


def is_relapse_value(
    field_type: FieldType,
    value: str | None,
    *,
    field_id: int | None = None,
    entry_id: int | None = None,
) -> bool:
    """
    A single stored value marks the day as a relapse.

    Boolean true and number > 0 count as a relapse; a zero (or negative)
    number, an empty value and any other field type leave the day clean.
    `field_id`/`entry_id` only localize the warning `parse_number` logs for
    unparsable text — they never affect the verdict.
    """
    if field_type == FieldType.BOOLEAN:
        return is_true_value(value)
    if field_type == FieldType.NUMBER:
        return (parse_number(value, field_id=field_id, entry_id=entry_id) or 0) > 0
    return False


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
    )


async def get_category_streak(
    db: AsyncSession, category_id: int, today: date | None = None
) -> StreakStats:
    """
    Compute the streak of a category from every entry it ever had.

    The day boundary here is UTC, and after PHASE-03/107 this is the only place
    in `app/` that disagrees with `app/core/daytime.local_date()`. It stays that
    way on purpose: the frontend parses `last_relapse_date` as a UTC instant
    (lib/streak-format.ts), so moving the server alone would make the two sides
    disagree by a day. TODO(#90): move both sides onto `local_date()` — the debt
    is named in ADR-0014. `today` can be passed in to pin the timeline.
    """
    result = await db.execute(
        select(
            Entry.id,
            Entry.entry_date,
            EntryValue.value,
            Field.id,
            Field.field_type,
        )
        .join(EntryValue, EntryValue.entry_id == Entry.id, isouter=True)
        .join(Field, Field.id == EntryValue.field_id, isouter=True)
        .where(Entry.category_id == category_id)
    )

    entry_dates: set[date] = set()
    relapse_dates: set[date] = set()
    for entry_id, entry_date, value, field_id, field_type in result.all():
        entry_dates.add(entry_date)
        if field_type is not None and is_relapse_value(
            field_type, value, field_id=field_id, entry_id=entry_id
        ):
            relapse_dates.add(entry_date)

    return compute_streak(
        entry_dates, relapse_dates, today or datetime.now(timezone.utc).date()
    )
