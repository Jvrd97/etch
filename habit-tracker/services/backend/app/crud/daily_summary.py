# [review:need-review] PHASE-01/75-daily-summary-checklist
# summary: id-only semantic validation of day metrics and checklist ticks + all-or-nothing apply of metrics, ticks (merged onto the day's current state, never replacing it) and the day's journal text, deduped by an applied_daily_summaries row keyed on Idempotency-Key, which records the exact metric pairs it wrote
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import entry as entry_crud
from app.crud import journal as journal_crud
from app.crud.category import CHECKLIST_DISPLAY_MODE
from app.crud.values import BOOLEAN_TRUE_VALUES, format_number
from app.models import AppliedDailySummary, Category, Entry, EntryValue, Field
from app.models.field import FieldType
from app.schemas.daily_summary import (
    CheckOp,
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


def _validate_one_check(
    op: CheckOp, categories_by_id: dict[int, Category]
) -> str | None:
    """The reason `op` cannot tick a box, or None when it can.

    Three checks: the category exists, its `display_mode` is `checklist`, and
    the field is that category's own and boolean. Only the middle one is shared
    with `PUT /entries/checklist` (`app/api/entries.py`), which validates the
    category and nothing else — it takes a whole map from a human-driven UI that
    can only offer the day's real boxes, while a plan's ids come from a model
    and may point anywhere. The unknown category is a 422 here where the
    endpoint answers 404: a plan is one request writing many things, and "this
    op is unusable" is not "the URL you asked for does not exist".

    Built from ids alone, like every message in this module.
    """
    category = categories_by_id.get(op.category_id)
    if category is None:
        return f"unknown category_id {op.category_id}"

    if category.display_mode != CHECKLIST_DISPLAY_MODE:
        return (
            f"category_id {op.category_id} is not a checklist category "
            f"(display_mode={category.display_mode!r})"
        )

    field = next((f for f in category.fields if f.id == op.field_id), None)
    if field is None:
        return f"field_id {op.field_id} does not belong to category_id {op.category_id}"

    if field.field_type is not FieldType.BOOLEAN:
        return (
            f"field_id {op.field_id} has field_type "
            f"{field.field_type.value!r}, which is not a checkbox"
        )
    return None


def validate_check_ops(ops: list[CheckOp], categories: list[Category]) -> list[str]:
    """Every reason the ticks cannot be written, so one repair pass sees them all."""
    categories_by_id = {category.id: category for category in categories}
    errors = [_validate_one_check(op, categories_by_id) for op in ops]
    return [error for error in errors if error is not None]


def merge_checklist_marks(
    current: dict[int, bool], marked_field_ids: Iterable[int]
) -> dict[int, bool]:
    """
    The day's checklist map after the plan's ticks, with everything else intact.

    This function is the whole safety of the slice, which is why it is pure and
    tested on its own. `PUT /entries/checklist` takes a full map, so the plan
    cannot be handed the map directly: a retelling that never mentioned the
    vitamins would arrive as an absence and untick them. Instead the current
    state is the base and the plan may only raise entries of it — the result can
    differ from `current` in one direction only.
    """
    merged = dict(current)
    for field_id in marked_field_ids:
        merged[field_id] = True
    return merged


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
    either. All four — a new date, a new metric, a tick that does not stand,
    and a journal where the original wrote none — are conflicts, and the client
    is told so.
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

    _assert_metrics_already_written(request, row)
    await _assert_checks_already_written(db, request)

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


def _assert_metrics_already_written(
    request: DailySummaryApplyRequest,
    row: AppliedDailySummary,
) -> None:
    """Raise unless every metric of the replay was written by the original apply.

    The evidence is the receipt's own `metric_pairs` — the list this key wrote,
    recorded at the moment it wrote it. Nothing about the entries can stand in
    for it. Their idempotency keys cannot: an apply may reuse a checklist
    category's existing entry for the day (see `_entry_for_metrics`), and such
    an entry carries whatever key — or none — it was created with. Their
    *contents* cannot either, which is the subtler trap: a value somebody typed
    into that field by hand before the apply is indistinguishable from one the
    apply wrote, so reading the entries would let a replay carrying a brand-new
    metric pass as an exact repeat and answer 200 while writing nothing.

    A receipt from before `metric_pairs` existed carries an empty list, so any
    replay of such a key with metrics is a conflict. That is the direction that
    loses nothing: the client is told to use a new key, and the metric gets
    written.
    """
    wanted = {(op.category_id, op.field_id) for op in request.metrics}
    if not wanted:
        return

    # JSON has no tuples: the pairs come back as two-element lists.
    written = {(category_id, field_id) for category_id, field_id in row.metric_pairs}
    if wanted <= written:
        return

    missing_categories = sorted({category_id for category_id, _ in wanted - written})
    raise DailySummaryApplyError(
        409,
        "this Idempotency-Key already applied a day without metrics for "
        f"category_id(s) {missing_categories}; use a new key to write them",
    )


async def _assert_checks_already_written(
    db: AsyncSession, request: DailySummaryApplyRequest
) -> None:
    """Raise unless every tick of the replay already stands for that date.

    The ticks are part of the idempotency contract, not a free rider on it: a
    key replayed with one more box is the same "new intent, not a replay" case
    as one replayed with an extra metric. Answering 200 would report the box as
    ticked while nothing was written, and the key can never write it afterwards
    either.

    Evidence is the day's current state rather than the receipt, because that
    is what a tick asserts: the box is up for this date. A box the user ticked
    by hand in between therefore satisfies the replay — nothing is lost, which
    is the only thing this guard exists to prevent.
    """
    if not request.checklist:
        return

    by_category: dict[int, set[int]] = {}
    for op in request.checklist:
        by_category.setdefault(op.category_id, set()).add(op.field_id)

    ticked = await _ticked_boxes(db, list(by_category), request.entry_date)

    missing_categories = [
        category_id
        for category_id, field_ids in by_category.items()
        if not all((category_id, field_id) in ticked for field_id in field_ids)
    ]
    if not missing_categories:
        return

    raise DailySummaryApplyError(
        409,
        "this Idempotency-Key already applied a day without ticks for "
        f"category_id(s) {sorted(missing_categories)}; use a new key to write them",
    )


async def _ticked_boxes(
    db: AsyncSession, category_ids: list[int], entry_date: date
) -> set[tuple[int, int]]:
    """Every `(category_id, field_id)` standing ticked on `entry_date`, in one query.

    The per-category read this replaces (`get_checklist_state` in a loop) cost a
    round-trip per category of the plan, and a retelling naming five checklists
    is an ordinary retelling. The subquery picks the same row
    `entry_crud.checklist_entry_id` would — `min(id)` per category is
    `order_by(id).limit(1)` said set-wise — so "the day's entry" stays one rule
    even though this is the one place that resolves it for many days' categories
    at once.

    Truthiness is `app.crud.values.BOOLEAN_TRUE_VALUES` said in SQL rather than
    in Python, because the filter has to run in the database. It must keep
    agreeing with `is_true_value`: a box stored as "1" read as empty here would
    make the replay guard disagree with the apply that wrote it.
    """
    if not category_ids:
        return set()

    canonical_entry_ids = (
        select(func.min(Entry.id))
        .where(
            Entry.category_id.in_(category_ids),
            Entry.entry_date == entry_date,
        )
        .group_by(Entry.category_id)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(Entry.category_id, EntryValue.field_id)
        .join(EntryValue, EntryValue.entry_id == Entry.id)
        .join(Field, EntryValue.field_id == Field.id)
        .where(
            Entry.id.in_(canonical_entry_ids),
            Field.field_type == FieldType.BOOLEAN,
            func.lower(func.trim(EntryValue.value)).in_(tuple(BOOLEAN_TRUE_VALUES)),
        )
    )
    return {(category_id, field_id) for category_id, field_id in rows.all()}


def _checks_by_category(
    ops: list[CheckOp], categories_by_id: dict[int, Category]
) -> dict[int, list[int]]:
    """Validated ticks grouped into one write per category; raises on the first bad op.

    Grouping is not an optimisation — the checklist endpoint writes a whole
    category at a time, so two boxes of one category ticked by one retelling
    have to meet in a single map before anything is written, or the second write
    would be built on a state read before the first.
    """
    grouped: dict[int, list[int]] = {}
    for op in ops:
        problem = _validate_one_check(op, categories_by_id)
        if problem is not None:
            # 422, not the metrics' 400: this is the status PUT /entries/checklist
            # already answers a non-checklist category with, and the same mistake
            # arriving through the day plan is not a different mistake.
            raise DailySummaryApplyError(422, problem)
        grouped.setdefault(op.category_id, []).append(op.field_id)
    return grouped


async def _entry_for_metrics(
    db: AsyncSession,
    category: Category,
    entry_date: date,
    idempotency_key: str | None,
) -> Entry:
    """The entry a metric of `category` goes into for `entry_date`.

    A form category gets a fresh entry every time, which is what a tracker
    record is: two applies of one day are two records, and #39's key — not the
    absence of a second row — is what stops a replay from doubling them.

    A checklist category is the exception, and it is a contract rather than an
    optimisation: `upsert_checklist_values` guarantees exactly one entry per
    (category, date), so a checklist that also carries a number would otherwise
    end the day with two rows — one holding the number, one holding the boxes —
    and every reader of the day would have to guess which is the day. Which row
    that is comes from `entry_crud.checklist_entry_id`, the same call the tick
    reader and the tick writer make: three places resolving "the day's entry"
    with three copies of one `order_by(...).limit(1)` is three places to get it
    wrong.
    """
    if category.display_mode == CHECKLIST_DISPLAY_MODE:
        existing_id = await entry_crud.checklist_entry_id(db, category.id, entry_date)
        if existing_id is not None:
            return (
                (
                    await db.execute(
                        select(Entry)
                        .options(selectinload(Entry.values))
                        .where(Entry.id == existing_id)
                    )
                )
                .scalars()
                .one()
            )

    entry = Entry(
        category_id=category.id,
        entry_date=entry_date,
        idempotency_key=(
            entry_idempotency_key(idempotency_key, category.id)
            if idempotency_key is not None
            else None
        ),
    )
    # Marks the collection loaded, so reading it after the flush below cannot
    # fall into a lazy load — which under an async session is an error, not a
    # slow query.
    entry.values = []
    db.add(entry)
    await db.flush()
    return entry


def _write_metric_value(
    db: AsyncSession, entry: Entry, field_id: int, value: str
) -> None:
    """Put `value` into `entry`'s field, replacing what is there rather than stacking.

    Only a reused entry can already hold the field (a freshly created one holds
    nothing), and there a second row for the same field would be two answers to
    one question with no rule for which wins.
    """
    known = next((v for v in entry.values if v.field_id == field_id), None)
    if known is not None:
        known.value = value
        return
    new_value = EntryValue(entry_id=entry.id, field_id=field_id, value=value)
    entry.values.append(new_value)
    db.add(new_value)


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
    checklist_entry_ids: list[int] = []
    # What the receipt will claim this key wrote. Collected as it happens rather
    # than derived afterwards: a reused entry cannot tell its own values apart
    # from ones written before this apply.
    metric_pairs: list[list[int]] = []
    journal_entry_id: int | None = None

    try:
        for op in request.metrics:
            problem = _validate_one(op, categories_by_id)
            if problem is not None:
                raise DailySummaryApplyError(400, problem)

            entry = entry_by_category.get(op.category_id)
            if entry is None:
                entry = await _entry_for_metrics(
                    db,
                    categories_by_id[op.category_id],
                    request.entry_date,
                    idempotency_key,
                )
                entry_by_category[op.category_id] = entry

            _write_metric_value(db, entry, op.field_id, format_number(op.value))
            pair = [op.category_id, op.field_id]
            if pair not in metric_pairs:
                metric_pairs.append(pair)

        for category_id, field_ids in _checks_by_category(
            request.checklist, categories_by_id
        ).items():
            # The day's current ticks are read here, on the server, inside the
            # transaction — not carried in by the client. The preview may have
            # been open for an hour while a box was ticked by hand on Today, and
            # a map assembled from what the client last saw would quietly undo
            # it. Reading it here also means the merge sees the metrics' own
            # entry when a category has both.
            #
            # Accepted risk, deliberately not locked: a hand tick committed
            # between this read and the write below is lost. The window is the
            # few milliseconds of one apply, the collision needs the same
            # category on the same date from two devices at once, and the loss
            # is one box a user can see is unticked and tick again. A
            # `SELECT ... FOR UPDATE` on the day's entry would close it at the
            # cost of holding a row lock across the whole apply — including the
            # journal write and the LLM-free but still multi-statement tail —
            # which trades a rare lost tick for a common lock wait. Revisit if
            # the app ever gains concurrent writers per user (background sync,
            # a second client applying days automatically).
            current = await entry_crud.get_checklist_state(
                db, category_id, request.entry_date
            )
            checklist_entry = await entry_crud.upsert_checklist_values(
                db,
                category_id,
                request.entry_date,
                merge_checklist_marks(current, field_ids),
            )
            checklist_entry_ids.append(checklist_entry.id)

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

        # Every entry the day touched, metrics first, each id once. A category
        # that is both a checklist and a metric holder is written through twice
        # — once for the number, once for the boxes — but `_entry_for_metrics`
        # points both writes at the day's single entry, so the same id comes
        # back from both loops and a receipt listing it twice would be a lie
        # about what happened.
        entry_ids = [entry.id for entry in entry_by_category.values()]
        entry_ids += [eid for eid in checklist_entry_ids if eid not in entry_ids]

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
                    metric_pairs=metric_pairs,
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
