# [review:need-review] PHASE-03/86, PHASE-03/90
# summary: pure day-canon logic — which rule row was in force on a date, which rule is in force now, the kind/is_nocode a date gets under a rule, the window in which opening a day counts as opening it, and the two seed rows
"""
The canon of a day, decided without a database.

Everything here is a function of rows already in hand, so the whole of it is
testable without postgres and none of it can drift from what the API answers:
`app.crud.day` loads the rows and calls exactly these functions.

Two ideas are worth reading closely.

**A rule is in force over a half-open interval of dates.** `valid_to` is the
first date the rule no longer applies, which makes a change of canon a single
date rather than a pair that has to be kept in sync: the new row's `valid_from`
equals the old row's `valid_to`.

**"The rule in force now" is a property of the rows, not of the clock.** It is
the last interval, and the database refuses overlaps, so it can be found without
asking what today's date is. That matters because the day boundary itself is one
of the rule's fields: asking `today_local()` first, to then find the rule that
defines what "today" means, is a circle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

from app.models.day import DayRuleSet

__all__ = [
    "KIND_OFF",
    "KIND_WORK",
    "OPEN_WINDOW_DAYS",
    "SEED_RULES",
    "NoRuleForDate",
    "RuleSeed",
    "active_rule",
    "covers",
    "day_kind",
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

# The hard edges of the day. Only these may carry `rigidity='hard'` when plans
# arrive (`#87`); the middle of the evening breathes.
# How far back an open window reaches: сегодня и вчера. See `is_openable`.
OPEN_WINDOW_DAYS = 1

REQUIRED_ANCHORS: tuple[str, ...] = (
    "подъём",
    "спорт",
    "старт работы",
    "ревью",
    "отбой",
)


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
    work_stop_at: time
    max_work_tasks: int
    tasks_required_ratio: Decimal
    overtime_disqualifies: bool
    workdays: tuple[int, ...]
    nocode_days: tuple[int, ...]
    required_anchors: tuple[str, ...]
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
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        tasks_required_ratio=Decimal("0.80"),
        overtime_disqualifies=True,
        workdays=(MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY),
        nocode_days=(TUESDAY, THURSDAY),
        required_anchors=REQUIRED_ANCHORS,
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
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        tasks_required_ratio=Decimal("1.00"),
        overtime_disqualifies=True,
        workdays=(MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY),
        nocode_days=(TUESDAY, THURSDAY),
        required_anchors=REQUIRED_ANCHORS,
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
