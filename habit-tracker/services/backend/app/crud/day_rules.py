# [review:need-review] PHASE-03/137, PHASE-03/152
# summary: publishing a version of the day canon — closing the rule in force and inserting the new one inside one SAVEPOINT, refusing a start date that is not in the future, and turning the exclusion constraint's refusal into a sentence a person can read
"""
Changing the canon of a day without SQL, and without rewriting the past.

The whole module exists because of one property: a rule row that has already
judged days is never edited. The ceiling changed on 2026-08-17 and will change
again; the day of the 14th has to keep answering by the numbers it was lived
under. So there is exactly one way to change the canon — publish a new version
starting on a date that has not happened yet — and no way at all to edit a row
that is already in force. The API has no PUT and no PATCH, and that absence is
the feature.

Two things are worth reading closely.

**Closing and inserting are one SAVEPOINT.** The version in force ends where
the new one begins (`valid_to = valid_from`), and the two writes cannot be
allowed to happen separately: the insert alone is refused by `EXCLUDE`
(the old row is still open-ended), and the close alone leaves a date range that
no rule covers — a day with no canon, which has no verdict at all. On any
refusal the savepoint rolls back and the previous version keeps the `valid_to`
it had.

**The database decides about overlaps, this module only translates.** The
exclusion constraint on `daterange(valid_from, valid_to, '[)')` is the authority
because a service check is skipped by every writer that does not go through it.
What is added here is a sentence instead of `ExclusionViolation`: the person is
publishing a rule, not reading a stack trace.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.day.rules import active_rule, covers
from app.models.day import DayRuleSet
from app.schemas.day import DayRuleSetPublish

__all__ = [
    "OVERLAP_CONSTRAINT",
    "PUBLISH_LEAD_DAYS",
    "RuleOverlap",
    "RulePublishRejected",
    "RuleStartsTooEarly",
    "current_rule",
    "earliest_valid_from",
    "publish_rule_set",
]

# The exclusion constraint of `day_rule_set` (`app.models.day`). Matched against
# the driver's message so that only *this* refusal is reported as an overlap:
# any other integrity error is a different bug and must not be dressed up as
# one the person can fix by picking another date.
OVERLAP_CONSTRAINT = "excl_day_rule_set_no_overlap"

# How far ahead the earliest publishable date is. One day, and the reason is
# not caution: today is already being lived and may already be closed, so a
# version starting today would change the numbers a verdict was computed by.
PUBLISH_LEAD_DAYS = 1


class RulePublishRejected(ValueError):
    """
    A new version the system refuses to record, with the reason in words.

    A single base so the API maps the family once; the two subclasses differ
    only in what the person has to do next — pick a later date, or look at what
    is already published.
    """


class RuleStartsTooEarly(RulePublishRejected):
    """The version would start today or earlier, on days already judged."""


class RuleOverlap(RulePublishRejected):
    """The interval collides with one already recorded; the database said so."""


def earliest_valid_from(today: date) -> date:
    """
    The first date a new version may start on: tomorrow.

    A function rather than an expression at each call site because both the
    check and the screen quote this number, and a screen offering a date the
    check refuses is a form that cannot be submitted.
    """
    return today + timedelta(days=PUBLISH_LEAD_DAYS)


async def current_rule(db: AsyncSession) -> DayRuleSet:
    """
    The version in force, raising `NoRuleForDate` when the table is empty.

    Reuses `app.day.rules.active_rule`: "the last interval" is the definition
    everything else in the service already uses, and a second one here would
    let the rules screen and the day screen disagree about which rule is
    current.
    """
    return active_rule(await day_crud.list_rules(db))


def _covering_rule(rules: list[DayRuleSet], on: date) -> DayRuleSet | None:
    """The version in force on `on`, or None when no recorded interval holds it."""
    for rule in rules:
        if covers(rule, on):
            return rule
    return None


async def publish_rule_set(db: AsyncSession, draft: DayRuleSetPublish) -> DayRuleSet:
    """
    Record `draft` as the version in force from `draft.valid_from` onwards.

    Closes the version that covers that date at exactly that date — the
    interval is half-open, so the boundary day belongs to the new version and
    the two meet without a gap — and inserts the new row. Both writes live in
    one savepoint: a refusal leaves the table exactly as it was found.

    A version that starts where another one already starts, or in front of one
    already published for a later date, is not closed and not sandwiched: the
    insert goes to the database and comes back as `RuleOverlap`. Guessing what
    was meant would edit a row somebody published on purpose.

    Nothing already recorded is touched apart from the `valid_to` of the version
    being closed, and no verdict is recomputed: a day is judged by the rule that
    covered its date, and that rule keeps its numbers.

    One edge is worth knowing before changing `timezone` or `day_start_hour`.
    The day boundary the whole service reads comes from `active_rule`, which is
    "the last interval" — not "the interval covering today", because the
    boundary is what decides what today *is* (`#86`). A version published for a
    future date is the last interval from the moment it is inserted, so a change
    of the boundary hour starts deciding which day a moment belongs to before
    the date it was published for. Ceilings, anchors and the task bar are not
    affected: they are read through `rule_for_date`, which resolves by date.
    """
    rules = await day_crud.list_rules(db)
    # Reading the table is also how `local_date()` learns the boundary hour, so
    # "сегодня" below is the day the rest of the service is living in rather
    # than the calendar date of the process's clock.
    day_crud.publish_boundary(rules)

    today = today_local()
    earliest = earliest_valid_from(today)
    if draft.valid_from < earliest:
        raise RuleStartsTooEarly(
            f"Версия не может начинаться {draft.valid_from.isoformat()}: "
            f"сегодня {today.isoformat()}, а по сегодняшнему и прошедшим дням "
            "вердикты уже считаются по действующему правилу и не "
            f"пересчитываются. Самая ранняя дата — {earliest.isoformat()}."
        )

    covering = _covering_rule(rules, draft.valid_from)
    created = DayRuleSet(
        valid_from=draft.valid_from,
        valid_to=None,
        timezone=draft.timezone,
        day_start_hour=draft.day_start_hour,
        work_cap_min=draft.work_cap_min,
        work_hard_cap_min=draft.work_hard_cap_min,
        work_stop_at=draft.work_stop_at,
        max_work_tasks=draft.max_work_tasks,
        tasks_required_ratio=draft.tasks_required_ratio,
        overtime_disqualifies=draft.overtime_disqualifies,
        workdays=list(draft.workdays),
        nocode_days=list(draft.nocode_days),
        required_anchors=list(draft.required_anchors),
        role_clause_enabled=draft.role_clause_enabled,
        role_clause_roles=draft.role_clause_roles,
        note_md=draft.note_md,
    )

    try:
        async with db.begin_nested():
            if covering is not None and covering.valid_from < draft.valid_from:
                covering.valid_to = draft.valid_from
            db.add(created)
            await db.flush()
    except IntegrityError as error:
        if OVERLAP_CONSTRAINT not in str(error.orig):
            raise
        raise RuleOverlap(
            f"Период с {draft.valid_from.isoformat()} перекрывает уже "
            "записанный: на эти даты правило дня уже есть. Две версии на одну "
            "дату сделали бы вердикт того дня подбрасыванием монеты. Посмотрите "
            "историю версий и выберите дату после последней из них."
        ) from error

    return created
