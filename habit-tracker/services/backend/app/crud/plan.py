# [review:need-review] PHASE-03/87
# summary: plan persistence — a document flattened and judged before a single row is written, the previous plan replaced whole in one transaction, and overlapping windows found by a self-join on `&&` rather than on render
"""
Database access for the plan of a day.

The order of operations here is the design, not an implementation detail.

**Flatten, then judge, then write.** The document is walked once into a flat
list of prepared rows — windows resolved against the day boundary, markdown
flattened, `ord` assigned from position — and only that list is handed to
`app.day.plan_validate`. Judging the JSON directly would mean the validator and
the writer each parse a window, and the day a plan is accepted with one reading
and stored with another is the day the constraint stops meaning anything.

**A plan replaces a plan.** A second `POST` on the same date deletes the old
rows and writes the new ones inside one transaction. Merging would leave the
caller unable to say what the plan *is* without replaying every edit, and
`day_plan.day_date` is unique precisely so that no code path can end up with
two.

**Overlaps are a query, not a render.** Two windows intersect if the database
says so — a self-join on `&&` over the GiST index on the generated `window`
column. The screen is then one consumer of that fact rather than its only
owner, and `#90`'s verdict can ask the same question without reimplementing it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.daytime import DayBoundary, current_boundary
from app.day.plan_validate import (
    ItemFacts,
    PlanRejected,
    parse_window,
    resolve_window,
    to_plain,
    validate_plan,
)
from app.models.day import DayRuleSet
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.schemas.plan import (
    PlanDocument,
    PlanItemIn,
    PlanItemResponse,
    PlanResponse,
    PlanSectionResponse,
    ScheduleEntry,
    ScheduleOverlap,
)

SECONDS_PER_MINUTE = 60

# Two windows overlap when the stored ranges intersect. `tstzrange` is half-open,
# so 09:00-10:00 and 10:00-11:00 touch without overlapping — which is the answer
# a reader wants, and the reason this is a range operator rather than a pair of
# comparisons somebody would have got wrong at the boundary. `left` is the item
# that starts earlier, so the pair reads in the order of the day.
OVERLAP_SQL = text(
    """
    SELECT
        a.id AS left_item_id,
        b.id AS right_item_id,
        EXTRACT(EPOCH FROM (
            upper(a.window * b.window) - lower(a.window * b.window)
        ))::bigint AS overlap_seconds
    FROM plan_item a
    JOIN plan_section sa ON sa.id = a.section_id
    JOIN plan_item b ON b.window && a.window
    JOIN plan_section sb ON sb.id = b.section_id
    WHERE sa.plan_id = :plan_id
      AND sb.plan_id = :plan_id
      AND (a.starts_at, a.id) < (b.starts_at, b.id)
    ORDER BY a.starts_at, b.starts_at
    """
)


@dataclass
class _PreparedItem:
    """
    One row as it will be written, with everything already decided.

    Carries its own `id` before the insert so that a child can name its parent
    without a second round trip, and so that a rejection can point at a line the
    caller sent rather than at a row that was never created.
    """

    id: uuid.UUID
    section_index: int
    parent_id: uuid.UUID | None
    ord: int
    source: PlanItemIn
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    text_plain: str = ""
    children: list[_PreparedItem] = field(default_factory=list)

    def facts(self) -> ItemFacts:
        """What `app.day.plan_validate` needs in order to judge this line."""
        return ItemFacts(
            kind=self.source.kind,
            rigidity=self.source.rigidity,
            code=self.source.code,
            text_plain=self.text_plain,
            has_window=self.starts_at is not None and self.ends_at is not None,
            has_criterion=bool(self.source.done_criterion),
            is_goal_linked=(
                self.source.quarter_goal_id is not None
                or bool(self.source.unlinked_reason)
            ),
        )


def _prepare_items(
    items: list[PlanItemIn],
    section_index: int,
    parent_id: uuid.UUID | None,
    on: date,
    boundary: DayBoundary,
    flat: list[_PreparedItem],
) -> list[_PreparedItem]:
    """
    Walk one level of the document, resolving every window as it goes.

    `ord` is the position in the list, per level: siblings are numbered among
    themselves, so inserting a step into a training block does not renumber the
    section below it.
    """
    prepared: list[_PreparedItem] = []
    for index, item in enumerate(items):
        row = _PreparedItem(
            id=uuid.uuid4(),
            section_index=section_index,
            parent_id=parent_id,
            ord=index,
            source=item,
            text_plain=to_plain(item.text_md),
        )
        if item.window is not None:
            start, end = parse_window(item.window)
            window = resolve_window(on, start, end, boundary)
            row.starts_at = window.starts_at
            row.ends_at = window.ends_at
        prepared.append(row)
        flat.append(row)
        row.children = _prepare_items(
            item.children, section_index, row.id, on, boundary, flat
        )
    return prepared


def prepare_plan(
    document: PlanDocument, on: date, boundary: DayBoundary
) -> tuple[list[list[_PreparedItem]], list[_PreparedItem]]:
    """
    The document as rows-to-be: one tree per section, plus every row flat.

    The flat list is what gets judged; the trees are what gets written. Both
    reference the same objects, so a line cannot be validated in one shape and
    stored in another.
    """
    trees: list[list[_PreparedItem]] = []
    flat: list[_PreparedItem] = []
    for section_index, section in enumerate(document.sections):
        trees.append(
            _prepare_items(section.items, section_index, None, on, boundary, flat)
        )
    return trees, flat


async def get_plan(db: AsyncSession, on: date) -> DayPlan | None:
    """The stored plan of `on`, with sections and items loaded, or None."""
    result = await db.execute(
        select(DayPlan)
        .where(DayPlan.day_date == on)
        .options(selectinload(DayPlan.sections).selectinload(PlanSection.items))
    )
    return result.scalar_one_or_none()


async def delete_plan(db: AsyncSession, on: date) -> bool:
    """
    Remove the plan of `on` entirely. Sections and items go with it by cascade.

    Returns whether there was one, so the caller can tell "replaced" from
    "created" without a second query.
    """
    result = await db.execute(delete(DayPlan).where(DayPlan.day_date == on))
    await db.flush()
    return bool(result.rowcount)


async def replace_plan(
    db: AsyncSession,
    on: date,
    rule: DayRuleSet,
    document: PlanDocument,
    boundary: DayBoundary | None = None,
) -> DayPlan:
    """
    Store `document` as the plan of `on`, replacing whatever was there.

    Raises `PlanRejected` before touching a row: nothing is deleted for a plan
    that is not going to be accepted, so a rejected `POST` leaves yesterday's
    plan exactly as it was rather than emptying the day on the way to a 422.
    """
    resolved_boundary = boundary if boundary is not None else current_boundary()
    trees, flat = prepare_plan(document, on, resolved_boundary)
    validate_plan([row.facts() for row in flat], rule)

    await delete_plan(db, on)

    plan = DayPlan(
        id=uuid.uuid4(),
        day_date=on,
        title=document.title,
        title_marker=document.title_marker,
        lede=document.lede,
        purpose_md=document.purpose_md,
        quarter_goal_id=document.quarter_goal_id,
        counters=document.counters,
        condition_tomorrow=document.condition_tomorrow,
        status=document.status,
        source=document.source,
        raw_md=document.raw_md,
    )
    db.add(plan)

    for section_index, section_in in enumerate(document.sections):
        section = PlanSection(
            id=uuid.uuid4(),
            plan_id=plan.id,
            ord=section_index,
            title=section_in.title,
            kind=section_in.kind,
        )
        db.add(section)
        for row in flat:
            if row.section_index == section_index:
                db.add(_to_model(row, section.id))

    await db.flush()
    stored = await get_plan(db, on)
    if stored is None:  # pragma: no cover - the insert above just ran
        raise RuntimeError(
            f"plan for {on.isoformat()} vanished between insert and read."
        )
    return stored


def _to_model(row: _PreparedItem, section_id: uuid.UUID) -> PlanItem:
    """One prepared row as the ORM object that will be inserted."""
    source = row.source
    return PlanItem(
        id=row.id,
        section_id=section_id,
        parent_id=row.parent_id,
        ord=row.ord,
        kind=source.kind,
        rigidity=source.rigidity,
        text_md=source.text_md,
        text_plain=row.text_plain,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        window_comment=source.window_comment,
        code=source.code,
        done_criterion=source.done_criterion,
        why_md=source.why_md,
        plan_md=source.plan_md,
        external_ref=source.external_ref,
        extra=source.extra,
        quarter_goal_id=source.quarter_goal_id,
        unlinked_reason=source.unlinked_reason,
        carried_from_item_id=source.carried_from_item_id,
        carry_count=source.carry_count,
        legacy_key=source.legacy_key,
    )


async def find_overlaps(db: AsyncSession, plan_id: uuid.UUID) -> list[ScheduleOverlap]:
    """Every pair of items of this plan whose windows intersect."""
    result = await db.execute(OVERLAP_SQL, {"plan_id": plan_id})
    return [
        ScheduleOverlap(
            left_item_id=row.left_item_id,
            right_item_id=row.right_item_id,
            overlap_minutes=int(row.overlap_seconds) // SECONDS_PER_MINUTE,
        )
        for row in result
    ]


def build_schedule(plan: DayPlan) -> list[ScheduleEntry]:
    """
    Every item that claimed a piece of the clock, in the order of the day.

    Minutes are computed here rather than in the browser: a window that runs
    past midnight is only sixty minutes long to someone who knows where the day
    ends, and the stored moments already carry that answer.
    """
    entries: list[ScheduleEntry] = []
    for section in plan.sections:
        for item in section.items:
            if item.starts_at is None or item.ends_at is None:
                continue
            span = item.ends_at - item.starts_at
            entries.append(
                ScheduleEntry(
                    item_id=item.id,
                    section_id=section.id,
                    code=item.code,
                    text_plain=item.text_plain,
                    kind=item.kind,
                    rigidity=item.rigidity,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    minutes=int(span.total_seconds()) // SECONDS_PER_MINUTE,
                    window_comment=item.window_comment,
                )
            )
    entries.sort(key=lambda entry: (entry.starts_at, entry.ends_at))
    return entries


def _item_response(item: PlanItem) -> PlanItemResponse:
    """
    One row as its DTO, field by field and with no children yet.

    Spelled out rather than left to `model_validate(item)`: pydantic would read
    every attribute the DTO declares, `children` included, and reading that one
    off an ORM object outside a greenlet is a lazy load that raises. Naming the
    columns also means adding a column to the table does not silently add a
    field to the wire.
    """
    return PlanItemResponse(
        id=item.id,
        parent_id=item.parent_id,
        ord=item.ord,
        kind=item.kind,
        rigidity=item.rigidity,
        text_md=item.text_md,
        text_plain=item.text_plain,
        starts_at=item.starts_at,
        ends_at=item.ends_at,
        window_comment=item.window_comment,
        code=item.code,
        done_criterion=item.done_criterion,
        why_md=item.why_md,
        plan_md=item.plan_md,
        external_ref=item.external_ref,
        extra=dict(item.extra),
        quarter_goal_id=item.quarter_goal_id,
        unlinked_reason=item.unlinked_reason,
        carried_from_item_id=item.carried_from_item_id,
        carry_count=item.carry_count,
        children=[],
    )


def _nest(items: list[PlanItem]) -> list[PlanItemResponse]:
    """
    The flat rows of a section rebuilt into the tree they were sent as.

    Two passes, not one. `ord` numbers siblings among themselves, so a child at
    position 0 sorts ahead of its parent at position 2 and a single pass would
    hand the child a parent it has not built yet — and quietly promote it to a
    root, which reads on screen as a step that escaped its task.
    """
    ordered = sorted(items, key=lambda row: row.ord)
    by_id: dict[uuid.UUID, PlanItemResponse] = {}
    for item in ordered:
        by_id[item.id] = _item_response(item)

    roots: list[PlanItemResponse] = []
    for item in ordered:
        node = by_id[item.id]
        parent = by_id.get(item.parent_id) if item.parent_id else None
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots


async def to_response(db: AsyncSession, plan: DayPlan) -> PlanResponse:
    """The stored plan as the screen and `/day-open` read it."""
    sections = [
        PlanSectionResponse(
            id=section.id,
            ord=section.ord,
            title=section.title,
            kind=section.kind,
            items=_nest(list(section.items)),
        )
        for section in sorted(plan.sections, key=lambda row: row.ord)
    ]
    return PlanResponse(
        id=plan.id,
        day_date=plan.day_date,
        title=plan.title,
        title_marker=plan.title_marker,
        lede=plan.lede,
        purpose_md=plan.purpose_md,
        quarter_goal_id=plan.quarter_goal_id,
        counters=list(plan.counters),
        condition_tomorrow=plan.condition_tomorrow,
        status=plan.status,
        source=plan.source,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        sections=sections,
        schedule=build_schedule(plan),
        overlaps=await find_overlaps(db, plan.id),
    )


__all__ = [
    "PlanRejected",
    "build_schedule",
    "delete_plan",
    "find_overlaps",
    "get_plan",
    "prepare_plan",
    "replace_plan",
    "to_response",
]
