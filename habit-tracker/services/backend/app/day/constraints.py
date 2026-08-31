# [review:need-review] PHASE-03/147
# summary: the eight rules a draft plan is judged by before it becomes rows — hard edges, the free evening, the ceiling on work, the ceilings on counts, health before work, the evening with the family, windows that do not overlap, and rows written only on the target day — each a pure function over a draft and a rule row, each answering with codes and ids so the result can go back into a repair prompt
"""
What a draft plan is allowed to be, decided before it is written.

**This is not the database's last line of defence, and it is not meant to be.**
`#87` put the row-level rules into CHECK constraints and the whole-document
rules into `plan_validate`, and both stay. What arrives here is a third thing:
a draft judged *before* the write, answering with rule codes and item ids rather
than with an `IntegrityError`. The difference matters because the answer has a
second reader — the repair prompt of `#148` — and "duplicate key value violates
unique constraint" is not something a model can act on.

The two ends do not overlap in meaning. The module rejects a draft; the database
refuses what slipped through. Four of the eight rules have no counterpart in
`#87` at all: `hard_edges_only` reaches past the shape of a line to the canon's
own list of edge kinds, `health_before_work` and `relationship_anchor_required`
are about the *order and composition* of a day, and `target_day_only` is about
which dates a generator is allowed to touch — the machine-readable form of
«сегодня сорвалось, неделю не трогаем».

**The strictness is asymmetric, and that is a decision rather than an
oversight.** A draft the machine produced is blocked. The same draft edited by a
person is stored and a `warn` violation is recorded beside it. A system that
refuses a person the right to edit their own day gets abandoned in a week; a
system that says nothing about a broken rule is useless. So `severity` is the
caller's to choose — `check_all` reports what is broken, `origin` decides what
happens next.

**Nothing here reads a clock and nothing here holds a number.** Every time, every
ceiling and every list of anchors comes off the `day_rule_set` row, because the
canon has already changed twice in a month and a constant in this module would
rewrite the rules of days already lived.

PII: a violation carries item ids, rule codes and numbers. The text of a line
never enters `detail` and never enters a message — a task can be named after a
diagnosis, and `plan_violation` rows outlive the plan they describe.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.day import rules as day_rules
from app.models.day import DayRuleSet

__all__ = [
    "DraftItem",
    "HEALTH_ANCHOR_CODES",
    "ORIGINS",
    "ORIGIN_AI",
    "ORIGIN_FALLBACK",
    "ORIGIN_HUMAN",
    "PlanDraft",
    "RULE_CODES",
    "RULE_FREE_EVENING_EMPTY",
    "RULE_HARD_EDGES_ONLY",
    "RULE_HEALTH_BEFORE_WORK",
    "RULE_NO_OVERLAP",
    "RULE_RELATIONSHIP_ANCHOR_REQUIRED",
    "RULE_TARGET_DAY_ONLY",
    "RULE_TASK_CAP",
    "RULE_WORK_CAP",
    "SEVERITIES",
    "SEVERITY_BLOCK",
    "SEVERITY_WARN",
    "Violation",
    "check_all",
    "check_free_evening_empty",
    "check_hard_edges_only",
    "check_health_before_work",
    "check_no_overlap",
    "check_relationship_anchor_required",
    "check_target_day_only",
    "check_task_cap",
    "check_work_cap",
]

# The eight codes, spelled once. A violation names one of these and the ids it
# was found on; the sentence a person reads is built from the pair, which is
# what keeps the answer usable by a model and free of the plan's own text.
RULE_HARD_EDGES_ONLY = "hard_edges_only"
RULE_FREE_EVENING_EMPTY = "free_evening_empty"
RULE_WORK_CAP = "work_cap"
RULE_TASK_CAP = "task_cap"
RULE_HEALTH_BEFORE_WORK = "health_before_work"
RULE_RELATIONSHIP_ANCHOR_REQUIRED = "relationship_anchor_required"
RULE_NO_OVERLAP = "no_overlap"
RULE_TARGET_DAY_ONLY = "target_day_only"

RULE_CODES: tuple[str, ...] = (
    RULE_HARD_EDGES_ONLY,
    RULE_FREE_EVENING_EMPTY,
    RULE_WORK_CAP,
    RULE_TASK_CAP,
    RULE_HEALTH_BEFORE_WORK,
    RULE_RELATIONSHIP_ANCHOR_REQUIRED,
    RULE_NO_OVERLAP,
    RULE_TARGET_DAY_ONLY,
)

# What a violation costs. `block` stops a write, `warn` is recorded beside one
# that went through — the asymmetry the module docstring names.
SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"
SEVERITIES: tuple[str, ...] = (SEVERITY_BLOCK, SEVERITY_WARN)

# Who produced the draft the violation was found in.
ORIGIN_AI = "ai"
ORIGIN_FALLBACK = "fallback"
ORIGIN_HUMAN = "human"
ORIGINS: tuple[str, ...] = (ORIGIN_AI, ORIGIN_FALLBACK, ORIGIN_HUMAN)

# Kinds of item the ceilings count.
KIND_TASK = "task"
KIND_ANCHOR = "anchor"

# Sections whose items the study ceiling counts.
SECTION_STUDY = "study"

# Codes that stand for the body rather than for the work: the walk outside and
# the strength block of `config.md`, plus the single `спорт` the current canon
# names as one anchor. A list of codes rather than a query, because the
# directory that will answer this properly is `#92` (`day_anchor`); when it
# lands, this constant becomes a lookup and goes away. The rule only requires
# the ones the canon actually names, so widening this list does not invent an
# obligation.
HEALTH_ANCHOR_CODES: tuple[str, ...] = ("спорт", "улица", "силовая")

SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class DraftItem:
    """
    One line of a draft, reduced to what the eight rules ask about.

    Deliberately not `PlanItemIn` and not `PlanItem`: a draft is judged in the
    same shape whether it came from a model, from the skeleton or from a person
    editing a stored plan, and a rule that had to know which of the three it was
    looking at would be three rules.

    `text_plain` is absent on purpose. Nothing here may build a message out of
    what the line says.
    """

    item_id: uuid.UUID
    kind: str
    rigidity: str
    code: str | None
    section_kind: str
    day_date: date
    starts_at: datetime | None = None
    ends_at: datetime | None = None


@dataclass(frozen=True)
class PlanDraft:
    """A whole draft: the day it is for, and the lines it is made of."""

    target: date
    items: tuple[DraftItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Violation:
    """
    One broken rule, in the shape that goes into `plan_violation` and into a
    repair prompt.

    `detail` holds ids and numbers and nothing else, which is checked by a test
    rather than left to discipline: these rows outlive the plan, and a task can
    be named after a diagnosis.
    """

    rule_code: str
    severity: str
    detail: dict[str, Any]
    message: str


def _zone(rule: DayRuleSet) -> ZoneInfo:
    """The wall clock the canon is written in."""
    return ZoneInfo(rule.timezone or "Europe/Berlin")


def _local_times(item: DraftItem, rule: DayRuleSet) -> tuple[time, time] | None:
    """
    The item's window as wall-clock ends, or None when it has no window.

    Converted into the canon's own zone rather than read off the stored
    datetime: the row is `timestamptz`, the rule's evening is a wall clock, and
    comparing the two in UTC is how a plan made abroad would be judged against
    somebody else's evening.
    """
    if item.starts_at is None or item.ends_at is None:
        return None
    zone = _zone(rule)
    return item.starts_at.astimezone(zone).time(), item.ends_at.astimezone(zone).time()


def _minutes(item: DraftItem) -> int:
    """How long the item's window is, or zero when it has none."""
    if item.starts_at is None or item.ends_at is None:
        return 0
    return int((item.ends_at - item.starts_at).total_seconds() // SECONDS_PER_MINUTE)


def _ids(items: Sequence[DraftItem]) -> list[str]:
    """Item ids as text, which is what `jsonb` and a prompt both take."""
    return [str(item.item_id) for item in items]


def check_hard_edges_only(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    Only the edges of the day may call themselves immovable.

    Which kinds those are is the canon's answer (`day_rule_set.hard_edge_kinds`),
    not this module's: the decision of 2026-08-30 allows hardness to the whole
    of `hard_point`, and a list frozen here would have to be edited to follow
    the next such decision.
    """
    allowed = set(day_rules.hard_edge_kinds(rule))
    offenders = [
        item
        for item in draft.items
        if item.rigidity == "hard" and item.kind not in allowed
    ]
    if not offenders:
        return []
    return [
        Violation(
            rule_code=RULE_HARD_EDGES_ONLY,
            severity=SEVERITY_BLOCK,
            detail={"item_ids": _ids(offenders), "allowed_kinds": sorted(allowed)},
            message=(
                f"{RULE_HARD_EDGES_ONLY}: {len(offenders)} пункт(ов) объявлены "
                f"жёсткими, но жёсткими бывают только края дня "
                f"({', '.join(sorted(allowed))}). Пункты: {', '.join(_ids(offenders))}"
            ),
        )
    ]


def check_free_evening_empty(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    Nothing with a window may reach into the free evening.

    The block is free because nothing is scheduled in it, so the rule is about
    windows rather than about kinds: a `free` item has no window at all (a CHECK
    of `#87` sees to that), and anything that does have one and lands here has
    scheduled the evening whether it meant to or not.
    """
    start, end = rule.free_evening_start, rule.free_evening_end
    offenders = []
    for item in draft.items:
        window = _local_times(item, rule)
        if window is None:
            continue
        item_start, item_end = window
        # Half-open on both sides: a window that ends exactly at the start of the
        # evening has not entered it, and one that starts exactly at its end is
        # after it.
        if item_start < end and item_end > start:
            offenders.append(item)
    if not offenders:
        return []
    return [
        Violation(
            rule_code=RULE_FREE_EVENING_EMPTY,
            severity=SEVERITY_BLOCK,
            detail={
                "item_ids": _ids(offenders),
                "free_evening_start": start.isoformat(),
                "free_evening_end": end.isoformat(),
            },
            message=(
                f"{RULE_FREE_EVENING_EMPTY}: {len(offenders)} пункт(ов) залезли "
                f"в свободный вечер {start.isoformat()}-{end.isoformat()}. "
                f"Пункты: {', '.join(_ids(offenders))}"
            ),
        )
    ]


def check_work_cap(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    The windows of work tasks may not add up past the canon's hard ceiling.

    `work_hard_cap_min` rather than `work_cap_min`: the softer number is the
    day's target and going over it is a fact for the verdict to weigh, while the
    harder one is what a *plan* may never propose. `overtime_lost_min` is never
    plannable at all — it is the amount at which a day is lost, and a generator
    that proposed it would be scheduling a defeat.
    """
    tasks = [item for item in draft.items if item.kind == KIND_TASK]
    planned = sum(_minutes(item) for item in tasks)
    if planned <= rule.work_hard_cap_min:
        return []
    return [
        Violation(
            rule_code=RULE_WORK_CAP,
            severity=SEVERITY_BLOCK,
            detail={
                "item_ids": _ids(tasks),
                "planned_minutes": planned,
                "work_hard_cap_min": rule.work_hard_cap_min,
                "overtime_lost_min": rule.overtime_lost_min,
            },
            message=(
                f"{RULE_WORK_CAP}: запланировано {planned} минут работы, потолок "
                f"{rule.work_hard_cap_min}. Переработка ({rule.overtime_lost_min} "
                "минут) не планируется никогда"
            ),
        )
    ]


def check_task_cap(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    The counts the canon caps: work tasks and items of study.

    Two ceilings and therefore up to two violations, not one merged complaint —
    the repair for each is a different line to remove, and a single message
    naming both would be repaired by deleting the wrong one.
    """
    violations: list[Violation] = []

    tasks = [item for item in draft.items if item.kind == KIND_TASK]
    if len(tasks) > rule.max_work_tasks:
        over = tasks[rule.max_work_tasks :]
        violations.append(
            Violation(
                rule_code=RULE_TASK_CAP,
                severity=SEVERITY_BLOCK,
                detail={
                    "item_ids": _ids(over),
                    "tasks": len(tasks),
                    "max_work_tasks": rule.max_work_tasks,
                },
                message=(
                    f"{RULE_TASK_CAP}: рабочих задач {len(tasks)}, канон разрешает "
                    f"{rule.max_work_tasks}. Лишние: {', '.join(_ids(over))}"
                ),
            )
        )

    study = [item for item in draft.items if item.section_kind == SECTION_STUDY]
    max_study = rule.max_study_items
    if max_study is not None and len(study) > max_study:
        over = study[max_study:]
        violations.append(
            Violation(
                rule_code=RULE_TASK_CAP,
                severity=SEVERITY_BLOCK,
                detail={
                    "item_ids": _ids(over),
                    "study_items": len(study),
                    "max_study_items": max_study,
                },
                message=(
                    f"{RULE_TASK_CAP}: учебных пунктов {len(study)}, канон "
                    f"разрешает {max_study}. Лишние: {', '.join(_ids(over))}"
                ),
            )
        )

    return violations


def _required_health_codes(rule: DayRuleSet) -> tuple[str, ...]:
    """
    Which health anchors this canon actually names.

    The intersection rather than the constant: requiring an anchor the rule row
    has never heard of would invent an obligation, and the point of `#142` is
    that obligations live in the row.
    """
    named = set(day_rules.anchors_of(rule)) | set(rule.required_anchors or ())
    return tuple(code for code in HEALTH_ANCHOR_CODES if code in named)


def check_health_before_work(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    The body comes before the work, in the plan and in the clock.

    «здоровье > работа» in the only form a machine can check: the health anchors
    the canon names are in the plan at all, and the ones that carry a window
    start before the first work task does. A day whose plan opens with work has
    already decided the priority the other way, whatever its prose says.
    """
    required = _required_health_codes(rule)
    if not required:
        return []

    by_code = {item.code: item for item in draft.items if item.code is not None}
    missing = [code for code in required if code not in by_code]
    if missing:
        return [
            Violation(
                rule_code=RULE_HEALTH_BEFORE_WORK,
                severity=SEVERITY_BLOCK,
                detail={"missing_codes": missing},
                message=(
                    f"{RULE_HEALTH_BEFORE_WORK}: в плане нет якорей "
                    f"{', '.join(missing)}. Здоровье стоит выше работы, значит "
                    "и в плане стоит раньше"
                ),
            )
        ]

    work_starts = [
        item.starts_at
        for item in draft.items
        if item.kind == KIND_TASK and item.starts_at is not None
    ]
    if not work_starts:
        return []
    first_work = min(work_starts)

    late: list[DraftItem] = []
    for code in required:
        anchor = by_code[code]
        # An anchor without a window is not late — it is unscheduled, which the
        # canon allows: «спорт» has no fixed hour in the map of the day.
        if anchor.starts_at is not None and anchor.starts_at >= first_work:
            late.append(anchor)
    if not late:
        return []
    return [
        Violation(
            rule_code=RULE_HEALTH_BEFORE_WORK,
            severity=SEVERITY_BLOCK,
            detail={
                "item_ids": _ids(late),
                "first_work_at": first_work.isoformat(),
            },
            message=(
                f"{RULE_HEALTH_BEFORE_WORK}: {len(late)} якорь(я) здоровья "
                f"начинаются не раньше первой рабочей задачи "
                f"({first_work.isoformat()}). Пункты: {', '.join(_ids(late))}"
            ),
        )
    ]


def _is_working_evening(target: date, rule: DayRuleSet) -> bool:
    """
    Whether the evening of `target` is one the canon treats as a working one.

    A day in `days_off` has no working evening; anything else does. Demanding an
    evening with the family on the weekday a release ships is not a right the
    system has, which is why the rule asks this question first rather than
    applying to every date.
    """
    days_off = set(rule.days_off or ())
    return target.isoweekday() not in days_off


def check_relationship_anchor_required(
    draft: PlanDraft, rule: DayRuleSet
) -> list[Violation]:
    """
    A non-working evening carries the evening with the family.

    The third priority of `config.md` reaching the same status as the first two.
    Without this rule it is the one that quietly disappears after the move off
    files: no anchor, no check, no column — and a priority nobody measures stops
    being a priority within a month.

    Two conditions gate it, both from the row: the canon has to require the
    anchor at all (`relationship_anchor_required`, false for `legacy`), and the
    evening has to be one the canon does not consider a working one.
    """
    if not rule.relationship_anchor_required:
        return []
    if _is_working_evening(draft.target, rule):
        return []

    code = day_rules.ANCHOR_RELATIONSHIP
    if any(item.code == code for item in draft.items):
        return []
    return [
        Violation(
            rule_code=RULE_RELATIONSHIP_ANCHOR_REQUIRED,
            severity=SEVERITY_BLOCK,
            detail={
                "target": draft.target.isoformat(),
                "missing_codes": [code],
                "evening_start": rule.relationship_evening_start.isoformat(),
                "evening_end": rule.relationship_evening_end.isoformat(),
            },
            message=(
                f"{RULE_RELATIONSHIP_ANCHOR_REQUIRED}: в нерабочий вечер "
                f"{draft.target.isoformat()} не поставлен якорь {code}"
            ),
        )
    ]


def _window_key(item: DraftItem) -> tuple[datetime, datetime]:
    """Sort key of a scheduled item; only called for items that have a window."""
    assert item.starts_at is not None and item.ends_at is not None
    return item.starts_at, item.ends_at


def check_no_overlap(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    Two windows may not claim the same minute.

    Pairwise over a sorted list rather than over the cross product: a plan is
    tens of lines, and the sorted sweep reports the *pair* that collided, which
    is the only form of this complaint anybody can act on.
    """
    scheduled = sorted(
        (item for item in draft.items if item.starts_at and item.ends_at),
        key=_window_key,
    )
    # Ends and starts as plain values: `scheduled` holds only items whose window
    # is set, and carrying that fact in a second list is what keeps the sweep
    # free of narrowing noise on every comparison.
    windows = [_window_key(item) for item in scheduled]
    pairs: list[tuple[str, str]] = []
    for index, (_, item_end) in enumerate(windows[:-1]):
        for offset, (other_start, _) in enumerate(windows[index + 1 :]):
            if other_start >= item_end:
                break
            other = scheduled[index + 1 + offset]
            pairs.append((str(scheduled[index].item_id), str(other.item_id)))
    if not pairs:
        return []
    return [
        Violation(
            rule_code=RULE_NO_OVERLAP,
            severity=SEVERITY_BLOCK,
            detail={"pairs": [list(pair) for pair in pairs]},
            message=(
                f"{RULE_NO_OVERLAP}: {len(pairs)} пар(ы) окон пересекаются: "
                + "; ".join(f"{left} × {right}" for left, right in pairs)
            ),
        )
    ]


def check_target_day_only(draft: PlanDraft, rule: DayRuleSet) -> list[Violation]:
    """
    A generation writes rows on the target day and on no other.

    The machine-readable form of «сегодня сорвалось — неделю не трогаем». A
    generator that repaired tomorrow by rearranging the day after it would be
    doing exactly what the rule of the week forbids, and the only way to find
    that out afterwards would be to diff two snapshots.

    `rule` is unused and stays in the signature: `check_all` calls the eight
    functions through one shape, and a rule that opted out of the argument would
    make that dispatch special-case itself.
    """
    del rule
    offenders = [item for item in draft.items if item.day_date != draft.target]
    if not offenders:
        return []
    return [
        Violation(
            rule_code=RULE_TARGET_DAY_ONLY,
            severity=SEVERITY_BLOCK,
            detail={
                "item_ids": _ids(offenders),
                "target": draft.target.isoformat(),
                "dates": sorted({item.day_date.isoformat() for item in offenders}),
            },
            message=(
                f"{RULE_TARGET_DAY_ONLY}: {len(offenders)} пункт(ов) написаны не "
                f"на {draft.target.isoformat()}. Пункты: {', '.join(_ids(offenders))}"
            ),
        )
    ]


# The eight, in the order a reader of the result would want them: what the day
# is shaped like, then how much of it is spoken for, then whose day it is.
CHECKS = (
    check_hard_edges_only,
    check_free_evening_empty,
    check_work_cap,
    check_task_cap,
    check_health_before_work,
    check_relationship_anchor_required,
    check_no_overlap,
    check_target_day_only,
)


def check_all(
    draft: PlanDraft, rule: DayRuleSet, *, severity: str = SEVERITY_BLOCK
) -> list[Violation]:
    """
    Every rule the draft breaks, at the severity the caller is entitled to.

    All of them rather than the first: the result goes back into a repair prompt,
    and a prompt that fixes one rule per round trip costs one model call per
    mistake. `severity` is the asymmetry — a machine's draft is judged at
    `block`, a person's edit at `warn`, and the rules themselves know nothing
    about which they are looking at.
    """
    found: list[Violation] = []
    for check in CHECKS:
        found.extend(check(draft, rule))
    if severity == SEVERITY_BLOCK:
        return found
    return [
        Violation(
            rule_code=violation.rule_code,
            severity=severity,
            detail=violation.detail,
            message=violation.message,
        )
        for violation in found
    ]
