# [review:need-review] PHASE-01/24-ai-insights-endpoint-button, PHASE-03/107
# summary: builds the LLM context for a period — table aggregates + journal texts
# summary: the period now ends on today_local(), not on the server's calendar date
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import category as category_crud
from app.crud import journal as journal_crud
from app.crud import table as table_crud

# Upper bound of journal entries fed into the prompt (context size guard).
MAX_JOURNAL_ENTRIES = 200


async def build_period_context(db: AsyncSession, period_days: int) -> str:
    """
    Build the textual context for the insight prompt over the trailing period.

    Combines the aggregated table view (per-day category/field values) with
    journal entries (title, mood, tags, content) for [today - period_days + 1,
    today]. The output is plain text consumed by the LLM only — it is never
    logged.
    """
    date_to = today_local()
    date_from = date_to - timedelta(days=period_days - 1)

    lines: list[str] = [
        f"Period: last {period_days} days ({date_from.isoformat()} to {date_to.isoformat()})",
        "",
    ]

    lines.extend(await _table_section(db, date_from, date_to))
    lines.append("")
    lines.extend(await _journal_section(db, date_from, date_to))

    return "\n".join(lines)


async def _table_section(db: AsyncSession, date_from: date, date_to: date) -> list[str]:
    """Per-day aggregated field values, with category/field names resolved."""
    categories = await category_crud.get_categories(db, limit=None, active_only=True)
    category_names = {c.id: c.name for c in categories}
    field_names = {f.id: f.name for c in categories for f in c.fields}

    table = await table_crud.get_table(db, date_from=date_from, date_to=date_to)

    lines = ["## Tracked data (per-day aggregates)"]
    has_data = False
    for day in table.days:
        if not day.cells:
            continue
        has_data = True
        lines.append(f"### {day.date.isoformat()}")
        for cell in day.cells:
            category = category_names.get(
                cell.category_id, f"category {cell.category_id}"
            )
            field = field_names.get(cell.field_id, f"field {cell.field_id}")
            lines.append(f"- {category} / {field}: {cell.aggregated_value}")
    if not has_data:
        lines.append("(no tracked entries in this period)")
    return lines


async def _journal_section(
    db: AsyncSession, date_from: date, date_to: date
) -> list[str]:
    """Journal entries with title, mood, tags and full text."""
    entries, _total = await journal_crud.get_journal_entries(
        db,
        limit=MAX_JOURNAL_ENTRIES,
        start_date=date_from,
        end_date=date_to,
    )

    lines = ["## Journal entries"]
    if not entries:
        lines.append("(no journal entries in this period)")
        return lines
    for entry in entries:
        header = f"### {entry.entry_date.isoformat()}"
        if entry.title:
            header += f" — {entry.title}"
        lines.append(header)
        if entry.mood:
            lines.append(f"Mood: {entry.mood}")
        if entry.tags:
            lines.append(f"Tags: {entry.tags}")
        lines.append(entry.content)
    return lines
