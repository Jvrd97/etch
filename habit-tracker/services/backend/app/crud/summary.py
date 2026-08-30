# [review:need-review] PHASE-03/90
# summary: persistence of the day's итог — the facts gathered from rows that already exist, the upsert that closes a day, the whole-history recompute that never touches an imported verdict, and full-text search over the prose
"""
Database access for the итог of a day.

Three decisions carry the ticket.

**Наличие строки — это и есть «день закрыт».** `summary_for` answers with the
stored row when there is one and with a live recount when there is not, and the
live one carries `verdict = null` and the reason `not_closed`. So «не закрыл»
and «проиграл» come back different without a second flag, the screen shows
progress before anything is pressed, and there is one code path instead of two.
The *stage* of closing is `#143` and adds a column rather than a table.

**Импортированные вердикты не пересчитываются никогда.** `recompute_history`
re-judges rows written here (`source='close'`) and only ever writes the derived
`streak_after` onto rows that arrived as prose (`source='import'`). Смена канона
2026-08-17 иначе задним числом переписала бы всё, что было до неё — and a
verdict recomputed from marks that were never made would be zeros pretending to
be history.

**Стрик считается в одном месте.** `close_day` writes the row and then folds
`app.day.streak.step_streak` over every day in date order. A running number kept
per row and patched on write would drift the first time a past day is closed
out of order, which is exactly what closing yesterday at 00:30 is.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.day.evaluate import VERDICT_WON, DayFacts, Verdict, evaluate_day
from app.day.rules import resolve_rule
from app.day.streak import step_streak
from app.models.day import DayRuleSet
from app.models.mark import PlanMark
from app.models.plan import DayPlan
from app.models.summary import SOURCE_CLOSE, DaySummary
from app.schemas.summary import DayCloseIn, DaySummaryResponse

__all__ = [
    "close_day",
    "facts_of",
    "get_summary",
    "recompute_history",
    "search",
    "summary_for",
]


def facts_of(
    plan: DayPlan | None,
    marks: list[PlanMark],
    *,
    work_minutes: int | None,
    closed: bool,
) -> DayFacts:
    """
    Everything the verdict is decided from, read off rows already in hand.

    Anchors are counted from `plan_item.kind='anchor'` rather than from a
    catalogue: `anchor_kind`/`day_anchor` arrive with `#92`, and until then the
    lines of the plan are the only place an anchor exists. Their *kinds* — which
    anchors of the canon this day closed — are read off the codes those lines
    carry and are `None` when the plan names none, so an unnamed composition
    falls back to the counter instead of losing the day (`#142`).
    """
    return DayFacts(
        closed=closed,
        tasks=mark_crud.task_counts(plan, marks),
        anchors=mark_crud.anchor_counts(plan, marks),
        work_minutes=work_minutes,
        anchor_kinds=mark_crud.closed_anchor_kinds(plan, marks),
    )


async def get_summary(db: AsyncSession, on: date) -> DaySummary | None:
    """The stored итог of `on`, or None while the day is not closed."""
    result = await db.execute(select(DaySummary).where(DaySummary.day_date == on))
    return result.scalar_one_or_none()


def _to_response(row: DaySummary, *, missing_anchors: list[str]) -> DaySummaryResponse:
    """
    A stored row as the wire carries it.

    Written out field by field rather than through `from_attributes`: `closed`
    and `missing_anchors` are not columns — the first is the existence of this
    row, the second a reading of the plan — and a DTO half-filled by reflection
    and half by hand is the version that quietly drops a field on the next edit.
    """
    return DaySummaryResponse(
        day_date=row.day_date,
        closed=True,
        rule_set_id=row.rule_set_id,
        verdict=row.verdict,
        verdict_reason=row.verdict_reason,
        verdict_override=row.verdict_override,
        verdict_override_note=row.verdict_override_note,
        anchors_done=row.anchors_done,
        anchors_total=row.anchors_total,
        tasks_done=row.tasks_done,
        tasks_total=row.tasks_total,
        work_minutes=row.work_minutes,
        streak_after=row.streak_after,
        wrote_from_scratch=row.wrote_from_scratch,
        education_debt=row.education_debt,
        reviewed_today=row.reviewed_today,
        body_md=row.body_md,
        missing_data=list(row.missing_data),
        missing_anchors=missing_anchors,
        source=row.source,
    )


def _preview(
    on: date, verdict: Verdict, *, missing_anchors: list[str]
) -> DaySummaryResponse:
    """The итог of a day nobody has closed: counted live, judged by nothing."""
    return DaySummaryResponse(
        day_date=on,
        closed=False,
        rule_set_id=verdict.rule_set_id,
        verdict=verdict.verdict,
        verdict_reason=verdict.reason,
        anchors_done=verdict.anchors_done,
        anchors_total=verdict.anchors_total,
        tasks_done=verdict.tasks_done,
        tasks_total=verdict.tasks_total,
        work_minutes=verdict.work_minutes,
        missing_data=list(verdict.missing_data),
        missing_anchors=missing_anchors,
    )


async def summary_for(
    db: AsyncSession,
    on: date,
    rule: DayRuleSet,
    plan: DayPlan | None,
    marks: list[PlanMark],
) -> DaySummaryResponse:
    """
    The итог block `GET /day/{date}` always carries.

    Takes the plan and the marks the caller has already loaded rather than
    reading them again: the day screen needs both anyway, and a second read
    would be a second chance for the counters on the page to disagree with the
    verdict beside them.
    """
    missing = mark_crud.missing_anchors(plan, marks)
    stored = await get_summary(db, on)
    if stored is not None:
        return _to_response(stored, missing_anchors=missing)
    facts = facts_of(plan, marks, work_minutes=None, closed=False)
    return _preview(on, evaluate_day(rule, facts), missing_anchors=missing)


async def _store_close(
    db: AsyncSession, on: date, rule_set_id: int, body: DayCloseIn
) -> None:
    """
    Write what the person said about the day, and nothing the machine decides.

    The verdict, its reason and the counters are deliberately absent here:
    `recompute_history` writes them for this row along with every other, so the
    judgement is made in exactly one place. A row inserted for the first time
    gets them from the column defaults and is judged a moment later.
    """
    values = {
        "day_date": on,
        "rule_set_id": rule_set_id,
        "verdict_override": body.verdict_override,
        "verdict_override_note": body.verdict_override_note,
        "work_minutes": body.work_minutes,
        "wrote_from_scratch": body.wrote_from_scratch,
        "education_debt": body.education_debt,
        "reviewed_today": body.reviewed_today,
        "body_md": body.body_md,
        "source": SOURCE_CLOSE,
    }
    statement = pg_insert(DaySummary).values(**values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[DaySummary.day_date],
            set_={key: statement.excluded[key] for key in values if key != "day_date"},
        )
    )
    await db.flush()


async def close_day(db: AsyncSession, on: date, body: DayCloseIn) -> DaySummaryResponse:
    """
    Close the day `on`: store what was said about it, then judge the history.

    The day is judged against the rule it was lived under, not the rule in force
    now — closing yesterday at 00:30 and closing a day of last month have to
    give the same answer they would have given then.
    """
    day = await day_crud.ensure_day(db, on)
    rule = await day_crud.rule_for_date(db, on)
    await _store_close(db, day.day_date, rule.id, body)
    await recompute_history(db)

    plan = await plan_crud.get_plan(db, on)
    marks = await mark_crud.list_marks(db, on)
    return await summary_for(db, day.day_date, rule, plan, marks)


async def recompute_history(db: AsyncSession) -> None:
    """
    Re-judge every day that was closed here, and re-fold the streak over all of them.

    Идемпотентен: два прогона подряд оставляют те же значения, because every
    number written is a function of rows that the recompute itself does not
    change. It is also the only place a verdict is ever written, which is why
    closing a day is "store the answers, then recompute" rather than a second
    copy of the same arithmetic.

    **Ни один импортированный вердикт не переписывается.** A row with
    `source='import'` carries a judgement made in prose by a person, about a day
    whose marks were never entered; recomputing it would replace history with
    zeros. Only `streak_after` — derived by definition — is written onto it.

    **Переопределение переживает пересчёт.** `verdict_override` replaces the
    verdict and leaves `verdict_reason` as the machine reached it: a person
    re-reading the day in a month has to see what was disagreed with.
    """
    rules = await day_crud.list_rules(db)
    result = await db.execute(select(DaySummary).order_by(DaySummary.day_date))
    streak = 0

    for row in result.scalars().all():
        if row.source == SOURCE_CLOSE:
            plan = await plan_crud.get_plan(db, row.day_date)
            marks = await mark_crud.list_marks(db, row.day_date)
            facts = facts_of(plan, marks, work_minutes=row.work_minutes, closed=True)
            verdict = evaluate_day(resolve_rule(rules, row.day_date), facts)
            row.verdict = VERDICT_WON if row.verdict_override else verdict.verdict
            row.verdict_reason = verdict.reason
            row.anchors_done = verdict.anchors_done
            row.anchors_total = verdict.anchors_total
            row.tasks_done = verdict.tasks_done
            row.tasks_total = verdict.tasks_total
            row.missing_data = list(verdict.missing_data)
        streak = step_streak(streak, row.day_date, row.verdict)
        row.streak_after = streak

    await db.flush()


async def search(db: AsyncSession, query: str) -> list[DaySummary]:
    """
    The days whose prose matches `query`, oldest first.

    `plainto_tsquery` rather than `to_tsquery`: the input is a phrase a person
    typed («что мешало вчера»), not an expression with operators, and the
    alternative is a syntax error thrown at a reader who wrote ordinary Russian.
    """
    result = await db.execute(
        select(DaySummary)
        .where(DaySummary.search.op("@@")(func.plainto_tsquery("russian", query)))
        .order_by(DaySummary.day_date)
    )
    return list(result.scalars().all())
