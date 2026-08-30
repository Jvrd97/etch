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
from app.models.summary import SOURCE_CLOSE, SOURCE_IMPORT, DaySummary
from app.schemas.summary import DayCloseIn, DaySummaryResponse

__all__ = [
    "ImportedDayIsNotClosable",
    "close_day",
    "facts_of",
    "get_summary",
    "recompute_history",
    "search",
    "summary_for",
]


class ImportedDayIsNotClosable(RuntimeError):
    """
    `POST /close` reached a day whose итог arrived as prose.

    A row with `source='import'` carries a judgement a person made in words
    about a day whose marks were never entered. Letting a close write over it
    would hand that day to `recompute_history`, which would then re-judge it by
    marks that do not exist — the one thing this module says out loud it never
    does. So the write is refused whole rather than applied in part: such a day
    is edited in `summaries/YYYY/MM/*.md` and imported again.
    """

    def __init__(self, on: date) -> None:
        self.day_date = on
        super().__init__(
            f"Итог {on.isoformat()} пришёл прозой из personal-os: такой вердикт "
            "не пересчитывают. Правьте summary этого дня в personal-os и "
            "импортируйте заново."
        )


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
    lines of the plan are the only place an anchor exists.
    """
    return DayFacts(
        closed=closed,
        tasks=mark_crud.task_counts(plan, marks),
        anchors=mark_crud.anchor_counts(plan, marks),
        work_minutes=work_minutes,
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

    **Счётчики — снимок, список якорей — живой, и это видно на экране.**
    `anchors_done`/`tasks_done` are read off the row as `recompute_history` last
    wrote them, while `missing_anchors` is recounted from the marks as they are
    now. Nothing forbids ticking a line of a day already closed, and nothing
    recomputes the итог when that happens, so «якоря 4/5» beside an empty list
    of missed anchors is a reachable state. Reconciling the two means deciding
    whether a closed day may still change its verdict, which is `#143`; until
    then the difference is named here rather than hidden.
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


async def _stored_source(db: AsyncSession, on: date) -> str | None:
    """
    Where the stored итог of `on` came from, or None while there is no row.

    One column rather than `get_summary`, and deliberately so: loading the
    entity would put it in the identity map, and the `ON CONFLICT` that follows
    writes past the ORM — `recompute_history` would then re-judge the day from
    the copy it loaded before the write, using the minutes of work of the
    previous close.
    """
    source: str | None = await db.scalar(
        select(DaySummary.source).where(DaySummary.day_date == on)
    )
    return source


async def _store_close(
    db: AsyncSession, on: date, rule_set_id: int, body: DayCloseIn
) -> None:
    """
    Write the fields the caller actually named, and no others.

    **Только присланное, а не весь документ.** `POST /close` is used twice over
    the life of a day: once to close it, and later to переопределить the verdict
    — and that second request carries two fields. Writing the schema's defaults
    for the rest would blank `body_md` with one click of «Записать «выигран»»,
    and «проза итога — половина ценности записи» would be true of a record that
    no longer has any; `work_minutes` would go with it, so the day would also
    stop being checked for overtime. `model_fields_set` is what tells «не
    прислал» from «прислал null», so `verdict_override: false` removes an
    override and its absence leaves one standing.

    The verdict, its reason and the counters are deliberately absent here:
    `recompute_history` writes them for this row along with every other, so the
    judgement is made in exactly one place. A row inserted for the first time
    gets them from the column defaults and is judged a moment later.

    `source` is written on insert and never in `set_`. A row that arrived as
    prose must not become a closed day by being written over; `close_day`
    refuses that row outright, and this is the second lock — for a writer that
    goes past the handle.
    """
    sent = body.model_dump(exclude_unset=True)
    statement = pg_insert(DaySummary).values(
        day_date=on, rule_set_id=rule_set_id, source=SOURCE_CLOSE, **sent
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[DaySummary.day_date],
            set_={key: statement.excluded[key] for key in ("rule_set_id", *sent)},
        )
    )
    await db.flush()


async def close_day(db: AsyncSession, on: date, body: DayCloseIn) -> DaySummaryResponse:
    """
    Close the day `on`: store what was said about it, then judge the history.

    The day is judged against the rule it was lived under, not the rule in force
    now — closing yesterday at 00:30 and closing a day of last month have to
    give the same answer they would have given then.

    **День, чей итог пришёл прозой, здесь не закрывается.** A row with
    `source='import'` is refused with `ImportedDayIsNotClosable` before anything
    is written. Accepting it would flip `source` to `close` and put the day
    under `recompute_history`, which would re-judge a lived August by marks
    nobody ever entered — «импортированные вердикты не пересчитываются» is the
    promise of this module, and it only holds if there is no way in.
    """
    day = await day_crud.ensure_day(db, on)
    if await _stored_source(db, day.day_date) == SOURCE_IMPORT:
        raise ImportedDayIsNotClosable(day.day_date)
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

    **Переопределение — пятое правило вердикта, и оно одностороннее.**
    `evaluate_day` decides four conditions over values; the line below adds the
    fifth, which no pure function can hold — a person saying «день был выигран,
    просто я не отметил». It only ever turns `lost` into `won`, never the other
    way, and it leaves `verdict_reason` as the machine reached it: a person
    re-reading the day in a month has to see what was disagreed with. The rule
    lives here rather than in `app.day.evaluate` because it is a fact of the
    stored row, not of the day's facts.
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

    **Ручки над этим пока нет.** The only callers are the tests. Search over the
    prose is finished at this layer — generated `tsvector`, GIN index, this
    function — and `GET /day/search?q=` is not written, because the path would
    have to be registered ahead of `GET /day/{on}` or a date parser would claim
    it. Named here so that a reader does not take the feature for shipped.
    """
    result = await db.execute(
        select(DaySummary)
        .where(DaySummary.search.op("@@")(func.plainto_tsquery("russian", query)))
        .order_by(DaySummary.day_date)
    )
    return list(result.scalars().all())
