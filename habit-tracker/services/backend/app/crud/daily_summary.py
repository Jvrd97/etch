# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: id-only semantic validation of day metrics + all-or-nothing apply of metrics and the day's journal text, deduped by an applied_daily_summaries row keyed on Idempotency-Key
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import journal as journal_crud
from app.crud.values import format_number
from app.models import AppliedDailySummary, Category, Entry, EntryValue
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


def entry_idempotency_key(idempotency_key: str, category_id: int) -> str:
    """
    The key stored on the entry a day's apply creates for `category_id`.

    One apply creates one entry per category, but `entries.idempotency_key` is
    unique, so a single client key cannot sit on all of them. Widening it by the
    category id gives every entry its own key. It is no longer what recognises a
    replay — `applied_daily_summaries` is — but it still makes each entry
    individually undoubleable, which is what turns a lost race into an
    `IntegrityError` rather than a duplicate row.
    """
    return f"{idempotency_key}:{category_id}"


async def find_applied_summary(
    db: AsyncSession, request: DailySummaryApplyRequest, idempotency_key: str
) -> DailySummaryApplyResponse | None:
    """
    The result of an earlier apply under this key, if it already happened.

    The key is looked up on `applied_daily_summaries`, not on the entries: the
    row exists whatever the apply wrote, so a day that was nothing but text is
    recognised as a replay too. That is the whole point — a double-click on
    "Записать" must not stack the retelling onto itself, and until the row
    existed a journal-only apply had nothing to be recognised by.

    Nothing is written here, including the day's text.

    What the replay carries is still checked against what the original wrote.
    A request that asks for more than the receipt records is not a replay: the
    user checked one more box, switched the journal on, or moved to the next
    day and pressed the same button. Answering 200 would drop that addition
    silently and for good, because the key can never write it afterwards
    either. All three — a new date, a new metric, a journal where the original
    wrote none — are conflicts, and the client is told so.
    """
    row = (
        (
            await db.execute(
                select(AppliedDailySummary).where(
                    AppliedDailySummary.idempotency_key == idempotency_key
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None

    if row.entry_date != request.entry_date:
        raise DailySummaryApplyError(
            409,
            "this Idempotency-Key already applied another date; use a new key",
        )

    await _assert_metrics_already_written(db, request, idempotency_key)

    if request.journal is not None and row.journal_entry_id is None:
        raise DailySummaryApplyError(
            409,
            "this Idempotency-Key already applied a day without a journal; "
            "use a new key",
        )

    return DailySummaryApplyResponse(
        entry_ids=list(row.entry_ids),
        journal_entry_id=row.journal_entry_id,
    )


async def _assert_metrics_already_written(
    db: AsyncSession, request: DailySummaryApplyRequest, idempotency_key: str
) -> None:
    """Raise unless every metric of the replay was written by the original apply."""
    wanted = {
        entry_idempotency_key(idempotency_key, op.category_id) for op in request.metrics
    }
    if not wanted:
        return

    found = set(
        (
            await db.execute(
                select(Entry.idempotency_key).where(Entry.idempotency_key.in_(wanted))
            )
        )
        .scalars()
        .all()
    )
    if wanted <= found:
        return

    missing_categories = sorted(
        {
            op.category_id
            for op in request.metrics
            if entry_idempotency_key(idempotency_key, op.category_id) not in found
        }
    )
    raise DailySummaryApplyError(
        409,
        "this Idempotency-Key already applied a day without metrics for "
        f"category_id(s) {missing_categories}; use a new key to write them",
    )


async def apply_daily_summary(
    db: AsyncSession,
    request: DailySummaryApplyRequest,
    categories: list[Category],
    idempotency_key: str | None = None,
) -> DailySummaryApplyResponse:
    """
    Write the day in one transaction: every metric, the day's text, or nothing.

    Metrics of the same category share one entry for the date, which is how a
    day is shaped in the tracker: one sport record carrying push-ups and pull-ups
    rather than one record per number. The journal text goes in last and under
    the same transaction, so a failure there takes the numbers back out with it —
    a day whose metrics landed but whose story did not is exactly the state
    nobody could reconstruct later.

    A rejected metric aborts the whole apply and rolls back what was already
    flushed. That is what makes a retry after a *failure* safe: nothing was
    written, so resending the same day cannot double it. A repeat after
    *success* is recognised by `find_applied_summary`, which reads the
    `applied_daily_summaries` row this function writes inside the very same
    transaction — so the receipt of an apply exists exactly when the apply did.
    """
    categories_by_id = {category.id: category for category in categories}
    entry_by_category: dict[int, Entry] = {}
    journal_entry_id: int | None = None

    try:
        for op in request.metrics:
            problem = _validate_one(op, categories_by_id)
            if problem is not None:
                raise DailySummaryApplyError(400, problem)

            entry = entry_by_category.get(op.category_id)
            if entry is None:
                entry = Entry(
                    category_id=op.category_id,
                    entry_date=request.entry_date,
                    idempotency_key=(
                        entry_idempotency_key(idempotency_key, op.category_id)
                        if idempotency_key is not None
                        else None
                    ),
                )
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

        if request.journal is not None:
            op_journal = request.journal
            # The mode goes through as asked. `write_day_journal` resolves the
            # day's entry itself and already downgrades `create` on a day that
            # has text to an append, so re-reading the day here would only buy
            # a second copy of that rule and an extra round-trip.
            written = await journal_crud.write_day_journal(
                db,
                request.entry_date,
                mode=op_journal.mode,
                title=op_journal.title,
                content=op_journal.content,
                mood=op_journal.mood,
                tags=op_journal.tags,
            )
            journal_entry_id = written.id

        entry_ids = [entry.id for entry in entry_by_category.values()]

        if idempotency_key is not None:
            # The receipt, written under the same transaction as everything it
            # describes: it is the only thing a journal-only apply leaves for a
            # replay to be recognised by, and its unique key is what makes two
            # simultaneous applies of one day collide instead of both landing.
            db.add(
                AppliedDailySummary(
                    idempotency_key=idempotency_key,
                    entry_date=request.entry_date,
                    entry_ids=entry_ids,
                    journal_entry_id=journal_entry_id,
                )
            )

        await db.flush()
        await db.commit()
    except Exception:
        # Undo the flushed rows here rather than leaning on the caller: get_db
        # does roll back on a propagating exception, but a caller that catches
        # DailySummaryApplyError and keeps using the session (the API layer
        # turns it into a 400 response) would otherwise carry a poisoned
        # transaction. Every failure is rolled back, not just the validation
        # one, because atomicity of the metrics and the day's text has to hold
        # whatever broke — the exception itself is re-raised untouched.
        await db.rollback()
        raise

    return DailySummaryApplyResponse(
        entry_ids=entry_ids,
        journal_entry_id=journal_entry_id,
    )
