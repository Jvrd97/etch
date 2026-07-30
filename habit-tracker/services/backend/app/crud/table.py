# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: table view aggregation; DURATION sums like NUMBER (elapsed seconds), the sum is rendered by the shared format_number
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import cast

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import category as category_crud
from app.crud.values import format_number, is_true_value, parse_number
from app.models import Category, Entry, EntryValue, Field
from app.models.field import FieldType
from app.schemas.category import CategoryDisplayMode
from app.schemas.table import TableCategoryMeta, TableCell, TableDay, TableResponse


@dataclass
class _CellAccumulator:
    """Mutable aggregation state for one (day, category, field) cell."""

    field_type: FieldType
    number_sum: float = 0.0
    has_number: bool = False
    any_true: bool = False
    last_value: str | None = None
    entry_ids: set[int] = field(default_factory=set)

    def add(self, entry_id: int, field_id: int, value: str | None) -> None:
        self.entry_ids.add(entry_id)
        if value is None:
            return
        # DURATION is elapsed seconds — numerically it aggregates exactly like
        # NUMBER (sum over the day); only the client formats it as h/m.
        if self.field_type in (FieldType.NUMBER, FieldType.DURATION):
            number = parse_number(value, field_id=field_id, entry_id=entry_id)
            if number is not None:
                self.number_sum += number
                self.has_number = True
        elif self.field_type == FieldType.BOOLEAN:
            self.any_true = self.any_true or is_true_value(value)
        else:
            self.last_value = value  # rows arrive ordered by created_at, id

    def aggregated_value(self) -> str | None:
        if self.field_type in (FieldType.NUMBER, FieldType.DURATION):
            if not self.has_number:
                return None
            return format_number(self.number_sum)
        if self.field_type == FieldType.BOOLEAN:
            return "true" if self.any_true else "false"
        return self.last_value


def _category_meta(category: Category) -> TableCategoryMeta:
    """Build table metadata for a category; primary field = first by (order, id)."""
    primary = min(category.fields, key=lambda f: (f.order, f.id), default=None)
    return TableCategoryMeta(
        id=category.id,
        name=category.name,
        # DB column is a plain str constrained to the same values as the Literal
        display_mode=cast(CategoryDisplayMode, category.display_mode),
        group=category.group,
        primary_field_id=primary.id if primary is not None else None,
        primary_field_name=primary.name if primary is not None else None,
        primary_field_type=primary.field_type.value if primary is not None else None,
    )


async def _get_category_metas(db: AsyncSession) -> list[TableCategoryMeta]:
    """Active categories with grouping metadata, ordered by name."""
    categories = await category_crud.get_categories(db, limit=None, active_only=True)
    return [_category_meta(category) for category in categories]


async def get_table(
    db: AsyncSession,
    date_from: date,
    date_to: date,
) -> TableResponse:
    """
    Build the table view for [date_from, date_to] (inclusive).

    The response carries category metadata (group, display_mode, primary
    field = first field by order) for tab/column layout on the client.
    Every day of the range is present in the response; days without
    entries have an empty cells list. Aggregation per (category, field):
    number -> sum, boolean -> any, text/select/date/etc -> last by created_at.
    """
    result = await db.execute(
        select(
            Entry.entry_date,
            Entry.category_id,
            Entry.id,
            EntryValue.field_id,
            EntryValue.value,
            Field.field_type,
        )
        .join(EntryValue, EntryValue.entry_id == Entry.id)
        .join(Field, Field.id == EntryValue.field_id)
        .where(
            and_(
                Entry.entry_date >= date_from,
                Entry.entry_date <= date_to,
            )
        )
        .order_by(Entry.created_at.asc(), Entry.id.asc())
    )

    cells: dict[date, dict[tuple[int, int], _CellAccumulator]] = {}
    for entry_date, category_id, entry_id, field_id, value, field_type in result.all():
        day_cells = cells.setdefault(entry_date, {})
        key = (category_id, field_id)
        accumulator = day_cells.get(key)
        if accumulator is None:
            accumulator = _CellAccumulator(field_type=field_type)
            day_cells[key] = accumulator
        accumulator.add(entry_id, field_id, value)

    days: list[TableDay] = []
    current = date_from
    while current <= date_to:
        day_cells = cells.get(current, {})
        days.append(
            TableDay(
                date=current,
                cells=[
                    TableCell(
                        category_id=category_id,
                        field_id=field_id,
                        aggregated_value=accumulator.aggregated_value(),
                        entry_count=len(accumulator.entry_ids),
                    )
                    for (category_id, field_id), accumulator in sorted(
                        day_cells.items()
                    )
                ],
            )
        )
        current += timedelta(days=1)

    return TableResponse(categories=await _get_category_metas(db), days=days)
