# [review:need-review] PHASE-03/90, PHASE-03/91, PHASE-03/143
# summary: persistence of the day's итог — the facts gathered from rows that already exist (`work_minutes` measured by the day's intervals, the number sent at a touch only where nothing measured it), the two touches that move one row from `open` through `reviewed` to `closed` with an idempotency key each, the whole-history recompute that never touches an imported verdict, and full-text search over the prose
"""
Database access for the итог of a day.

**Закрытие идёт в два касания, но пишет одну строку.** `review_day` — факт по
рабочим задачам около 15:40, `close_day` — якоря, вердикт и стрик вечером. Обе
двигают `stage` одной и той же строки (`open → reviewed → closed`), а не
заводят вторую: двух хранилищ итога в одной базе быть не должно, а «день
наполовину закрыт» — это стадия, а не набор случайно заполненных полей.

**Пропуск первого касания — обычный день.** Никакой ошибки: стадия прыгает
`open → closed`, а ответ несёт `review_skipped`, посчитанный по пустому
`reviewed_at`. Отдельной колонки под этот признак нет — она была бы вторым
ответом на тот же вопрос.

**Повтор с тем же ключом ничего не пишет; повтор с другим — перезакрывает.**
Первый возвращает 200 и ту же строку, и `updated_at` не сдвигается, потому что
записи не происходит вовсе. Второй пересчитывает вердикт и стрик той же чистой
функцией и оставляет ровно одну строку на дату. Пересчёт идемпотентен по
построению: `evaluate_day` — функция от состояния дня, а не от числа нажатий.

Цена одной колонки на ключ вместо журнала ключей названа вслух: перезакрытие
затирает прежний `final_idempotency_key`, так что повтор **старого** ключа после
перезакрытия закроет день ещё раз вместо того, чтобы узнать себя. Строка от
этого всё равно остаётся одна, а вердикт — тем же.

**`null` в теле касания — «не трогать».** Вечернее закрытие, не назвавшее
рабочие минуты, оставляет цифру, записанную в 15:40; перезакрытие, не назвавшее
переопределение, не отменяет записку человека.

**Живой блок для незакрытого дня остаётся живым.** День на стадии `reviewed`
отвечает пересчётом по текущим отметкам, а не счётчиками, замороженными в
15:40, — иначе отметка, поставленная в 17:00, не была бы видна до вечера.

**Импортированные вердикты не пересчитываются никогда.** `recompute_history`
re-judges rows written here (`source='close'`) and only ever writes the derived
`streak_after` onto rows that arrived as prose (`source='import'`). Смена канона
2026-08-17 иначе задним числом переписала бы всё, что было до неё — and a
verdict recomputed from marks that were never made would be zeros pretending to
be history.

**Минуты работы берутся у интервалов, а не у того, кто закрывал день.**
`work_interval` (`#91`) is a measurement; the `work_minutes` of `POST /close` is
somebody's estimate typed into a field. Where both exist the measurement wins,
and where there are no intervals at all the estimate is used as it always was —
so an imported day and a day closed before the agent existed keep their number.
A day with neither says `None`, which is «не измерено» and not zero.

**Стрик считается в одном месте.** `close_day` writes the row and then folds
`app.day.streak.step_streak` over every day in date order. A running number kept
per row and patched on write would drift the first time a past day is closed
out of order, which is exactly what closing yesterday at 00:30 is.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import work_interval as work_crud
from app.day.evaluate import VERDICT_WON, DayFacts, Verdict, evaluate_day
from app.day.rules import resolve_rule
from app.day.streak import step_streak
from app.models.day import DayRuleSet
from app.models.mark import PlanMark
from app.models.plan import DayPlan
from app.models.summary import (
    SOURCE_CLOSE,
    STAGE_CLOSED,
    STAGE_OPEN,
    STAGE_REVIEWED,
    DaySummary,
)
from app.schemas.summary import DayCloseIn, DayReviewIn, DaySummaryResponse

__all__ = [
    "KeyBelongsToAnotherDay",
    "close_day",
    "facts_of",
    "get_summary",
    "recompute_history",
    "review_day",
    "search",
    "summary_for",
]

# The fields a touch carries that are simply written down as said. Spelled once,
# because both touches carry the same set and a second list would drift from
# this one the first time a question is added to the closing.
SAID_FIELDS: tuple[str, ...] = (
    "work_minutes",
    "body_md",
    "wrote_from_scratch",
    "education_debt",
    "reviewed_today",
)


class KeyBelongsToAnotherDay(Exception):
    """
    The `Idempotency-Key` was already spent — on a different date.

    Not a replay and not a fresh touch: answering 200 with somebody else's day
    would be a lie, and writing it would break the promise that one key writes
    at most once. The API turns this into 409, the way `POST /daily-summary`
    already does for a key reused on another date.
    """

    def __init__(self, spent_on: date) -> None:
        super().__init__(
            f"этот Idempotency-Key уже применён к дню {spent_on.isoformat()}; "
            "для другого дня нужен новый ключ"
        )
        self.spent_on = spent_on


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

    `work_minutes` is passed in rather than read here, because the two callers
    resolve it differently: a live preview measures the intervals as they stand,
    a recompute takes the sum it already read for the whole history at once.
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
    """
    return DaySummaryResponse(
        day_date=row.day_date,
        closed=True,
        stage=row.stage,
        reviewed_at=row.reviewed_at,
        # A day closed in one touch, said out loud. An imported day is excluded
        # rather than counted as skipped: the two touches did not exist when it
        # was lived, so «ревью не было» would be an answer to a question nobody
        # asked.
        review_skipped=row.source == SOURCE_CLOSE and row.reviewed_at is None,
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
    on: date,
    verdict: Verdict,
    *,
    missing_anchors: list[str],
    stored: DaySummary | None,
) -> DaySummaryResponse:
    """
    The итог of a day nobody has closed: counted live, judged by nothing.

    `stored` is the half-closed row when the 15:40 touch already happened. Its
    counters are deliberately *not* used — they were true at 15:40 and a mark
    put down at 17:00 has to show — but everything it wrote down stays visible,
    and its `stage` is what lets the screen say «вердикт будет вечером» rather
    than «день не закрыт».
    """
    return DaySummaryResponse(
        day_date=on,
        closed=False,
        stage=STAGE_OPEN if stored is None else stored.stage,
        reviewed_at=None if stored is None else stored.reviewed_at,
        rule_set_id=verdict.rule_set_id,
        verdict=verdict.verdict,
        verdict_reason=verdict.reason,
        anchors_done=verdict.anchors_done,
        anchors_total=verdict.anchors_total,
        tasks_done=verdict.tasks_done,
        tasks_total=verdict.tasks_total,
        work_minutes=verdict.work_minutes,
        wrote_from_scratch=None if stored is None else stored.wrote_from_scratch,
        education_debt=None if stored is None else stored.education_debt,
        reviewed_today=None if stored is None else stored.reviewed_today,
        body_md="" if stored is None else stored.body_md,
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
    if stored is not None and stored.stage == STAGE_CLOSED:
        return _to_response(stored, missing_anchors=missing)
    # The intervals of the day are the measurement; a day that is not closed has
    # no other source for the number beyond whatever the 15:40 touch estimated,
    # and reading them here is what lets the screen show «уже 7 ч 40 мин» before
    # anybody presses «закрыть день».
    measured = await work_crud.minutes_for_day(db, on)
    estimated = None if stored is None else stored.work_minutes
    facts = facts_of(
        plan,
        marks,
        work_minutes=measured if measured is not None else estimated,
        closed=False,
    )
    return _preview(
        on, evaluate_day(rule, facts), missing_anchors=missing, stored=stored
    )


def _said(body: DayReviewIn | DayCloseIn) -> dict[str, Any]:
    """
    What the touch actually said, with the silences left out.

    A field left `null` is «не трогать», so it never reaches the upsert and the
    value already in the row survives. That is what lets the evening touch omit
    the minutes the 15:40 one measured, and a перезакрытие omit the override
    somebody made an hour earlier without erasing its note.
    """
    values: dict[str, Any] = {
        name: getattr(body, name)
        for name in SAID_FIELDS
        if getattr(body, name) is not None
    }
    if isinstance(body, DayCloseIn) and body.verdict_override is not None:
        # The pair moves together: an override and the note it stands on are one
        # statement, and the CHECK on the table refuses to see them apart.
        values["verdict_override"] = body.verdict_override
        values["verdict_override_note"] = body.verdict_override_note
    return values


async def _store(
    db: AsyncSession, on: date, rule_set_id: int, values: dict[str, Any]
) -> None:
    """
    Write what the person said about the day, and nothing the machine decides.

    The verdict, its reason and the counters are deliberately absent here:
    `recompute_history` writes them for this row along with every other, so the
    judgement is made in exactly one place. A row inserted for the first time
    gets them from the column defaults and is judged a moment later.
    """
    row: dict[str, Any] = {
        "day_date": on,
        "rule_set_id": rule_set_id,
        "source": SOURCE_CLOSE,
        **values,
    }
    statement = pg_insert(DaySummary).values(**row)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[DaySummary.day_date],
            set_={key: statement.excluded[key] for key in row if key != "day_date"},
        )
    )
    await db.flush()
    # The upsert went past the ORM, so a row already loaded in this session
    # still carries the values it had a moment ago. `recompute_history` reads
    # through the ORM right after, and a stale object there would write the old
    # numbers back over the ones just stored — which is exactly what a second
    # touch of the same day is.
    stale = await db.get(DaySummary, on)
    if stale is not None:
        await db.refresh(stale)


async def _spent_review_key(db: AsyncSession, key: str) -> DaySummary | None:
    """The row this review key already wrote, if it wrote one."""
    result = await db.execute(
        select(DaySummary).where(DaySummary.review_idempotency_key == key)
    )
    return result.scalar_one_or_none()


async def _spent_final_key(db: AsyncSession, key: str) -> DaySummary | None:
    """The row this final key already wrote, if it wrote one."""
    result = await db.execute(
        select(DaySummary).where(DaySummary.final_idempotency_key == key)
    )
    return result.scalar_one_or_none()


async def _answer(db: AsyncSession, on: date, rule: DayRuleSet) -> DaySummaryResponse:
    """The итог of `on` as both touches and `GET /day/{date}` report it."""
    plan = await plan_crud.get_plan(db, on)
    marks = await mark_crud.list_marks(db, on)
    return await summary_for(db, on, rule, plan, marks)


async def review_day(
    db: AsyncSession,
    on: date,
    body: DayReviewIn,
    *,
    idempotency_key: str | None = None,
) -> DaySummaryResponse:
    """
    Касание около 15:40: записать факт по работе, не вынося вердикта.

    Стадия становится `reviewed` — и никогда не откатывает уже закрытый день
    назад: ревью, пришедшее после вечернего закрытия, уточняет цифры, а не
    отменяет закрытие.

    Вердикта после этого касания по-прежнему нет: `verdict` остаётся NULL, и это
    «рано», а не «проиграл». Пересчёт всё равно запускается — он нужен дню,
    который уже был закрыт и которому это касание поправило рабочие минуты.
    """
    day = await day_crud.ensure_day(db, on)
    rule = await day_crud.rule_for_date(db, on)

    if idempotency_key is not None:
        seen = await _spent_review_key(db, idempotency_key)
        if seen is not None:
            if seen.day_date != day.day_date:
                raise KeyBelongsToAnotherDay(seen.day_date)
            # Повтор: ответ тот же, записи нет, `updated_at` на месте.
            return await _answer(db, day.day_date, rule)

    stored = await get_summary(db, day.day_date)
    values = _said(body)
    values["stage"] = (
        STAGE_CLOSED
        if stored is not None and stored.stage == STAGE_CLOSED
        else STAGE_REVIEWED
    )
    values["reviewed_at"] = func.now()
    if idempotency_key is not None:
        values["review_idempotency_key"] = idempotency_key

    await _store(db, day.day_date, rule.id, values)
    await recompute_history(db)
    return await _answer(db, day.day_date, rule)


async def close_day(
    db: AsyncSession,
    on: date,
    body: DayCloseIn,
    *,
    idempotency_key: str | None = None,
) -> DaySummaryResponse:
    """
    Вечернее касание: закрыть день `on`, посчитать вердикт и пересчитать стрик.

    The day is judged against the rule it was lived under, not the rule in force
    now — closing yesterday at 00:30 and closing a day of last month have to
    give the same answer they would have given then. Закрытие вчерашнего дня
    задним числом поэтому же пересчитывает стрик всей истории, а не только своей
    даты.

    Первого касания могло не быть: стадия тогда прыгает `open → closed`, и
    ответ несёт `review_skipped`. Это обычный день, а не ошибка.

    Повтор с тем же ключом ничего не пишет. Повтор с другим ключом на закрытый
    день — перезакрытие: вердикт и стрик считаются заново той же чистой
    функцией, вторая строка не появляется.
    """
    day = await day_crud.ensure_day(db, on)
    rule = await day_crud.rule_for_date(db, on)

    if idempotency_key is not None:
        seen = await _spent_final_key(db, idempotency_key)
        if seen is not None:
            if seen.day_date != day.day_date:
                raise KeyBelongsToAnotherDay(seen.day_date)
            return await _answer(db, day.day_date, rule)

    values = _said(body)
    values["stage"] = STAGE_CLOSED
    if idempotency_key is not None:
        values["final_idempotency_key"] = idempotency_key

    await _store(db, day.day_date, rule.id, values)
    await recompute_history(db)
    return await _answer(db, day.day_date, rule)


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

    **Интервалы сильнее числа, введённого при закрытии.** A day whose
    `work_interval` rows add up gets their sum written onto its row; a day with
    no intervals keeps whatever `POST /close` said, including `None`. That is
    what makes the intervals the source of `work_minutes` without breaking a
    history closed before they existed.

    **Переопределение переживает пересчёт.** `verdict_override` replaces the
    verdict and leaves `verdict_reason` as the machine reached it: a person
    re-reading the day in a month has to see what was disagreed with.
    """
    rules = await day_crud.list_rules(db)
    # Every day that has intervals, in one read: this walks the whole history,
    # and a query per row would turn a recompute into a query per day.
    measured = await work_crud.minutes_by_day(db)
    result = await db.execute(select(DaySummary).order_by(DaySummary.day_date))
    streak = 0

    for row in result.scalars().all():
        closed = row.stage == STAGE_CLOSED
        if row.source == SOURCE_CLOSE:
            plan = await plan_crud.get_plan(db, row.day_date)
            marks = await mark_crud.list_marks(db, row.day_date)
            # Measurement over estimate, and the row is rewritten to what the
            # verdict was reached from — otherwise the screen would show one
            # number and the judgement stand on another.
            row.work_minutes = measured.get(row.day_date, row.work_minutes)
            facts = facts_of(plan, marks, work_minutes=row.work_minutes, closed=closed)
            verdict = evaluate_day(resolve_rule(rules, row.day_date), facts)
            # Переопределение действует только на закрытом дне: «выигран» на
            # строке, до вечера которой ещё не дошли, было бы вердиктом,
            # вынесенным раньше срока, и CHECK таблицы его и не принял бы.
            row.verdict = (
                VERDICT_WON if closed and row.verdict_override else verdict.verdict
            )
            row.verdict_reason = verdict.reason
            row.anchors_done = verdict.anchors_done
            row.anchors_total = verdict.anchors_total
            row.tasks_done = verdict.tasks_done
            row.tasks_total = verdict.tasks_total
            row.missing_data = list(verdict.missing_data)
        streak = step_streak(streak, row.day_date, row.verdict)
        # Стрик — свойство закрытого дня. Полузакрытый день его не рвёт и не
        # удлиняет (его вердикт NULL), но и цифры не носит: «стрик после дня,
        # который ещё не кончился» — не ответ.
        row.streak_after = streak if closed else None

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
