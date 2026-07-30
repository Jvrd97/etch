# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: id-only semantic validation of day metrics + all-or-nothing apply into entries
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.values import format_number
from app.models import Category, Entry, EntryValue
from app.models.field import FieldType
from app.schemas.daily_summary import (
    DailySummaryApplyRequest,
    DailySummaryApplyResponse,
    LogMetricOp,
)

# Discriminator written on every transcript this feature stores.
DAILY_SUMMARY_SOURCE = "daily_summary"

# The field types a numeric metric can be written into. A duration is whole
# seconds, so a number lands in it unchanged; everything else (text, select,
# boolean, the date/time trio) has no meaning for a bare number.
NUMERIC_FIELD_TYPES: frozenset[FieldType] = frozenset(
    {FieldType.NUMBER, FieldType.DURATION}
)


class DailySummaryApplyError(Exception):
    """A metric was rejected; carries the HTTP status and detail for the API layer.

    Atomicity is why this exists: any rejection rolls back everything the apply
    had flushed, so a partially written day is not a reachable state.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _validate_one(op: LogMetricOp, categories_by_id: dict[int, Category]) -> str | None:
    """The reason `op` cannot be written, or None when it can.

    Every message is built from ids alone. The wording a metric was read from is
    user data and must not travel into an error string, which is shown, returned
    and (for the LLM repair pass) fed back into a prompt.
    """
    category = categories_by_id.get(op.category_id)
    if category is None:
        return f"unknown category_id {op.category_id}"

    field = next((f for f in category.fields if f.id == op.field_id), None)
    if field is None:
        return f"field_id {op.field_id} does not belong to category_id {op.category_id}"

    if field.field_type not in NUMERIC_FIELD_TYPES:
        return (
            f"field_id {op.field_id} has field_type "
            f"{field.field_type.value!r}, which holds no numeric value"
        )
    return None


def validate_metric_ops(
    ops: list[LogMetricOp], categories: list[Category]
) -> list[str]:
    """
    Every reason the metrics cannot be written, so one repair pass sees them all.

    Semantic, not formal: Pydantic already knows the shape. This checks that the
    ids point somewhere real — the category exists, the field is that category's
    own, and the field can hold a number.
    """
    categories_by_id = {category.id: category for category in categories}
    errors = [_validate_one(op, categories_by_id) for op in ops]
    return [error for error in errors if error is not None]


async def apply_daily_summary(
    db: AsyncSession, request: DailySummaryApplyRequest, categories: list[Category]
) -> DailySummaryApplyResponse:
    """
    Write the day's metrics in one transaction: all of them or none.

    Metrics of the same category share one entry for the date, which is how a
    day is shaped in the tracker: one sport record carrying push-ups and pull-ups
    rather than one record per number.

    A rejected metric aborts the whole apply and rolls back what was already
    flushed. That is what makes a retry after a *failure* safe without
    idempotency keys: nothing was written, so resending the same day cannot
    double it.

    A repeat of a *successful* apply is a different matter and is not guarded
    here: this endpoint takes no `Idempotency-Key` (unlike `POST /entries`), so
    applying the same plan twice writes two sets of entries that the table then
    sums. Accepted risk for this slice — the cost is deleting the extra entries
    by hand — and closed in #74 along with the journal operation.
    """
    categories_by_id = {category.id: category for category in categories}
    entry_by_category: dict[int, Entry] = {}

    try:
        for op in request.metrics:
            problem = _validate_one(op, categories_by_id)
            if problem is not None:
                raise DailySummaryApplyError(400, problem)

            entry = entry_by_category.get(op.category_id)
            if entry is None:
                entry = Entry(category_id=op.category_id, entry_date=request.entry_date)
                db.add(entry)
                await db.flush()
                entry_by_category[op.category_id] = entry

            db.add(
                EntryValue(
                    entry_id=entry.id,
                    field_id=op.field_id,
                    value=format_number(op.value),
                )
            )
        await db.flush()
        await db.commit()
    except DailySummaryApplyError:
        # Undo the flushed rows here rather than leaning on the caller: get_db
        # does roll back on a propagating exception, but a caller that catches
        # DailySummaryApplyError and keeps using the session (the API layer
        # turns it into a 400 response) would otherwise carry a poisoned
        # transaction. Rolling back where the failure is known keeps this
        # function safe to call from anywhere.
        await db.rollback()
        raise

    return DailySummaryApplyResponse(
        entry_ids=[entry.id for entry in entry_by_category.values()]
    )
