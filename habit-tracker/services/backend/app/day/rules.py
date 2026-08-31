# [review:need-review] PHASE-03/86, PHASE-03/90, PHASE-03/142
# summary: pure day-canon logic — which rule row was in force on a date, which rule is in force now, the kind/is_nocode a date gets under a rule, the window in which opening a day counts as opening it, the two seed rows, and (since #142) `day_map` — the whole map of the day as one object: edges, free evening, evening with the family, ceilings and the composition of anchors
"""
The canon of a day, decided without a database.

Everything here is a function of rows already in hand, so the whole of it is
testable without postgres and none of it can drift from what the API answers:
`app.crud.day` loads the rows and calls exactly these functions.

Three ideas are worth reading closely.

**A rule is in force over a half-open interval of dates.** `valid_to` is the
first date the rule no longer applies, which makes a change of canon a single
date rather than a pair that has to be kept in sync: the new row's `valid_from`
equals the old row's `valid_to`.

**"The rule in force now" is a property of the rows, not of the clock.** It is
the last interval, and the database refuses overlaps, so it can be found without
asking what today's date is. That matters because the day boundary itself is one
of the rule's fields: asking `today_local()` first, to then find the rule that
defines what "today" means, is a circle.

**The map of the day is data, and `day_map` is the single reading of it.** Края
дня, свободный вечер и вечер с близкими до `#142` существовали только прозой
`config.md`, поэтому сверить с ними план было нечем. Now they are columns, and
everything that needs them — the generator, the screen, the validator of a plan
— asks this one function instead of reading fifteen fields its own way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

from app.day.evaluate import verdict_reasons
from app.models.day import (
    DEFAULT_ANCHORS,
    DEFAULT_DAYS_OFF,
    DEFAULT_HARD_EDGE_KINDS,
    DEFAULT_VERDICT_RULE,
    DayRuleSet,
)

__all__ = [
    "EDGE_BEDTIME",
    "EDGE_REVIEW",
    "EDGE_SPORT",
    "EDGE_WAKE",
    "EDGE_WORK_START",
    "EDGE_WORK_STOP",
    "KIND_OFF",
    "KIND_WORK",
    "OPEN_WINDOW_DAYS",
    "SEED_RULES",
    "DayEdge",
    "DayMap",
    "Interval",
    "NoRuleForDate",
    "RuleSeed",
    "active_rule",
    "anchors_of",
    "covers",
    "day_kind",
    "day_map",
    "hard_edge_kinds",
    "is_nocode_date",
    "is_openable",
    "resolve_rule",
]

# The two kinds a day can be. Stored on `day.kind` and checked by the database.
KIND_WORK = "work"
KIND_OFF = "off"

# ISO weekday numbers, the ones `date.isoweekday()` returns.
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY = 1, 2, 3, 4, 5

# The date the canon changed: the ceiling dropped from ten hours to eight and
# the task bar rose from "most of them" to "all of them" (`config.md`, entry of
# 2026-08-17: "ten hours turned out to be the norm, not the ceiling").
CANON_CHANGED_ON = date(2026, 8, 17)

# Lower bound of the `legacy` interval. Deliberately earlier than any day this
# system will ever be asked about: it costs nothing and keeps the resolver total,
# so a date typed into the URL bar gets an answer instead of a 404 about a
# history that has no beginning recorded anywhere.
HISTORY_STARTS_ON = date(2020, 1, 1)

# How far back an open window reaches: сегодня и вчера. See `is_openable`.
OPEN_WINDOW_DAYS = 1

# The hard edges of the day. Only these may carry `rigidity='hard'` when plans
# arrive (`#87`); the middle of the evening breathes. A bound on what a plan may
# harden, not a checklist the verdict counts against — `app.day.evaluate` reads
# the anchors of the plan itself and says why.
REQUIRED_ANCHORS: tuple[str, ...] = (
    "подъём",
    "спорт",
    "старт работы",
    "ревью",
    "отбой",
)

# The anchor of the third priority — «вечер с близкими». Named here because the
# seed of the current row includes it and the legacy row does not: the evening
# with the family became part of the canon with `#142`, and a day lived before
# that is not judged by it.
ANCHOR_RELATIONSHIP = "relationship"

# Codes of the edges of the day, machine-readable. The Russian a person reads is
# a label of the screen, the same way `mark.state` is handled.
EDGE_WAKE = "wake"
EDGE_SPORT = "sport"
EDGE_WORK_START = "work_start"
EDGE_WORK_STOP = "work_stop"
EDGE_REVIEW = "review"
EDGE_BEDTIME = "bedtime"


class NoRuleForDate(LookupError):
    """
    No rule row covers the date asked about.

    A real failure rather than a default: answering with a made-up canon would
    produce a verdict nobody ever lived under, which is the one thing the
    versioned table exists to prevent.
    """


@dataclass(frozen=True)
class RuleSeed:
    """
    One rule row as a fresh installation starts with it.

    Mirrors the columns of `day_rule_set`. Kept as a dataclass rather than as
    model instances so that the migration, the test database and this module can
    be compared field by field.
    """

    valid_from: date
    valid_to: date | None
    timezone: str
    day_start_hour: int
    work_cap_min: int
    work_hard_cap_min: int
    overtime_lost_min: int
    work_stop_at: time
    max_work_tasks: int
    max_study_items: int
    tasks_required_ratio: Decimal
    overtime_disqualifies: bool
    workdays: tuple[int, ...]
    days_off: tuple[int, ...]
    nocode_days: tuple[int, ...]
    required_anchors: tuple[str, ...]
    wake_at: time
    work_start: time
    review_at: time
    bedtime_max: time
    free_evening_start: time
    free_evening_end: time
    relationship_anchor_required: bool
    relationship_evening_start: time
    relationship_evening_end: time
    hard_edge_kinds: tuple[str, ...]
    anchors: tuple[str, ...]
    verdict_rule: dict[str, Any]
    note_md: str


# Two rows, because the canon has two versions and both are needed: the one in
# force, and the one the imported history (`#89`) was actually lived under.
# Everything the record does not name is deliberately identical between them, so
# that a diff of the two rows shows exactly what changed on 2026-08-17 and
# nothing invented.
SEED_RULES: tuple[RuleSeed, ...] = (
    RuleSeed(
        valid_from=HISTORY_STARTS_ON,
        valid_to=CANON_CHANGED_ON,
        timezone="Europe/Berlin",
        day_start_hour=4,
        work_cap_min=600,
        work_hard_cap_min=600,
        overtime_lost_min=600,
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        max_study_items=2,
        tasks_required_ratio=Decimal("0.80"),
        overtime_disqualifies=True,
        workdays=(MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY),
        days_off=DEFAULT_DAYS_OFF,
        nocode_days=(TUESDAY, THURSDAY),
        required_anchors=REQUIRED_ANCHORS,
        wake_at=time(6, 0),
        work_start=time(7, 45),
        review_at=time(15, 40),
        bedtime_max=time(22, 30),
        free_evening_start=time(19, 10),
        free_evening_end=time(21, 0),
        # The evening with the family became a requirement of the canon with
        # `#142`; a day lived before that is not judged by it.
        relationship_anchor_required=False,
        relationship_evening_start=time(18, 30),
        relationship_evening_end=time(21, 0),
        hard_edge_kinds=DEFAULT_HARD_EDGE_KINDS,
        anchors=REQUIRED_ANCHORS,
        verdict_rule=dict(DEFAULT_VERDICT_RULE),
        note_md=(
            "legacy: канон до 2026-08-17 — потолок 10 ч и планка 80% задач. "
            "Существует ради импортированной истории: её вердикты переносятся "
            "как записаны, а не пересчитываются по нынешним числам."
        ),
    ),
    RuleSeed(
        valid_from=CANON_CHANGED_ON,
        valid_to=None,
        timezone="Europe/Berlin",
        day_start_hour=4,
        work_cap_min=480,
        work_hard_cap_min=540,
        overtime_lost_min=600,
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        max_study_items=2,
        tasks_required_ratio=Decimal("1.00"),
        overtime_disqualifies=True,
        workdays=(MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY),
        days_off=DEFAULT_DAYS_OFF,
        nocode_days=(TUESDAY, THURSDAY),
        required_anchors=REQUIRED_ANCHORS,
        wake_at=time(6, 0),
        work_start=time(7, 45),
        review_at=time(15, 40),
        bedtime_max=time(22, 30),
        free_evening_start=time(19, 10),
        free_evening_end=time(21, 0),
        relationship_anchor_required=True,
        relationship_evening_start=time(18, 30),
        relationship_evening_end=time(21, 0),
        hard_edge_kinds=DEFAULT_HARD_EDGE_KINDS,
        anchors=DEFAULT_ANCHORS,
        verdict_rule=dict(DEFAULT_VERDICT_RULE),
        note_md=(
            "Действующий канон по config.md: 8 ч со стопом в 16:00, потолок 9 ч "
            "для исключений, четыре рабочие задачи, закрыты все, переработка "
            "дисквалифицирует день."
        ),
    ),
)


def covers(rule: DayRuleSet, on: date) -> bool:
    """
    Whether `rule` was in force on `on`.

    Half-open: the `valid_from` date belongs to the rule, the `valid_to` date
    does not. An open `valid_to` means the rule is still in force.
    """
    if on < rule.valid_from:
        return False
    return rule.valid_to is None or on < rule.valid_to


def resolve_rule(rules: Sequence[DayRuleSet], on: date) -> DayRuleSet:
    """
    The rule in force on `on`.

    A linear scan on purpose: the database refuses overlapping intervals, so at
    most one row can match and the whole table is a handful of rows — the canon
    changes about once a month. Loading it whole and deciding here keeps the
    "in force on" rule written exactly once, instead of once in Python for the
    tests and once in SQL for production.
    """
    for rule in rules:
        if covers(rule, on):
            return rule
    raise NoRuleForDate(
        f"no day_rule_set covers {on.isoformat()}: the canon has to be recorded "
        "for a date before a day on it can be judged. Insert a rule row whose "
        "interval contains it."
    )


def active_rule(rules: Sequence[DayRuleSet]) -> DayRuleSet:
    """
    The rule in force now — the last interval, found without reading a clock.

    Used for the one thing that cannot wait for a date to be known: publishing
    the day boundary (`timezone`, `day_start_hour`) that `app.core.daytime` needs
    in order to answer what today even is.
    """
    if not rules:
        raise NoRuleForDate(
            "day_rule_set is empty: nothing describes what a day is. A fresh "
            "database gets its rows from the migration; a test database from "
            "app.crud.day.seed_rules()."
        )
    return max(rules, key=lambda rule: rule.valid_from)


def day_kind(rule: DayRuleSet, on: date) -> str:
    """Whether `on` is a working day under `rule`."""
    return KIND_WORK if on.isoweekday() in rule.workdays else KIND_OFF


def is_nocode_date(rule: DayRuleSet, on: date) -> bool:
    """Whether `on` is a no-code day — one the human writes the code themselves."""
    return on.isoweekday() in rule.nocode_days


def is_openable(on: date, today: date) -> bool:
    """
    Whether opening `on` in a browser may claim that the day was opened.

    Сегодня и вчера, и ни дня больше. Пролистать август из любопытства — это не
    «открыл день»: `GET /day/{date}?opened=true` ставил `opened_at` любой дате,
    и «не открывал» переставало отличаться от «открыл и ничего не сделал», а на
    этом различии стоит `verdict = null` (`#90`).

    Yesterday is inside the window because closing a day at 00:30 is the normal
    case rather than the exception — the boundary hour is 04:00, so «вчера» by
    the calendar is often still the day being lived.

    The predicate is the server's, never the browser's: a page has its own
    midnight and does not know this one, which is the same reason `useDay` sends
    `date === null` for today instead of the calendar's date.
    """
    return today - timedelta(days=OPEN_WINDOW_DAYS) <= on <= today


@dataclass(frozen=True)
class DayEdge:
    """
    One hard edge of the day: what it is, and at what hour — if the canon fixes one.

    `at` is optional because not every edge is a time. Спорт is an edge («жёсткие
    только края: подъём, спорт, старт работы, ревью, отбой») but the canon fixes
    its *place* — before the start of work — rather than its hour, and inventing
    06:15 for it here would be a number nobody decided.
    """

    kind: str
    label: str
    at: time | None


@dataclass(frozen=True)
class Interval:
    """A stretch of the evening, named by its two wall-clock ends."""

    start: time
    end: time


@dataclass(frozen=True)
class DayMap:
    """
    The whole canon of one day as a single object: edges, evenings, ceilings.

    One object rather than fifteen reads of the row, because every consumer
    needs the same set and each of them fetching its own field is how «жёсткие
    только края дня» drifted into three incompatible versions of prose in the
    first place. The generator (`#147`), the screen and the plan validator all
    ask this one question and get one answer.
    """

    rule_set_id: int
    edges: tuple[DayEdge, ...]
    free_evening: Interval
    relationship_evening: Interval
    relationship_anchor_required: bool
    work_cap_min: int
    work_hard_cap_min: int
    overtime_lost_min: int
    work_stop_at: time
    max_work_tasks: int
    max_study_items: int
    anchors: tuple[str, ...]
    hard_edge_kinds: tuple[str, ...]
    workdays: tuple[int, ...]
    days_off: tuple[int, ...]
    nocode_days: tuple[int, ...]
    verdict_reasons: tuple[str, ...]


def hard_edge_kinds(rule: DayRuleSet) -> tuple[str, ...]:
    """
    Which kinds of plan item this canon lets call themselves immovable.

    Falls back to the default for a row built in memory without the column —
    `mapped_column(default=...)` fills at INSERT, not at construction — so a
    rule that never saw a database still answers the question instead of
    raising `TypeError` on a `None`.
    """
    return tuple(rule.hard_edge_kinds or DEFAULT_HARD_EDGE_KINDS)


def anchors_of(rule: DayRuleSet) -> tuple[str, ...]:
    """The anchors a won day has to close under this canon."""
    return tuple(rule.anchors or DEFAULT_ANCHORS)


def day_map(rule: DayRuleSet) -> DayMap:
    """
    The map of the day the rule describes.

    Every number here used to live in `config.md` and nowhere else, which meant
    a plan could not be checked against the map of the day and a person could
    not see the map beside the plan. Reading it off the row is what makes «жёсткие
    только края» and «свободный вечер не расписывается» checkable statements
    rather than paragraphs of a prompt.
    """
    return DayMap(
        rule_set_id=rule.id,
        edges=(
            DayEdge(EDGE_WAKE, "подъём", rule.wake_at),
            DayEdge(EDGE_SPORT, "спорт", None),
            DayEdge(EDGE_WORK_START, "старт работы", rule.work_start),
            DayEdge(EDGE_WORK_STOP, "стоп работы", rule.work_stop_at),
            DayEdge(EDGE_REVIEW, "ревью", rule.review_at),
            DayEdge(EDGE_BEDTIME, "отбой", rule.bedtime_max),
        ),
        free_evening=Interval(rule.free_evening_start, rule.free_evening_end),
        relationship_evening=Interval(
            rule.relationship_evening_start, rule.relationship_evening_end
        ),
        relationship_anchor_required=rule.relationship_anchor_required,
        work_cap_min=rule.work_cap_min,
        work_hard_cap_min=rule.work_hard_cap_min,
        overtime_lost_min=rule.overtime_lost_min,
        work_stop_at=rule.work_stop_at,
        max_work_tasks=rule.max_work_tasks,
        max_study_items=rule.max_study_items,
        anchors=anchors_of(rule),
        hard_edge_kinds=hard_edge_kinds(rule),
        workdays=tuple(rule.workdays),
        days_off=tuple(rule.days_off or DEFAULT_DAYS_OFF),
        nocode_days=tuple(rule.nocode_days),
        verdict_reasons=verdict_reasons(rule),
    )
