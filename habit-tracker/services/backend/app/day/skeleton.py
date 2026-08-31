# [review:need-review] PHASE-03/147
# summary: the deterministic plan — `skeleton_plan(target, rule, carryovers, signals)` builds a day out of the canon's own edges, a training slot, the carryovers in priority order and the evening with the family, and passes `check_all` by construction because every number in it comes off the rule row
"""
The plan that exists when the model does not.

The insurance is shipped before the thing it insures. After this module a day is
never left without a plan: no answer from a model, a timeout, a malformed JSON,
an unpaid subscription — the day still opens with edges, a training slot and
whatever was carried over, and `#148` gets to be an improvement rather than a
single point of failure.

**The skeleton passes the eight rules by construction, not by luck.** It is
assembled out of the same row they are checked against: the edges are the
canon's edges, the ceiling on work is the canon's ceiling, the free evening is
left empty because nothing is ever placed into it, and the evening with the
family is added exactly when `relationship_anchor_required` says a non-working
evening needs it. A test asserts the result against `check_all` on both seeded
rows, which is what keeps that claim true after the next edit rather than on the
day it was written.

**Carryovers are placed in priority order and never past the ceiling.** What
does not fit is not squeezed in: the list is cut, and the day the plan describes
is one a person can actually live. Overflow is the caller's to see — the return
carries what was left out, so nothing disappears silently.

Nothing here reads a clock: `target` is an argument, and the wall-clock times
come off the rule. `local_date()` is the only answer to «какое сегодня число»
and it is asked by the endpoint, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.day import rules as day_rules
from app.day.constraints import DraftItem, PlanDraft
from app.models.day import DayRuleSet

__all__ = [
    "Carryover",
    "SKELETON_SOURCE",
    "SkeletonPlan",
    "Signals",
    "skeleton_plan",
]

# What `day_plan.source` says about a plan this module produced. `manual` of the
# three the column allows, because `day-open` is the model's path and `import` is
# the historic one: a skeleton is neither, and mislabelling it would make the
# question "how often did the fallback fire" unanswerable.
SKELETON_SOURCE = "manual"

# Kinds and rigidity of the lines the skeleton writes, named once.
KIND_ANCHOR = "anchor"
KIND_TASK = "task"
RIGIDITY_HARD = "hard"
RIGIDITY_SOFT = "soft"

SECTION_ANCHORS = "anchors"
SECTION_TRAINING = "training"
SECTION_WORK = "work"
SECTION_FREE = "free"

# How long a carried task is given when it does not say. Not a time of day and
# not a ceiling — a default duration, and the smallest unit of work the plans
# have ever used. The ceiling it is measured against is the canon's.
DEFAULT_TASK_MINUTES = 60

# How long the training slot lasts. Same nature as above: a length, not an hour.
TRAINING_MINUTES = 60

# How much room an edge of the day occupies. An edge is a moment, but the CHECK
# of `#87` refuses a zero-length window (`ends_at > starts_at`), so it gets the
# smallest window that exists.
EDGE_MINUTES = timedelta(minutes=1)

# Codes of the lines the skeleton writes. The Russian a person reads is a label
# of the screen; these are what a rule points at.
CODE_WAKE = "подъём"
CODE_SPORT = "спорт"
CODE_WORK_START = "старт работы"
CODE_REVIEW = "ревью"
CODE_BEDTIME = "отбой"


@dataclass(frozen=True)
class Carryover:
    """
    One task the previous day did not finish.

    `priority` is the order the caller decided; the skeleton places by it and
    does not re-rank. `carry_count` travels with the task so that the rule of
    three carryovers (`#95`) has something to count — this module does not
    enforce it, it only refuses to lose the number.
    """

    text_md: str
    priority: int
    minutes: int = DEFAULT_TASK_MINUTES
    done_criterion: str | None = None
    quarter_goal_id: int | None = None
    unlinked_reason: str | None = None
    carried_from_item_id: uuid.UUID | None = None
    carry_count: int = 0


@dataclass(frozen=True)
class Signals:
    """
    What the caller knows about the target day that the rule row does not.

    Empty is a valid value and the common one: the skeleton's whole point is
    that it works when nothing is known. `is_training_day` defaults to true
    because the training slot is part of the canon's shape of a day, and a day
    with no training planned is the exception a caller has to state.
    """

    is_training_day: bool = True
    training_note: str | None = None


@dataclass(frozen=True)
class SkeletonSection:
    """One section of the built plan, with the lines it holds."""

    kind: str
    title: str
    items: tuple[DraftItem, ...] = field(default_factory=tuple)
    texts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkeletonPlan:
    """
    The built plan: the draft the rules judge, and what did not fit.

    Two fields rather than one because the second is the honest half. A skeleton
    that silently dropped the fifth carryover would look like a plan for a day
    somebody could live, and be a plan that lost work.
    """

    draft: PlanDraft
    sections: tuple[SkeletonSection, ...]
    overflow: tuple[Carryover, ...]


def _at(target: date, when: time, rule: DayRuleSet) -> datetime:
    """
    A wall-clock hour of `target`, pinned to the canon's own zone.

    The rule's times are wall clock and the rows are `timestamptz`; pinning here
    rather than at the edge of the module is what keeps the plan of a day spent
    abroad judged against the canon's evening rather than against a UTC one.
    """
    return datetime.combine(target, when, tzinfo=ZoneInfo(rule.timezone))


def _anchor(
    target: date,
    rule: DayRuleSet,
    code: str,
    starts_at: datetime | None,
    ends_at: datetime | None,
    *,
    rigidity: str = RIGIDITY_HARD,
) -> DraftItem:
    """One edge of the day as a draft line."""
    return DraftItem(
        item_id=uuid.uuid4(),
        kind=KIND_ANCHOR,
        rigidity=rigidity,
        code=code,
        section_kind=SECTION_ANCHORS,
        day_date=target,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def _edges(target: date, rule: DayRuleSet) -> list[DraftItem]:
    """
    The hard edges, as the canon draws them.

    Each one is a moment rather than a stretch, so each gets a minute-long
    window: a zero-length window is refused by the CHECK of `#87`
    (`ends_at > starts_at`), and a longer one would start claiming time the edge
    does not actually occupy.
    """
    edges: list[DraftItem] = []
    for code, when in (
        (CODE_WAKE, rule.wake_at),
        (CODE_WORK_START, rule.work_start),
        (CODE_REVIEW, rule.review_at),
        (CODE_BEDTIME, rule.bedtime_max),
    ):
        start = _at(target, when, rule)
        edges.append(_anchor(target, rule, code, start, start + EDGE_MINUTES))
    return edges


def _training(target: date, rule: DayRuleSet, signals: Signals) -> list[DraftItem]:
    """
    The training slot, placed before work so that the body comes first.

    Ends where work starts rather than at a fixed hour: `health_before_work` asks
    whether sport begins before the first work task, and a slot measured back
    from the canon's own `work_start` satisfies that on any row, including one
    whose start of work moves.
    """
    if not signals.is_training_day:
        return []
    ends_at = _at(target, rule.work_start, rule)
    starts_at = ends_at - timedelta(minutes=TRAINING_MINUTES)
    return [
        _anchor(
            target,
            rule,
            CODE_SPORT,
            starts_at,
            ends_at,
            rigidity=RIGIDITY_SOFT,
        )
    ]


def _relationship_evening(target: date, rule: DayRuleSet) -> list[DraftItem]:
    """
    The evening with the family, on the evenings the canon asks for one.

    Placed with no window at all. The stretch the rule names
    (`relationship_evening_start`..`_end`) overlaps the free evening on both
    seeded rows, and a windowed line there would break `free_evening_empty` —
    which is the correct outcome: the evening with the family is a commitment,
    not an appointment, and scheduling it would be the exact
    «перезакручивание» `config.md` forbids.
    """
    if not rule.relationship_anchor_required:
        return []
    if target.isoweekday() not in set(rule.days_off or ()):
        return []
    return [
        _anchor(
            target,
            rule,
            day_rules.ANCHOR_RELATIONSHIP,
            None,
            None,
            rigidity=RIGIDITY_SOFT,
        )
    ]


def _work(
    target: date,
    rule: DayRuleSet,
    carryovers: tuple[Carryover, ...],
) -> tuple[list[DraftItem], list[Carryover], list[Carryover]]:
    """
    The carried tasks, laid between the start of work and the canon's stop.

    Two ceilings decide what fits: `max_work_tasks` on the count and
    `work_hard_cap_min` on the sum of the windows. A task that would cross the
    stop time is not placed either — the point of `work_stop_at` is that work
    ends there, and a generator that scheduled past it would be proposing the
    overtime the verdict then punishes.

    Returns the lines, the carryovers that were placed and the ones that were
    not, so the caller can say what was left out instead of the plan quietly
    being shorter than the queue.
    """
    ordered = sorted(carryovers, key=lambda item: item.priority)
    # After the edge, not on it: «старт работы» occupies the minute it names, and
    # a first task beginning in that same minute would collide with the anchor
    # that announces it — `no_overlap` would then fail on the skeleton's own
    # output, which is exactly the bug the by-construction claim exists to avoid.
    cursor = _at(target, rule.work_start, rule) + EDGE_MINUTES
    stop = _at(target, rule.work_stop_at, rule)
    free_start = _at(target, rule.free_evening_start, rule)

    placed: list[Carryover] = []
    items: list[DraftItem] = []
    spent = 0

    for task in ordered:
        if len(items) >= rule.max_work_tasks:
            break
        minutes = max(task.minutes, 1)
        if spent + minutes > rule.work_hard_cap_min:
            continue
        ends_at = cursor + timedelta(minutes=minutes)
        if ends_at > stop or ends_at > free_start:
            continue
        items.append(
            DraftItem(
                item_id=uuid.uuid4(),
                kind=KIND_TASK,
                rigidity=RIGIDITY_SOFT,
                code=None,
                section_kind=SECTION_WORK,
                day_date=target,
                starts_at=cursor,
                ends_at=ends_at,
            )
        )
        placed.append(task)
        cursor = ends_at
        spent += minutes

    left = [task for task in ordered if task not in placed]
    return items, placed, left


def skeleton_plan(
    target: date,
    rule: DayRuleSet,
    carryovers: tuple[Carryover, ...] = (),
    signals: Signals | None = None,
) -> SkeletonPlan:
    """
    Build the day `target` out of the canon in force on it.

    The order of assembly is the order of the priorities: the edges of the day
    first, then the body, then the work that fits under the ceiling, then the
    evening — free, and with the family on the evenings the canon asks for one.

    Nothing is written on any other date. The lines all carry `target`, which is
    what `target_day_only` then confirms: «сегодня сорвалось, неделю не трогаем»
    has to be checkable, not remembered.
    """
    resolved = signals if signals is not None else Signals()

    edge_items = _edges(target, rule)
    training_items = _training(target, rule, resolved)
    work_items, placed, overflow = _work(target, rule, carryovers)
    evening_items = _relationship_evening(target, rule)

    sections = (
        SkeletonSection(
            kind=SECTION_ANCHORS,
            title="Якоря",
            items=tuple(edge_items) + tuple(evening_items),
        ),
        SkeletonSection(
            kind=SECTION_TRAINING,
            title="Тренировка",
            items=tuple(training_items),
            texts=(resolved.training_note,) if resolved.training_note else (),
        ),
        SkeletonSection(
            kind=SECTION_WORK,
            title="Работа",
            items=tuple(work_items),
            texts=tuple(task.text_md for task in placed),
        ),
        # Empty, and it stays empty: the free block is what the day breathes
        # through, and «не перезакручивать» means nothing is ever placed here.
        SkeletonSection(kind=SECTION_FREE, title="Свободный вечер"),
    )

    items: list[DraftItem] = []
    for section in sections:
        items.extend(section.items)

    return SkeletonPlan(
        draft=PlanDraft(target=target, items=tuple(items)),
        sections=sections,
        overflow=tuple(overflow),
    )
