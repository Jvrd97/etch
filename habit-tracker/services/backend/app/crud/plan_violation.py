# [review:need-review] PHASE-03/147
# summary: the violations of a day — recorded as rows in the same transaction as the plan they belong to, replaced wholesale per (day, origin) so a re-check never doubles them, and read back for the screen; also the one converter that turns a built skeleton into the `PlanDocument` the accepting path already knows
"""
Where a broken rule is written down, and where a skeleton becomes a plan.

Two things live here rather than in two modules because they are the two halves
of one write: the endpoint builds a skeleton, turns it into the document
`#87` already accepts, and records whatever the rules said about it — all inside
one transaction, so a plan is never stored with the note about it missing.

**Violations are replaced, not appended.** One row per (day, origin, rule) at a
time: re-checking the same day twice is a normal thing to do — a person edits,
the skeleton runs again — and an append-only table would answer "how often is
this rule broken" with the number of times somebody looked.

PII: nothing here formats `text_md`, a title or a note into a row or a log line.
What goes into `detail` is what `app.day.constraints` built, which is ids and
numbers by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.day.constraints import Violation
from app.day.skeleton import KIND_TASK, SKELETON_SOURCE, SkeletonPlan
from app.models.day import DayRuleSet
from app.models.plan_violation import PlanViolation
from app.schemas.plan import PlanDocument, PlanItemIn, PlanSectionIn

__all__ = [
    "SKELETON_TITLE",
    "clear_violations",
    "list_violations",
    "record_violations",
    "skeleton_document",
]

# What the header of a generated plan says. The screen reads it to answer "кем
# он собран" without a second column: a plan whose title says nothing about its
# author is a plan a person has to guess about.
SKELETON_TITLE = "Скелет дня"

# Why a carried task names no goal of the quarter, when the queue it came from
# did not say. Required by the CHECK of `#87` — a task is linked or it explains
# itself — and honest: the skeleton does not know, and pretending it does would
# put somebody else's urgency into the day silently.
UNLINKED_BY_SKELETON = "перенос из очереди; цель квартала не названа источником"


async def record_violations(
    db: AsyncSession,
    day_date: date,
    violations: Sequence[Violation],
    *,
    origin: str,
) -> list[PlanViolation]:
    """
    Store what the rules said about this day's draft, replacing the last answer.

    Scoped by `origin`: a `warn` from a person's edit and a `block` from the
    generator are answers to different questions about the same day, and one
    overwriting the other would lose whichever ran second.
    """
    await clear_violations(db, day_date, origin=origin)
    rows = [
        PlanViolation(
            day_date=day_date,
            rule_code=violation.rule_code,
            severity=violation.severity,
            origin=origin,
            detail=violation.detail,
        )
        for violation in violations
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def clear_violations(db: AsyncSession, day_date: date, *, origin: str) -> None:
    """Drop this origin's previous answer about this day."""
    await db.execute(
        delete(PlanViolation).where(
            PlanViolation.day_date == day_date, PlanViolation.origin == origin
        )
    )


async def list_violations(db: AsyncSession, day_date: date) -> list[PlanViolation]:
    """Everything recorded about this day, oldest first."""
    result = await db.execute(
        select(PlanViolation)
        .where(PlanViolation.day_date == day_date)
        .order_by(PlanViolation.id)
    )
    return list(result.scalars().all())


def _window(
    item_start: datetime | None, item_end: datetime | None, rule: DayRuleSet
) -> str | None:
    """
    A draft item's window in the `ЧЧ:ММ-ЧЧ:ММ` shape the accepting path parses.

    Rendered back into wall clock in the canon's own zone, because that is the
    shape `#87` reads and the shape a person sees; the datetimes the skeleton
    built are the same moments, spelled the other way.
    """
    if item_start is None or item_end is None:
        return None
    zone = ZoneInfo(rule.timezone)
    start = item_start.astimezone(zone).strftime("%H:%M")
    end = item_end.astimezone(zone).strftime("%H:%M")
    return f"{start}-{end}"


def skeleton_document(built: SkeletonPlan, rule: DayRuleSet) -> PlanDocument:
    """
    The built skeleton as the document `POST /day/{date}/plan` already accepts.

    One writing path rather than two: a generated plan goes through the same
    validation, the same id minting and the same mark-lifting as a plan a person
    sends, so a bug in storing plans cannot exist in one of them and not the
    other.
    """
    sections: list[PlanSectionIn] = []
    for section in built.sections:
        items: list[PlanItemIn] = []
        # The lines that carry a window and a code — anchors and tasks.
        texts = list(section.texts)
        for index, item in enumerate(section.items):
            is_task = item.kind == KIND_TASK
            text_md = texts[index] if is_task and index < len(texts) else item.code
            items.append(
                PlanItemIn(
                    kind=item.kind,
                    rigidity=item.rigidity,
                    text_md=text_md or item.kind,
                    window=_window(item.starts_at, item.ends_at, rule),
                    code=item.code,
                    done_criterion="сделано" if is_task else None,
                    unlinked_reason=UNLINKED_BY_SKELETON if is_task else None,
                )
            )
        # A section with no items is still a section: the free evening exists as
        # an empty block, and dropping it would make «свободный вечер» invisible
        # rather than empty.
        sections.append(
            PlanSectionIn(title=section.title, kind=section.kind, items=items)
        )

    return PlanDocument(
        title=SKELETON_TITLE,
        source=SKELETON_SOURCE,
        sections=sections,
    )
