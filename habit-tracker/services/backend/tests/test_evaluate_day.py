"""
The truth table of the verdict, without a database.

`evaluate_day` is the one place that decides whether a day was won, and every
case of `#90`'s acceptance is a row here: the day that is won, each of the three
ways of losing it, the day nobody closed, the day whose work was never measured,
and the two days that are judged differently only because the canon changed on
2026-08-17.

The order of the reasons is the point of half of these tests. `not_closed →
overtime → anchors → tasks` is not an implementation detail: overtime causes the
anchors that follow it to be missed, so naming the anchors would send the reader
to repair the wrong thing, and a day that failed on both anchors and tasks has
to say `anchors`.

What «все якоря» means is pinned here too, in
`test_a_day_whose_plan_has_no_anchor_is_not_lost_by_anchors`: the denominator is
the anchors of *this plan*, not the five of `rule.required_anchors`. That reading
is stated in the docstring of `app.day.evaluate` and it is a hole with a name —
a day nobody wrote an anchor into passes — so the test exists to make changing it
a decision rather than an accident.
"""

# [review:need-review] PHASE-03/90
# summary: pure tests of evaluate_day — the won day, tasks/anchors/overtime, the unclosed day, work that was never measured, the order of reasons, skipped leaving the denominator, and the legacy canon judging the same day differently
from datetime import date, time
from decimal import Decimal

from app.day.evaluate import (
    MISSING_WORK_MINUTES,
    REASON_ANCHORS,
    REASON_NONE,
    REASON_NOT_CLOSED,
    REASON_OVERTIME,
    REASON_TASKS,
    VERDICT_LOST,
    VERDICT_WON,
    DayFacts,
    evaluate_day,
)
from app.day.marks import TaskCounts
from app.day.rules import SEED_RULES, RuleSeed
from app.models.day import DayRuleSet

# Nine hours, the number the ticket names: over the everyday ceiling of the
# current canon (480) and under the legacy one (600).
NINE_HOURS_MIN = 540

LEGACY_SEED, CURRENT_SEED = SEED_RULES


def rule(seed: RuleSeed, rule_id: int) -> DayRuleSet:
    """A rule row as a value, built without a session."""
    return DayRuleSet(
        id=rule_id,
        valid_from=seed.valid_from,
        valid_to=seed.valid_to,
        timezone=seed.timezone,
        day_start_hour=seed.day_start_hour,
        work_cap_min=seed.work_cap_min,
        work_hard_cap_min=seed.work_hard_cap_min,
        work_stop_at=seed.work_stop_at,
        max_work_tasks=seed.max_work_tasks,
        tasks_required_ratio=seed.tasks_required_ratio,
        overtime_disqualifies=seed.overtime_disqualifies,
        workdays=list(seed.workdays),
        nocode_days=list(seed.nocode_days),
        required_anchors=list(seed.required_anchors),
        # Клауз роли (`#137`) переносится из сида, а не оставляется пустым:
        # незаполненное поле ORM-объекта — `None`, то есть «клауз выключён»
        # молча, и половина этих тестов проверяла бы не тот канон.
        role_clause_enabled=seed.role_clause_enabled,
        role_clause_roles=seed.role_clause_roles,
        note_md=seed.note_md,
    )


CURRENT = rule(CURRENT_SEED, 2)
LEGACY = rule(LEGACY_SEED, 1)


def counts(done: int, planned: int, skipped: int = 0) -> TaskCounts:
    """`done` of `planned`, the rest never reached."""
    return TaskCounts(
        planned=planned,
        done=done,
        failed=0,
        skipped=skipped,
        pending=planned - done - skipped,
    )


def facts(
    *,
    tasks: TaskCounts | None = None,
    anchors: TaskCounts | None = None,
    work_minutes: int | None = 400,
    closed: bool = True,
) -> DayFacts:
    """A day that was won, unless the caller breaks one thing about it."""
    return DayFacts(
        closed=closed,
        tasks=tasks if tasks is not None else counts(4, 4),
        anchors=anchors if anchors is not None else counts(5, 5),
        work_minutes=work_minutes,
    )


# --- the day that was won --------------------------------------------------


def test_all_tasks_all_anchors_and_work_under_the_ceiling_win_the_day() -> None:
    verdict = evaluate_day(CURRENT, facts())

    assert verdict.verdict == VERDICT_WON
    assert verdict.reason == REASON_NONE
    assert verdict.missing_data == ()
    # The screen shows which canon judged the day; the row carries the answer.
    assert verdict.rule_set_id == CURRENT.id
    assert (verdict.tasks_done, verdict.tasks_total) == (4, 4)
    assert (verdict.anchors_done, verdict.anchors_total) == (5, 5)


# --- the three ways of losing it -------------------------------------------


def test_three_tasks_of_four_lose_the_day_and_name_the_tasks() -> None:
    """The bar of the current canon is all of them, not most of them."""
    assert CURRENT.tasks_required_ratio == Decimal("1.00")

    verdict = evaluate_day(CURRENT, facts(tasks=counts(3, 4)))

    assert verdict.verdict == VERDICT_LOST
    assert verdict.reason == REASON_TASKS


def test_a_missing_evening_with_the_family_loses_the_day_by_anchors() -> None:
    """
    Отношения считаются наравне со здоровьем.

    The anchor `relationship` has no reason of its own: a third priority with a
    verdict reason to itself would outrank the first two. It is an anchor and it
    weighs what an anchor weighs. *Which* anchor was missed is a reading of the
    plan and its marks rather than an input to the verdict, so it is decoded by
    `app.crud.mark.missing_anchors` and checked in `test_day_close.py`.
    """
    verdict = evaluate_day(CURRENT, facts(anchors=counts(4, 5)))

    assert verdict.verdict == VERDICT_LOST
    assert verdict.reason == REASON_ANCHORS
    assert (verdict.anchors_done, verdict.anchors_total) == (4, 5)


def test_nine_hours_lose_the_day_whatever_the_tasks_say() -> None:
    """Переработка — не подвиг, а проигранный день; доля задач на это не влияет."""
    overworked = evaluate_day(CURRENT, facts(work_minutes=NINE_HOURS_MIN))
    assert (overworked.verdict, overworked.reason) == (VERDICT_LOST, REASON_OVERTIME)

    nothing_done = evaluate_day(
        CURRENT, facts(tasks=counts(0, 4), work_minutes=NINE_HOURS_MIN)
    )
    assert (nothing_done.verdict, nothing_done.reason) == (
        VERDICT_LOST,
        REASON_OVERTIME,
    )


# --- what is not known -----------------------------------------------------


def test_work_that_was_never_measured_cannot_be_overtime() -> None:
    """
    `work_minutes IS NULL` значит «не измерено», а не «ноль».

    Intervals of work arrive with `#91`; until then most days have no number,
    and calling those days clean would be as wrong as calling them overtime.
    The check is skipped and the gap is stated.
    """
    verdict = evaluate_day(CURRENT, facts(work_minutes=None))

    assert verdict.verdict == VERDICT_WON
    assert verdict.missing_data == (MISSING_WORK_MINUTES,)
    assert verdict.work_minutes is None


def test_a_day_nobody_closed_has_no_verdict_at_all() -> None:
    """«Не закрыл» и «проиграл» — разные факты, и это единственная разница."""
    verdict = evaluate_day(CURRENT, facts(tasks=counts(0, 4), closed=False))

    assert verdict.verdict is None
    assert verdict.reason == REASON_NOT_CLOSED


# --- the order of the reasons ----------------------------------------------


def test_anchors_are_named_before_tasks_when_both_failed() -> None:
    """Здоровье > работа: the reason a reader gets first is the health one."""
    verdict = evaluate_day(
        CURRENT,
        facts(tasks=counts(1, 4), anchors=counts(3, 5)),
    )

    assert verdict.reason == REASON_ANCHORS


def test_overtime_is_named_before_anchors() -> None:
    """
    The day was stopped by working too long; nothing after that is the reason.

    Anchors missed *because* the day ran long are a consequence, and naming
    them would send the reader to fix the wrong thing.
    """
    verdict = evaluate_day(
        CURRENT,
        facts(anchors=counts(3, 5), work_minutes=NINE_HOURS_MIN),
    )

    assert verdict.reason == REASON_OVERTIME


# --- what the denominator holds --------------------------------------------


def test_a_day_off_with_no_tasks_planned_is_not_lost_by_tasks() -> None:
    """Ноль из нуля — это правда, а не провал."""
    verdict = evaluate_day(CURRENT, facts(tasks=counts(0, 0)))

    assert verdict.verdict == VERDICT_WON
    assert (verdict.tasks_done, verdict.tasks_total) == (0, 0)


def test_a_day_whose_plan_has_no_anchor_is_not_lost_by_anchors() -> None:
    """
    «Все якоря» — все, вписанные в этот план, а не все пять якорей канона.

    The denominator comes from the lines of the plan, and `rule.required_anchors`
    is not consulted: it bounds what a plan may mark as `rigidity='hard'`, not
    what a day must contain. So a plan with no anchor line counts 0/0 and passes,
    which is the hole `#92` closes by making an anchor a thing rather than a line
    of markdown. Until then the behaviour is pinned rather than assumed.
    """
    verdict = evaluate_day(CURRENT, facts(anchors=counts(0, 0)))

    assert verdict.verdict == VERDICT_WON
    assert verdict.reason == REASON_NONE
    assert (verdict.anchors_done, verdict.anchors_total) == (0, 0)
    assert CURRENT.required_anchors


def test_a_skipped_task_leaves_the_denominator() -> None:
    """
    Четыре запланировано, одна перестала быть нужной, три закрыты — день выигран.

    The rule is written once, in `app.day.marks`; this is the reading of it the
    verdict depends on, and «3 из 3» после отменённой встречи не врёт ни в одну
    сторону.
    """
    verdict = evaluate_day(CURRENT, facts(tasks=counts(3, 4, skipped=1)))

    assert verdict.verdict == VERDICT_WON
    assert (verdict.tasks_done, verdict.tasks_total) == (3, 3)


# --- the canon that changed ------------------------------------------------


def test_the_same_day_is_won_under_the_legacy_canon_and_lost_under_the_current() -> (
    None
):
    """
    Именно ради этого канон — строка, а не константы в модуле.

    Four tasks of five and nine hours of work: 80% and ten hours were the bar
    until 2026-08-17, and all of them and eight hours are the bar after it.
    """
    lived = facts(tasks=counts(4, 5), work_minutes=NINE_HOURS_MIN)

    assert LEGACY.tasks_required_ratio == Decimal("0.80")
    assert LEGACY.work_cap_min == 600
    assert evaluate_day(LEGACY, lived).verdict == VERDICT_WON
    assert evaluate_day(LEGACY, lived).rule_set_id == LEGACY.id
    assert evaluate_day(CURRENT, lived).verdict == VERDICT_LOST


def test_the_seed_rules_are_the_two_canons_the_tests_assume() -> None:
    """A guard: these numbers are the acceptance, not decoration."""
    assert (LEGACY_SEED.valid_to, CURRENT_SEED.valid_from) == (
        date(2026, 8, 17),
        date(2026, 8, 17),
    )
    assert CURRENT_SEED.work_cap_min == 480
    assert CURRENT_SEED.work_stop_at == time(16, 0)
