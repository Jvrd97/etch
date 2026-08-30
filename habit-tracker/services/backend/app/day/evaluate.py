# [review:need-review] PHASE-03/90
# summary: the verdict of a day as one pure function — `evaluate_day(rule, facts)` with the reasons ordered not_closed → overtime → anchors → tasks, `skipped` out of both denominators and `work_minutes IS NULL` read as "не измерено" rather than as zero
"""
Whether a day was won, decided without a database.

Until now this answer was prose. `## День выигран?` was written by hand, read
back by a regular expression in two independent places (`life.py` and
`plan_server.py`), and the criterion itself existed in three incompatible
versions — `config.md` said all four tasks and eight hours, the `/day-close`
skill said anchors and eighty percent, `templates/summary.md` said ten hours.
Here it is one function over values, and the numbers it compares against come
from the `day_rule_set` row the day was actually lived under.

**The reasons are ordered by which one is worth being sent to repair.**
`not_closed → overtime → anchors → tasks`. Overtime is named before the anchors
not because work outranks health but because it *causes* them: anchors missed
after the ninth hour are a consequence, and pointing at them would send the
reader to fix the wrong thing. Anchors then come before tasks because a day that
failed on both is decided by the anchors. The priority of `config.md` (здоровье
> работа > отношения) is expressed elsewhere: all kinds of anchor weigh the
same, so the evening with the family drops the day exactly where the missed
street does.

**«Все якоря» — это все якоря, вписанные в план этого дня.** The denominator is
counted from lines with `kind='anchor'`, never from `rule.required_anchors`:
that tuple names the five edges a plan *may* mark as `rigidity='hard'`
(`app.day.rules`, `check_hard_rigidity`), and it bounds what a plan may harden
rather than listing what a day must contain. So a day whose plan carries no
anchor line counts 0/0 and passes, exactly as 0/0 tasks passes. It is a hole and
it is a deliberate one for now: an anchor exists only as a line of markdown
until `anchor_kind` / `day_anchor` arrive with `#92`, and a denominator of five
today would call every imported day of August lost for anchors nobody had
anywhere to write down. `tests/test_evaluate_day.py` pins both readings, so
changing this is a decision rather than a side effect.

**«Не закрыл» и «проиграл» — разные факты.** An unclosed day has no verdict at
all rather than a lost one: nobody has said what happened to it yet, and a
`lost` written by a clock rather than by a person is the one reading that makes
the whole record untrustworthy.

**`work_minutes IS NULL` means "не измерено", never zero.** Intervals of work
arrive with `#91`; until then most days carry no number. Such a day skips the
overtime check and says so in `missing_data`, because calling it clean would be
exactly as wrong as calling it overtime.

Nothing here touches the session, FastAPI or `app.crud`, by the same reasoning
as `app.health.aggregate`: the whole truth table runs in milliseconds under
`tests/test_evaluate_day.py`. Four of the five rules of the verdict live here.
The fifth is `verdict_override` — «день был выигран, просто я не отметил» — and
it is applied in `app.crud.summary.recompute_history`, because it is a fact of
the stored row rather than of the day's facts. It is one-directional: it turns
`lost` into `won` and never the reverse, and it leaves the reason this function
reached untouched.

Related: ADR-0014 (day in postgres), Р2 and Р8.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.day.marks import TaskCounts
from app.models.day import DayRuleSet

__all__ = [
    "MISSING_WORK_MINUTES",
    "REASON_ANCHORS",
    "REASON_NONE",
    "REASON_NOT_CLOSED",
    "REASON_OVERTIME",
    "REASON_TASKS",
    "VERDICT_LOST",
    "VERDICT_WON",
    "VERDICTS",
    "DayFacts",
    "Verdict",
    "evaluate_day",
]

# The two things a verdict can say. Absence of a verdict — the day nobody
# closed — is `None` and deliberately not a third word: it is not a judgement.
VERDICT_WON = "won"
VERDICT_LOST = "lost"
VERDICTS: tuple[str, ...] = (VERDICT_WON, VERDICT_LOST)

# Which condition was not met, machine-readable. The Russian a person reads is
# a label in `lib/day-format.ts`, the same way `mark.state` is handled: one
# vocabulary in the database, one translation on the screen.
REASON_NONE = ""
REASON_NOT_CLOSED = "not_closed"
REASON_OVERTIME = "overtime"
REASON_ANCHORS = "anchors"
REASON_TASKS = "tasks"

# What the day could not be judged on. One code for now — the minutes of work,
# which nothing measures until `#91`.
MISSING_WORK_MINUTES = "work_minutes"


@dataclass(frozen=True)
class DayFacts:
    """
    Everything the verdict is decided from, as plain values.

    Assembled by `app.crud.summary` out of rows that already exist: the marks of
    the plan for both counters, and `work_minutes` from outside — the day's
    intervals of work are `#91`, and until then the number arrives in the body
    of `POST /close` or not at all.
    """

    closed: bool
    tasks: TaskCounts
    anchors: TaskCounts
    work_minutes: int | None


@dataclass(frozen=True)
class Verdict:
    """
    The judgement of one day, and everything it was reached from.

    Carries `rule_set_id` because "по какому правилу считался этот день" is part
    of the answer, not context around it: the canon changed on 2026-08-17, and a
    verdict without the rule it was measured against cannot be re-read a month
    later.
    """

    verdict: str | None
    reason: str
    rule_set_id: int
    anchors_done: int
    anchors_total: int
    tasks_done: int
    tasks_total: int
    work_minutes: int | None
    missing_data: tuple[str, ...]


def _closed_of(counts: TaskCounts) -> tuple[int, int]:
    """
    How many lines were closed, of how many that still counted.

    `skipped` leaves the denominator — the rule is written once, in
    `app.day.marks`, and this is the only reading of it under which «3 из 3»
    after a cancelled meeting is not a lie in either direction.
    """
    return counts.done, counts.planned - counts.skipped


def _is_overtime(rule: DayRuleSet, work_minutes: int | None) -> bool:
    """
    Whether the day ran past the everyday ceiling of its canon.

    Compared against `work_cap_min` rather than `work_hard_cap_min`: the hard
    cap is the exception a day is allowed to reach for, not the line a normal
    day is judged by. Nine hours under the current canon (480/540) is overtime,
    which is exactly what the acceptance of `#90` requires.
    """
    if work_minutes is None or not rule.overtime_disqualifies:
        return False
    return work_minutes > rule.work_cap_min


def _tasks_are_short(rule: DayRuleSet, done: int, total: int) -> bool:
    """Whether the share of closed tasks is under the bar of the rule."""
    if total == 0:
        return False
    return Decimal(done) / Decimal(total) < rule.tasks_required_ratio


def evaluate_day(rule: DayRuleSet, facts: DayFacts) -> Verdict:
    """
    Judge one day against the canon it was lived under.

    Returns the verdict, the condition that was not met, and the counters the
    screen shows — so that a reader is never told only "день не выигран" and
    left to guess which of three things went wrong.

    `anchors_done < anchors_total` reads as «закрыты все якоря, вписанные в этот
    план», not «закрыты все пять якорей канона»: `rule.required_anchors` is
    deliberately not consulted, and a plan without a single anchor line gives
    0/0 and passes. The reasoning is in the module docstring; `#92` is where it
    changes.
    """
    anchors_done, anchors_total = _closed_of(facts.anchors)
    tasks_done, tasks_total = _closed_of(facts.tasks)
    missing_data = () if facts.work_minutes is not None else (MISSING_WORK_MINUTES,)

    def decided(verdict: str | None, reason: str) -> Verdict:
        return Verdict(
            verdict=verdict,
            reason=reason,
            rule_set_id=rule.id,
            anchors_done=anchors_done,
            anchors_total=anchors_total,
            tasks_done=tasks_done,
            tasks_total=tasks_total,
            work_minutes=facts.work_minutes,
            missing_data=missing_data,
        )

    if not facts.closed:
        return decided(None, REASON_NOT_CLOSED)
    if _is_overtime(rule, facts.work_minutes):
        return decided(VERDICT_LOST, REASON_OVERTIME)
    if anchors_done < anchors_total:
        return decided(VERDICT_LOST, REASON_ANCHORS)
    if _tasks_are_short(rule, tasks_done, tasks_total):
        return decided(VERDICT_LOST, REASON_TASKS)
    return decided(VERDICT_WON, REASON_NONE)
