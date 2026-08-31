# [review:need-review] PHASE-03/140
# summary: the plan as a source of roles — a tick on an item that names an act closes `role_act` with `source='plan'` and `external_ref = plan_item.id`, un-ticking takes it back unless a person confirmed it, the windows under a section that names a role become `role_time_block` minutes, and every weaker source loses the hours the plan already owns
"""
The plan of the day, read as a statement about roles.

Two connections live here, and neither belongs to the plan alone or to the roles
alone.

**Пункт плана несёт намерение на акт.** `feedback.md` says it in one line:
«минимум без своей галочки не работает». An act that has to be entered on a
separate screen with a separate form does not get entered — the counter
«написано с нуля 0/3» stood untouched for six weeks exactly that way. So the act
closes where the day is already being ticked: marking an item `done` writes the
act, un-marking takes it back. `external_ref` is the item's id, which makes the
write idempotent by the constraint `#134` already put on the table — a second
tick of the same line does not produce a second act.

Priority is `manual > plan`, spelled by the same guard as everywhere else: an act
a person confirmed on `/roles` survives un-ticking the line it came from. The
automation may create and retract its own claim; it may not overrule a person's.

**Секция плана размечает минуты.** A section that names a role turns the windows
written under it into `role_time_block` with `source='plan'`. The minutes are
the *union* of those windows, not their sum: a task and its «Минимум» nested
inside it are one hour lived once, and adding them would inflate every day that
plans carefully.

And because the plan is a stronger claim on an hour than any automation
(`app.roles.precedence`), writing plan minutes takes those hours away from every
weaker source that had claimed them. This is what keeps the day from adding up
twice on exactly the days the numbers matter — the ones where the agent agreed
with the plan.

Marks do not change the minutes. A section says how the day was laid out, and
laying it out is what the section did whether or not each line got its tick; the
tick is measured by the act and by the verdict of `#90`, which is where «не
сделал» belongs. The minutes are recomputed on a plan write only.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import plan as plan_crud
from app.crud import role as role_crud
from app.models.mark import MARK_DONE
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.models.role import (
    CONFIDENCE_AUTO,
    CONFIDENCE_CONFIRMED,
    SOURCE_PLAN,
    RoleAct,
    RoleTimeBlock,
)
from app.roles.precedence import Span, is_weaker, merge, minutes_of, subtract

__all__ = [
    "apply_precedence",
    "plan_spans_by_section",
    "sync_act_for_item",
    "sync_plan_minutes",
    "sync_plan_roles",
]

# `role_act.title` is 200 characters; a plan line is unbounded text. The line is
# cut rather than refused: an act nobody can write because the task was worded
# at length is the failure this ticket exists to remove.
MAX_ACT_TITLE = 200


def _span_of(item: PlanItem) -> Span | None:
    """The window of one line, or None when it claims no piece of the clock."""
    if item.starts_at is None or item.ends_at is None:
        return None
    return Span(start=item.starts_at, end=item.ends_at)


def plan_spans_by_section(plan: DayPlan | None) -> dict[uuid.UUID, list[Span]]:
    """
    The wall time each role-bearing section claims, merged, by section id.

    Sections without a role are absent rather than empty: «эта секция роль не
    называет» and «эта секция роль называет и окон под ней нет» are different
    facts, and the second one has to erase a block the previous plan wrote.

    Pure, and reading a loaded plan only — `section.items` is flat over the
    whole subtree, so a nested «Минимум» is folded into its parent's hour by
    `merge` instead of being counted beside it.
    """
    if plan is None:
        return {}
    spans: dict[uuid.UUID, list[Span]] = {}
    for section in plan.sections:
        if section.role_id is None:
            continue
        spans[section.id] = merge(
            [span for item in section.items if (span := _span_of(item)) is not None]
        )
    return spans


async def _plan_blocks(db: AsyncSession, on: date) -> list[RoleTimeBlock]:
    """Every record of minutes this day owes to the plan."""
    result = await db.execute(
        select(RoleTimeBlock).where(
            RoleTimeBlock.work_day == on, RoleTimeBlock.source == SOURCE_PLAN
        )
    )
    return list(result.scalars().all())


async def sync_plan_minutes(db: AsyncSession, on: date) -> None:
    """
    Restate the day's plan minutes from the plan, then settle the precedence.

    Restate rather than append: the plan is replaced whole (`#87`), a section can
    lose its role or its windows between two writes, and a block left behind by a
    section that no longer claims anything is a minute charged to a role for a
    reason nobody can find. Blocks a person confirmed are left where they are —
    the same `manual > plan` guard `role_crud.write_time_block` applies.
    """
    plan = await plan_crud.get_plan(db, on)
    spans = plan_spans_by_section(plan)

    for section_id, section_spans in spans.items():
        minutes = minutes_of(section_spans)
        if minutes == 0:
            continue
        section = _section_of(plan, section_id)
        if section is None or section.role_id is None:  # pragma: no cover - defensive
            continue
        await role_crud.write_time_block(
            db,
            role_crud.TimeBlockDraft(
                work_day=on,
                role_id=section.role_id,
                minutes=minutes,
                source=SOURCE_PLAN,
                started_at=section_spans[0].start,
                ended_at=section_spans[-1].end,
                confidence=CONFIDENCE_AUTO,
                external_ref=str(section_id),
                note=section.title,
            ),
        )

    alive = {
        str(section_id) for section_id, rows in spans.items() if minutes_of(rows) > 0
    }
    for block in await _plan_blocks(db, on):
        if block.external_ref in alive:
            continue
        if block.confidence == CONFIDENCE_CONFIRMED:
            continue
        await db.delete(block)
    await db.flush()

    await apply_precedence(db, on, plan_spans=spans)


def _section_of(plan: DayPlan | None, section_id: uuid.UUID) -> PlanSection | None:
    if plan is None:  # pragma: no cover - callers hold a plan
        return None
    for section in plan.sections:
        if section.id == section_id:
            return section
    return None


async def apply_precedence(
    db: AsyncSession,
    on: date,
    *,
    plan_spans: dict[uuid.UUID, list[Span]] | None = None,
) -> None:
    """
    Cut every weaker source down to the hours no stronger source claimed.

    Called after the plan writes its minutes (`#140`) and after the classifier
    writes the agent's (`#135`), because either write can be the one that creates
    the overlap. A block left with no time at all is deleted rather than kept at
    zero: `role_time_block` refuses zero minutes by CHECK, and «строка на ноль
    минут» is not a fact worth a row anyway.

    A block a person confirmed is never touched — neither cut nor deleted. That
    is the same rule as everywhere: automation may retract its own claim and no
    one else's.

    A block with no window is outside this entirely. «Полтора часа на найм»
    records an amount, not a piece of the clock, and there is no honest way to
    ask whether it overlaps anything.

    `plan_spans` is the answer of `plan_spans_by_section` when the caller has
    just computed it; it is read back from the plan otherwise.
    """
    blocks = await role_crud.day_time_blocks(db, on)
    if plan_spans is None:
        plan_spans = plan_spans_by_section(await plan_crud.get_plan(db, on))
    spans_by_block = _spans_by_block(blocks, plan_spans)

    for block in blocks:
        if block.confidence == CONFIDENCE_CONFIRMED:
            continue
        own = spans_by_block.get(block.id)
        if not own:
            continue
        blockers = [
            span
            for other in blocks
            if other.id != block.id and is_weaker(block.source, other.source)
            for span in spans_by_block.get(other.id, [])
        ]
        if not blockers:
            continue
        remaining = subtract(own, blockers)
        minutes = minutes_of(remaining)
        if minutes == 0:
            await db.delete(block)
            continue
        if minutes == block.minutes:
            continue
        block.minutes = minutes
        block.started_at = remaining[0].start
        block.ended_at = remaining[-1].end
    await db.flush()


def _spans_by_block(
    blocks: list[RoleTimeBlock], plan_spans: dict[uuid.UUID, list[Span]]
) -> dict[int, list[Span]]:
    """
    The wall time each block actually holds, by block id.

    A plan block is asked back from the plan rather than read off its own
    `started_at`/`ended_at`: those are the ends of the section, and a section
    with a two-hour gap in the middle of it would otherwise claim the gap and
    displace an agent's hour that nothing planned.
    """
    spans: dict[int, list[Span]] = {}
    for block in blocks:
        if block.source == SOURCE_PLAN and block.external_ref is not None:
            section_id = _as_uuid(block.external_ref)
            section_spans = plan_spans.get(section_id) if section_id else None
            if section_spans:
                spans[block.id] = section_spans
            continue
        if block.started_at is not None and block.ended_at is not None:
            spans[block.id] = merge([Span(start=block.started_at, end=block.ended_at)])
    return spans


def _as_uuid(value: str) -> uuid.UUID | None:
    """An `external_ref` back as the section id it was written from, or None."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _plan_act(db: AsyncSession, item_id: uuid.UUID) -> RoleAct | None:
    """The act this line of the plan has already closed, if any."""
    result = await db.execute(
        select(RoleAct).where(
            RoleAct.source == SOURCE_PLAN, RoleAct.external_ref == str(item_id)
        )
    )
    return result.scalar_one_or_none()


async def sync_act_for_item(
    db: AsyncSession, on: date, item: PlanItem, state: str | None
) -> RoleAct | None:
    """
    Bring the act of one line into line with its mark. Returns it, or None.

    `done` closes the act; every other state — `failed`, `skipped`, no mark at
    all — takes it back. «Не сделал» deliberately does not close and does not
    create: the whole value of the connection is that the tick means what it
    says.

    A line that names no act kind or no role is left alone, and that is the
    normal case: planning an act ahead is not an obligation, and an ordinary item
    stays an ordinary item.
    """
    if item.act_kind is None or item.role_id is None:
        return None

    if state == MARK_DONE:
        outcome = await role_crud.write_act(
            db,
            role_crud.ActDraft(
                work_day=on,
                role_id=item.role_id,
                act_kind=item.act_kind,
                title=item.text_plain[:MAX_ACT_TITLE],
                source=SOURCE_PLAN,
                external_ref=str(item.id),
                confidence=CONFIDENCE_AUTO,
            ),
        )
        return outcome.row

    existing = await _plan_act(db, item.id)
    if existing is None:
        return None
    if existing.confidence == CONFIDENCE_CONFIRMED:
        return existing
    await db.delete(existing)
    await db.flush()
    return None


async def sync_plan_roles(db: AsyncSession, on: date) -> None:
    """
    Everything the roles owe to a plan that has just been written or edited.

    Two things, both of which a plan write can invalidate: the minutes of its
    sections, and the acts of lines that no longer ask for one. The second is the
    case the plan makes possible on its own — a line whose act kind was removed,
    or that was deleted outright, would otherwise leave an act standing on a day
    with nothing to explain it. An act a person confirmed stays, as always.
    """
    await sync_plan_minutes(db, on)

    plan = await plan_crud.get_plan(db, on)
    wanted = {
        str(item.id)
        for section in (plan.sections if plan is not None else [])
        for item in section.items
        if item.act_kind is not None and item.role_id is not None
    }
    for act in await role_crud.day_acts(db, on):
        if act.source != SOURCE_PLAN or act.external_ref in wanted:
            continue
        if act.confidence == CONFIDENCE_CONFIRMED:
            continue
        await db.delete(act)
    await db.flush()
