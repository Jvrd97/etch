# [review:need-review] PHASE-03/90, PHASE-03/91, PHASE-03/142
# summary: the verdict of a day as one pure function — `evaluate_day(rule, facts)` with the reasons ordered not_closed → overtime → anchors → tasks, `skipped` out of both denominators and `work_minutes IS NULL` read as "не измерено" rather than as zero; since #142 the order of the reasons and the composition of the anchors come from the rule row (`verdict_rule`, `anchors`) instead of from constants
"""
Whether a day was won, decided without a database.

Until now this answer was prose. `## День выигран?` was written by hand, read
back by a regular expression in two independent places (`life.py` and
`plan_server.py`), and the criterion itself existed in three incompatible
versions — `config.md` said all four tasks and eight hours, the `/day-close`
skill said anchors and eighty percent, `templates/summary.md` said ten hours.
Here it is one function over values, and the numbers it compares against come
from the `day_rule_set` row the day was actually lived under.

**The reasons are ordered, and the order is the priority of `config.md`.**
`not_closed → overtime → anchors → tasks` — здоровье > работа > отношения. A
day that failed on both anchors and tasks says `anchors`, because that is the
one worth fixing first; a day that ran nine hours says `overtime` and stops,
because anchors missed *after* the ninth hour are a consequence and pointing at
them would send the reader to repair the wrong thing.

**Сама формула — строка таблицы, а не эта функция.** `verdict_rule.reason_order`
holds the order, `anchors` holds the composition of the anchors, and both are
read here rather than written here (`#142`). Dropping `anchors` from the order,
or adding a sixth anchor, is a new rule row: yesterday keeps the formula it was
lived under, exactly as it keeps the ceiling of hours. `not_closed` is not in
the list and cannot be — «никто не закрыл день» is the absence of a judgement,
not a condition of one.

**«Не закрыл» и «проиграл» — разные факты.** An unclosed day has no verdict at
all rather than a lost one: nobody has said what happened to it yet, and a
`lost` written by a clock rather than by a person is the one reading that makes
the whole record untrustworthy.

**`work_minutes IS NULL` means "не измерено", never zero.** Since `#91` the
number is measured by the `work_interval` rows of the day; a day with none of
them carries no number at all. Such a day skips the overtime check and says so
in `missing_data`, because calling it clean would be exactly as wrong as calling
it overtime.

Nothing here touches the session, FastAPI or `app.crud`, by the same reasoning
as `app.health.aggregate`: the whole truth table runs in milliseconds under
`tests/test_evaluate_day.py`, and there is no second place where a day is
judged.

Related: ADR-0014 (day in postgres), Р2 and Р8.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.day.marks import TaskCounts
from app.models.day import DayRuleSet

__all__ = [
    "DEFAULT_REASON_ORDER",
    "MISSING_ANCHOR_KINDS",
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
    "UnknownVerdictReason",
    "Verdict",
    "evaluate_day",
    "verdict_reasons",
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

# What the day could not be judged on. `work_minutes` is measured by nothing
# until `#91`; `anchor_kinds` — which anchors of the canon the day actually
# closed — until the plan names them or `day_anchor` arrives with `#92`.
MISSING_WORK_MINUTES = "work_minutes"
MISSING_ANCHOR_KINDS = "anchor_kinds"

# The order the conditions are weighed in when the rule row does not say. The
# priority of `config.md`: работа сначала (переработка снимает день целиком),
# затем якоря здоровья и отношений, затем задачи.
DEFAULT_REASON_ORDER: tuple[str, ...] = (REASON_OVERTIME, REASON_ANCHORS, REASON_TASKS)

# Key of `verdict_rule` the order is written under.
REASON_ORDER_KEY = "reason_order"


class UnknownVerdictReason(ValueError):
    """
    `verdict_rule.reason_order` names a condition nothing knows how to weigh.

    Loud rather than ignored. A silently dropped code would mean a canon a
    person wrote — «перестань снимать день за задачи» — applied in a way nobody
    asked for, and the whole point of keeping the formula in a row is that what
    is written there is what happens.
    """


def verdict_reasons(rule: DayRuleSet) -> tuple[str, ...]:
    """
    Which conditions lower a day under this canon, in the order they are weighed.

    A row with no formula — one built in memory, or written before `#142` — is
    judged by `DEFAULT_REASON_ORDER`: that is the canon as it stood, and reading
    an absent column as "ничто не снимает день" would silently turn every past
    day into a won one.
    """
    formula = rule.verdict_rule or {}
    raw = formula.get(REASON_ORDER_KEY)
    if raw is None:
        return DEFAULT_REASON_ORDER
    if not isinstance(raw, list):
        raise UnknownVerdictReason(
            f"verdict_rule.{REASON_ORDER_KEY} правила {rule.id} — не список: "
            f"{raw!r}. Формула вердикта это порядок условий, а не одно значение."
        )
    order = tuple(str(reason) for reason in raw)
    unknown = [reason for reason in order if reason not in DEFAULT_REASON_ORDER]
    if unknown:
        raise UnknownVerdictReason(
            f"verdict_rule.{REASON_ORDER_KEY} правила {rule.id} называет условия "
            f"{unknown}, которых нет: считать можно "
            f"{list(DEFAULT_REASON_ORDER)}. Опечатка в правиле молча не "
            "проглатывается — иначе день считался бы не по тому, что записано."
        )
    return order


@dataclass(frozen=True)
class DayFacts:
    """
    Everything the verdict is decided from, as plain values.

    Assembled by `app.crud.summary` out of rows that already exist: the marks of
    the plan for both counters, and `work_minutes` from the day's `work_interval`
    rows (`#91`). A day with no intervals falls back to the number `POST /close`
    carried, and to `None` when it carried none either.
    """

    closed: bool
    tasks: TaskCounts
    anchors: TaskCounts
    work_minutes: int | None
    # Which anchors of the canon the day actually closed, by kind. `None` means
    # «состав не измерен», not «ни одного»: the plan of the day names its
    # anchors only when its lines carry codes, and the catalogue that will
    # always name them (`day_anchor`) arrives with `#92`. An unmeasured
    # composition falls back to the counter and says so in `missing_data`,
    # exactly as an unmeasured `work_minutes` does.
    anchor_kinds: frozenset[str] | None = None


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
    # Anchors of the canon the day did not close, by kind — empty when the
    # composition was not measured. Named rather than counted: «не хватило
    # вечера с близкими» is what a reader can act on, «якоря 5/6» is not.
    missing_anchor_kinds: tuple[str, ...] = ()


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


def _anchors_not_closed(rule: DayRuleSet, facts: DayFacts) -> tuple[str, ...]:
    """
    Which anchors of the canon the day left open, by kind.

    The composition comes from the row (`anchors`), so adding «вечер с
    близкими» to the canon is an INSERT rather than an edit of this function —
    and a day lived under the older row keeps being judged by the five anchors
    it was lived under. An unmeasured composition answers with nothing at all;
    the counter of the plan's own anchor lines still has the last word.
    """
    if facts.anchor_kinds is None:
        return ()
    closed = facts.anchor_kinds
    return tuple(kind for kind in (rule.anchors or ()) if kind not in closed)


def evaluate_day(rule: DayRuleSet, facts: DayFacts) -> Verdict:
    """
    Judge one day against the canon it was lived under.

    Returns the verdict, the condition that was not met, and the counters the
    screen shows — so that a reader is never told only "день не выигран" and
    left to guess which of three things went wrong.

    Which conditions are weighed, and in which order, is `verdict_rule` of the
    same row: this function knows how to weigh each condition, and the row says
    which of them count. That is why a change of canon — «якоря больше не
    снимают день», «добавился шестой якорь» — is a new row and never a patch
    here.
    """
    anchors_done, anchors_total = _closed_of(facts.anchors)
    tasks_done, tasks_total = _closed_of(facts.tasks)
    missing_anchor_kinds = _anchors_not_closed(rule, facts)

    missing_data: tuple[str, ...] = ()
    if facts.work_minutes is None:
        missing_data += (MISSING_WORK_MINUTES,)
    # Only worth saying when the canon actually names anchors: a row that names
    # none has nothing to measure, and reporting a gap there would be noise
    # rather than a fact.
    if facts.anchor_kinds is None and rule.anchors:
        missing_data += (MISSING_ANCHOR_KINDS,)

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
            missing_anchor_kinds=missing_anchor_kinds,
        )

    # Не судить нечего: день, который никто не закрыл, вердикта не получает —
    # и это не условие формулы, а её отсутствие.
    if not facts.closed:
        return decided(None, REASON_NOT_CLOSED)

    lowered = {
        REASON_OVERTIME: _is_overtime(rule, facts.work_minutes),
        REASON_ANCHORS: anchors_done < anchors_total or bool(missing_anchor_kinds),
        REASON_TASKS: _tasks_are_short(rule, tasks_done, tasks_total),
    }
    for reason in verdict_reasons(rule):
        if lowered[reason]:
            return decided(VERDICT_LOST, reason)
    return decided(VERDICT_WON, REASON_NONE)
