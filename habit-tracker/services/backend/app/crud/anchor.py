# [review:need-review] PHASE-03/92
# summary: anchor persistence — the catalogue seeded from `app.models.anchor`, the anchors of one day read against the composition the rule names, an upsert on (day_date, kind) whose second write wins, the link from an anchor to the plan line it is written on, and the reading `evaluate_day` decides a day by
"""
Database access for the anchors of a day.

**Якорь стал строкой, и это снимает подпорку.** До `#92` якорем был буллет,
который узнавали по подстроке «якор» в тексте, и вердикт дня считался по этому
узнаванию. Отсюда два следствия: план, сформулировавший якорь другими словами,
терял его молча, и якоря не могло быть у дня, чей план не написан вовсе. Здесь
якорь — строка `day_anchor` с `UNIQUE(day_date, kind)`, и оба следствия
исчезают вместе с распознаванием.

**Состав якорей приходит из правила, а не отсюда.** `day_rule_set.anchors`
называет, какими якорями судится конкретный день; `anchor_kind` говорит, что
такое вид якоря. Поэтому «добавить вечер с близкими» — это `INSERT` в каталог
плюс новая строка правила, и ни одной правки в коде, который судит день.

**Отметка якоря — upsert, а не чтение-с-правкой.** Ровно та же причина, что у
`app.crud.mark`: две вкладки пишут то, что видели, побеждает последняя, и
`updated_at` показывает, какая именно.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.day.marks import TaskCounts, count_day_anchors
from app.day.plan_validate import KIND_ANCHOR
from app.models.anchor import (
    ANCHOR_KIND_SEED,
    CLOSING_ANCHOR_STATES,
    AnchorKind,
    DayAnchor,
)
from app.models.day import DayRuleSet
from app.models.plan import DayPlan, PlanItem, PlanSection

__all__ = [
    "anchor_counts",
    "closed_kinds",
    "known_codes",
    "list_day_anchors",
    "list_kinds",
    "missing_anchor_titles",
    "seed_anchor_kinds",
    "set_anchor",
    "states_of",
    "sync_from_plan",
]


async def list_kinds(db: AsyncSession) -> list[AnchorKind]:
    """The catalogue, in the order a person reads a day in."""
    result = await db.execute(select(AnchorKind).order_by(AnchorKind.ord))
    return list(result.scalars().all())


async def seed_anchor_kinds(db: AsyncSession) -> None:
    """
    Ensure the catalogue rows exist, without disturbing rows already there.

    Runs on a filled table as happily as on an empty one, the same way
    `app.crud.day.seed_rules` does, so a test database built by `create_all` —
    which never sees the migration's seed — starts from the same catalogue as a
    migrated one. A kind is recognised by its code; a title edited by hand stays
    edited.
    """
    existing = {kind.code for kind in await list_kinds(db)}
    for seed in ANCHOR_KIND_SEED:
        if seed.code in existing:
            continue
        db.add(
            AnchorKind(
                code=seed.code,
                title=seed.title,
                ord=seed.ord,
                counts_for_verdict=seed.counts_for_verdict,
                required_in_nonwork_evening=seed.required_in_nonwork_evening,
            )
        )
    await db.flush()


async def known_codes(db: AsyncSession) -> set[str]:
    """Every code the catalogue knows — what an unknown kind is checked against."""
    result = await db.execute(select(AnchorKind.code))
    return set(result.scalars().all())


async def list_day_anchors(db: AsyncSession, on: date) -> list[DayAnchor]:
    """Every anchor row of `on`, in catalogue order."""
    result = await db.execute(
        select(DayAnchor)
        .join(AnchorKind, AnchorKind.code == DayAnchor.kind)
        .where(DayAnchor.day_date == on)
        .order_by(AnchorKind.ord)
    )
    return list(result.scalars().all())


async def set_anchor(
    db: AsyncSession,
    on: date,
    kind: str,
    *,
    state: str | None,
    note: str | None,
    item_id: uuid.UUID | None = None,
) -> DayAnchor:
    """
    Give the anchor `kind` of the day `on` the state `state`.

    A second anchor of the same kind on the same date is not an error to be
    reported — it is a state that cannot exist, so the write lands on the row
    that is already there. The database refuses the duplicate regardless of who
    is writing, which is what the acceptance case «второй якорь того же вида не
    сохраняется» is actually about.
    """
    values = {
        "id": uuid.uuid4(),
        "day_date": on,
        "kind": kind,
        "state": state,
        "note": note,
        "item_id": item_id,
    }
    statement = pg_insert(DayAnchor).values(**values)
    updated = {
        "state": statement.excluded.state,
        "note": statement.excluded.note,
    }
    if item_id is not None:
        updated["item_id"] = statement.excluded.item_id
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[DayAnchor.day_date, DayAnchor.kind], set_=updated
        )
    )
    await db.flush()
    result = await db.execute(
        select(DayAnchor).where(DayAnchor.day_date == on, DayAnchor.kind == kind)
    )
    return result.scalar_one()


async def sync_from_plan(db: AsyncSession, on: date) -> int:
    """
    Point every anchor of `on` at the line of the plan it is written on.

    The line's `code` is the kind — the same vocabulary `day_rule_set.anchors`
    speaks and the one `#87` validates a hard anchor against. Only the link is
    written: the state of an anchor is a person's answer, and a plan being
    rewritten at 14:00 must not tick or untick anything.

    Returns how many anchors got a line, so the caller can say nothing at all
    when a plan carries no anchors.
    """
    codes = await known_codes(db)
    result = await db.execute(
        select(PlanItem)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanItem.kind == KIND_ANCHOR)
    )
    linked = 0
    for item in result.scalars().all():
        if item.code is None or item.code not in codes:
            continue
        statement = pg_insert(DayAnchor).values(
            id=uuid.uuid4(),
            day_date=on,
            kind=item.code,
            item_id=item.id,
            state=None,
            note=None,
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[DayAnchor.day_date, DayAnchor.kind],
                set_={"item_id": statement.excluded.item_id},
            )
        )
        linked += 1
    await db.flush()
    return linked


def states_of(anchors: Sequence[DayAnchor]) -> dict[str, str | None]:
    """The state of every anchor of a day, by kind."""
    return {anchor.kind: anchor.state for anchor in anchors}


def closed_kinds(anchors: Sequence[DayAnchor]) -> frozenset[str] | None:
    """
    Which anchors the day actually closed — `None` when nothing was answered.

    `None` means «состав не измерен», not «ни одного», and it is what makes the
    imported history readable: a day of July has no anchor rows at all, and
    reading that as "closed nothing" would lose every day before the table
    existed. The verdict falls back to counting the anchor lines of the plan
    exactly as it did before `#92`, and says so in `missing_data`.

    `skipped` counts as closed, the same as it does for a task: an anchor that
    stopped being relevant is not one the day missed.
    """
    answered = {
        anchor.kind: anchor.state for anchor in anchors if anchor.state is not None
    }
    if not answered:
        return None
    return frozenset(
        kind for kind, state in answered.items() if state in CLOSING_ANCHOR_STATES
    )


def anchor_counts(rule: DayRuleSet, anchors: Sequence[DayAnchor]) -> TaskCounts | None:
    """
    The anchors of the day counted against the composition the rule names.

    `None` when no anchor of the day says anything — the caller then counts the
    anchor lines of the plan instead, which is the only reading available for a
    day that predates the table.
    """
    if closed_kinds(anchors) is None:
        return None
    return count_day_anchors(tuple(rule.anchors or ()), states_of(anchors))


def missing_anchor_titles(
    kinds: Sequence[AnchorKind], required: Sequence[str], anchors: Sequence[DayAnchor]
) -> list[str]:
    """
    The anchors the day left open, named the way a person reads them.

    «Не хватило вечера с близкими» is what a reader can act on; «якоря 5 из 6»
    is not. Titles come from the catalogue rather than from the codes, which is
    the whole reason `anchor_kind.title` is a column.
    """
    titles = {kind.code: kind.title for kind in kinds}
    states = states_of(anchors)
    return [
        titles.get(code, code)
        for code in required
        if states.get(code) not in CLOSING_ANCHOR_STATES
    ]
