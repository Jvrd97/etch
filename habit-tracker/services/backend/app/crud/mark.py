# [review:need-review] PHASE-03/88
# summary: mark persistence — an upsert that lets the last of two tabs win, an append-only event beside every change of state, and the snapshot/restore that carries marks across a plan being rewritten
"""
Database access for the marks of a day.

Three decisions here are the whole point of the ticket.

**A write is an upsert, not a read-modify-write.** `plan_server.py` had to
refuse "empty over non-empty" (409) and re-read the page on
`visibilitychange`, because it wrote marks into a file with no transaction and
two tabs could silently overwrite each other. Here the state a client names
lands with `ON CONFLICT (item_id) DO UPDATE`, the second write wins, and
`updated_at` records which write that was. Neither patch is reproduced.

**Every change of state also appends a row.** The mark is one mutable row —
that is what makes "what is the state of this line" a single answer — so the
history has to live somewhere, and since the `.html` left git there is no
version control under it any more. `plan_mark_event` is written in the same
transaction as the mark: a state that changed without a recorded transition is
not a state anybody can explain later.

**Marks survive a plan being replaced.** `#87` stores a plan by replacing it
whole, and a re-sent plan that reuses an item's uuid means "the same line, new
text". `snapshot_marks`/`restore_marks` carry the rows across that delete —
which is why editing the wording of a task at 14:00 does not un-tick it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import Select, case, delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.day.marks import TaskCounts, count_tasks
from app.models.mark import PlanMark, PlanMarkEvent
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.schemas.mark import MarkResponse, TaskCountsResponse

__all__ = [
    "CarriedMark",
    "day_item",
    "list_marks",
    "restore_marks",
    "set_mark",
    "snapshot_marks",
    "task_counts",
    "to_counts_response",
    "to_response",
]


@dataclass(frozen=True)
class CarriedMark:
    """
    A mark taken off an item that is about to be deleted and re-inserted.

    Plain values rather than the ORM object: the rows are read before the plan
    is deleted and written after it is rebuilt, and an ORM instance that lived
    across that delete would still be in the identity map when a row with the
    same primary key is inserted again.
    """

    item_id: uuid.UUID
    state: str
    note: str | None
    marked_at: datetime
    updated_at: datetime
    source: str


def _now() -> datetime:
    """An aware moment, as every timestamptz in this service is written."""
    return datetime.now(timezone.utc)


def _items_of_day(on: date) -> Select[tuple[uuid.UUID]]:
    """Ids of every item belonging to the plan of `on`."""
    return (
        select(PlanItem.id)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on)
    )


async def day_item(db: AsyncSession, on: date, item_id: uuid.UUID) -> PlanItem | None:
    """
    The item `item_id`, but only if it belongs to the plan of `on`.

    Scoped by date rather than looked up by id alone: a mark is addressed as
    "this line of this day", and an id from another day arriving on this URL is
    a mistake worth a 404 rather than a mark quietly written into a day the
    caller was not looking at.
    """
    result = await db.execute(
        select(PlanItem)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def list_marks(db: AsyncSession, on: date) -> list[PlanMark]:
    """Every mark of the plan of `on`, in no particular order."""
    result = await db.execute(
        select(PlanMark).where(PlanMark.item_id.in_(_items_of_day(on)))
    )
    return list(result.scalars().all())


async def get_mark(db: AsyncSession, item_id: uuid.UUID) -> PlanMark | None:
    """The mark of one item, or None when it has none."""
    result = await db.execute(select(PlanMark).where(PlanMark.item_id == item_id))
    return result.scalar_one_or_none()


def _append_event(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    on: date,
    from_state: str | None,
    to_state: str | None,
    note: str | None,
    source: str,
    at: datetime,
) -> None:
    """Record one transition. Never called when nothing changed."""
    db.add(
        PlanMarkEvent(
            id=uuid.uuid4(),
            item_id=item_id,
            day_date=on,
            from_state=from_state,
            to_state=to_state,
            note=note,
            source=source,
            at=at,
        )
    )


async def set_mark(
    db: AsyncSession,
    on: date,
    item_id: uuid.UUID,
    *,
    state: str | None,
    note: str | None,
    source: str,
) -> PlanMark | None:
    """
    Give `item_id` the mark `state`, or take its mark off when `state` is None.

    Returns the stored mark, or None when the item now has none. The event is
    appended only when the state actually moved: re-sending the same tick is
    the normal consequence of two tabs and of a retried request, and a log in
    which half the rows are "nothing happened" is not a log anybody reads.
    A note edited without the state moving updates the row and its `updated_at`
    and is not a transition.
    """
    existing = await get_mark(db, item_id)
    previous = existing.state if existing is not None else None
    at = _now()

    if state is None:
        if existing is not None:
            await db.execute(delete(PlanMark).where(PlanMark.item_id == item_id))
            _append_event(
                db,
                item_id=item_id,
                on=on,
                from_state=previous,
                to_state=None,
                note=note if note is not None else existing.note,
                source=source,
                at=at,
            )
        await db.flush()
        return None

    stored = pg_insert(PlanMark).values(
        item_id=item_id,
        state=state,
        note=note,
        source=source,
        marked_at=at,
        updated_at=at,
    )
    await db.execute(
        stored.on_conflict_do_update(
            index_elements=[PlanMark.item_id],
            set_={
                "state": stored.excluded.state,
                "note": stored.excluded.note,
                "source": stored.excluded.source,
                "updated_at": stored.excluded.updated_at,
                # Moves with the state, stays put when only the note changed:
                # "отмечено в 14:05" is about the tick, not about the sentence
                # somebody appended to it at 23:00.
                "marked_at": case(
                    (
                        PlanMark.state.is_distinct_from(stored.excluded.state),
                        stored.excluded.marked_at,
                    ),
                    else_=PlanMark.marked_at,
                ),
            },
        )
    )

    if previous != state:
        _append_event(
            db,
            item_id=item_id,
            on=on,
            from_state=previous,
            to_state=state,
            note=note,
            source=source,
            at=at,
        )

    await db.flush()
    if existing is not None:
        await db.refresh(existing)
        return existing
    return await get_mark(db, item_id)


async def snapshot_marks(
    db: AsyncSession, item_ids: set[uuid.UUID]
) -> list[CarriedMark]:
    """
    The marks of `item_ids` as plain values, before the rows are deleted.

    Reads columns rather than entities on purpose — see `CarriedMark`.
    """
    if not item_ids:
        return []
    result = await db.execute(
        select(
            PlanMark.item_id,
            PlanMark.state,
            PlanMark.note,
            PlanMark.marked_at,
            PlanMark.updated_at,
            PlanMark.source,
        ).where(PlanMark.item_id.in_(item_ids))
    )
    return [
        CarriedMark(
            item_id=row.item_id,
            state=row.state,
            note=row.note,
            marked_at=row.marked_at,
            updated_at=row.updated_at,
            source=row.source,
        )
        for row in result
    ]


async def restore_marks(db: AsyncSession, carried: list[CarriedMark]) -> None:
    """
    Write carried marks back, timestamps and all.

    `updated_at` is restored rather than refreshed: rewriting the plan is not a
    change to the mark, and a reader comparing "when did I tick this" against
    "when was the plan last edited" has to be able to tell the two apart.
    """
    if not carried:
        return
    await db.execute(
        insert(PlanMark),
        [
            {
                "item_id": mark.item_id,
                "state": mark.state,
                "note": mark.note,
                "marked_at": mark.marked_at,
                "updated_at": mark.updated_at,
                "source": mark.source,
            }
            for mark in carried
        ],
    )
    await db.flush()


def task_counts(plan: DayPlan | None, marks: list[PlanMark]) -> TaskCounts:
    """
    The day's tasks split by what happened to them, marks included.

    A day with no plan counts zeroes rather than refusing to answer: the header
    of an empty day still has to say something, and "0 из 0" is true.
    """
    kinds = (
        {}
        if plan is None
        else {item.id: item.kind for section in plan.sections for item in section.items}
    )
    return count_tasks(kinds, {mark.item_id: mark.state for mark in marks})


def to_response(item_id: uuid.UUID, mark: PlanMark | None) -> MarkResponse:
    """One mark as the wire carries it; `state: null` when there is none."""
    if mark is None:
        return MarkResponse(item_id=item_id)
    return MarkResponse(
        item_id=mark.item_id,
        state=mark.state,
        note=mark.note,
        marked_at=mark.marked_at,
        updated_at=mark.updated_at,
        source=mark.source,
    )


def to_counts_response(counts: TaskCounts) -> TaskCountsResponse:
    """The counted tasks as the wire carries them."""
    return TaskCountsResponse(
        planned=counts.planned,
        done=counts.done,
        failed=counts.failed,
        skipped=counts.skipped,
        pending=counts.pending,
    )
