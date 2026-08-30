# [review:need-review] PHASE-03/87, PHASE-03/93
# summary: the plan document validated as a whole, without a database — the task bar from the rule row, hardness only for the day's edges, a link to a goal of the quarter that exists (the set of ids arrives as an argument, the session stays out), windows unrolled across midnight, markdown flattened to the text search reads
"""
What a plan is allowed to be, decided without a database.

The rules of `config.md` live in two places on purpose, and the split is the
point of this module.

**Row-level rules are CHECK constraints** (`app.models.plan`): a task has a
window and a criterion, a free item has no window, a task names a goal or the
reason it names none. They hold for every writer — an import, a `psql` session,
a migration — because nothing can write around them.

**Whole-document rules are here**: the ceiling on the number of tasks, and which
items may declare themselves immovable. Both are properties of a plan rather
than of a line, and both depend on the `day_rule_set` row in force. Making the
task bar a trigger would have refused the import of exactly the historic days
worth keeping — the ones that broke it. So a plan arrives whole, is judged
whole, and is rejected whole with the code of the line that broke it.

Nothing here touches the session, so the truth table of every rejection is
testable in milliseconds and cannot drift from what the API answers: `app.crud.plan`
calls these functions and does no checking of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.daytime import DayBoundary
from app.models.day import DayRuleSet

__all__ = [
    "HARD_ALLOWED_KINDS",
    "KIND_TASK",
    "PlanRejected",
    "RIGIDITY_FREE",
    "RIGIDITY_HARD",
    "Window",
    "ItemFacts",
    "check_goal_exists",
    "check_hard_rigidity",
    "check_item_shape",
    "check_task_bar",
    "count_tasks",
    "parse_window",
    "resolve_window",
    "to_plain",
    "validate_plan",
]

KIND_TASK = "task"
KIND_ANCHOR = "anchor"
KIND_HARD_POINT = "hard_point"

RIGIDITY_HARD = "hard"
RIGIDITY_SOFT = "soft"
RIGIDITY_FREE = "free"

# An item may call itself immovable only if it is an edge of the day. `anchor`
# additionally has to name one of `required_anchors`; `hard_point` is here
# because it is *defined* as a commitment at a clock time (a call, an
# appointment) and exists as a separate kind precisely so that an ordinary task
# cannot pass itself off as one. The rule ADR-0014 Р3 protects is "a task
# cannot declare itself unmovable", and that survives intact.
HARD_ALLOWED_KINDS: tuple[str, ...] = (KIND_ANCHOR, KIND_HARD_POINT)

# `09:30-11:00`, `23:30-00:30` — the shape `Окно ::` has had since the plans
# were files. Anything after the second time is a comment, not a time.
WINDOW_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*$")

HOURS_PER_DAY = 24


class PlanRejected(ValueError):
    """
    A plan that breaks a whole-document rule, carrying the line that broke it.

    `code` is what the answer has to name: "422, validation error" sends the
    author back to read the whole document, while "the fifth task, W5, is over
    the bar of four" names the line to delete. When the line has no code its
    text stands in — an unnamed line is still findable by what it says.
    """

    def __init__(
        self,
        error: str,
        message: str,
        code: str | None = None,
        text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.code = code
        self.text = text

    def as_detail(self) -> dict[str, str | None]:
        """The body of the 422, in the shape the day-open skill reads."""
        return {
            "error": self.error,
            "message": self.message,
            "item_code": self.code,
            "item_text": self.text,
        }


@dataclass(frozen=True)
class Window:
    """A resolved window: two moments, already unrolled across midnight."""

    starts_at: datetime
    ends_at: datetime

    @property
    def minutes(self) -> int:
        """Length in whole minutes — 60 for `23:30-00:30`, never negative."""
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


def parse_window(raw: str) -> tuple[time, time]:
    """
    `"09:30-11:00"` to the pair of wall-clock times it names.

    Only the times: a window in the files is written as `09:30-11:00, пока ногти`
    and the tail is a comment that belongs in `window_comment`, so the caller
    splits it off before getting here rather than this function guessing where
    the time ends.
    """
    match = WINDOW_RE.match(raw)
    if match is None:
        raise PlanRejected(
            "bad_window",
            f"окно «{raw}» не читается: ожидается ЧЧ:ММ-ЧЧ:ММ, "
            "комментарий к окну — в поле window_comment.",
            text=raw,
        )
    start_h, start_m, end_h, end_m = (int(group) for group in match.groups())
    try:
        return time(start_h, start_m), time(end_h, end_m)
    except ValueError as error:
        raise PlanRejected(
            "bad_window",
            f"окно «{raw}» называет несуществующее время: {error}.",
            text=raw,
        ) from error


def resolve_window(on: date, start: time, end: time, boundary: DayBoundary) -> Window:
    """
    A pair of wall-clock times pinned to the day `on`, as two aware moments.

    Two things happen here, and both come from the day boundary rather than from
    the calendar.

    A time earlier than the boundary hour belongs to the *next* calendar date:
    a day runs 04:00 to 04:00, so `00:30` written into the plan of the 30th is
    the 31st by the calendar and the 30th by the day. This is what makes
    `23:30-00:30` sixty minutes instead of minus twenty-three hours.

    Should the two still come out equal or backwards — `10:00-10:00` — the end
    is pushed a full day forward, the same `+24h` `parse_window` in
    `plan_html.py` has always applied. The CHECK `ends_at > starts_at` then
    passes, and a zero-length window stays as visible as it deserves to be.
    """
    zone = ZoneInfo(boundary.timezone)
    starts_at = _pin(on, start, boundary, zone)
    ends_at = _pin(on, end, boundary, zone)
    if ends_at <= starts_at:
        ends_at += timedelta(hours=HOURS_PER_DAY)
    return Window(starts_at=starts_at, ends_at=ends_at)


def _pin(on: date, at: time, boundary: DayBoundary, zone: ZoneInfo) -> datetime:
    """The moment `at` happens during the day `on`, in UTC."""
    calendar_date = on if at.hour >= boundary.day_start_hour else on + timedelta(days=1)
    return datetime.combine(calendar_date, at, tzinfo=zone).astimezone(timezone.utc)


# Inline markdown the plans actually use. Applied in order: links first (their
# text may itself be bold), then emphasis, then code.
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)
_CODE_RE = re.compile(r"`([^`]*)`")
_WHITESPACE_RE = re.compile(r"\s+")


def to_plain(text_md: str) -> str:
    """
    Markdown flattened to the words a search index and a screen reader see.

    Derived here rather than in SQL because `search` is a generated column and
    postgres will only generate from an immutable expression — stripping
    markdown is not one. Deriving it in the service also means there is exactly
    one place where `text_md` and `text_plain` can disagree, and it is this
    function.
    """
    stripped = _LINK_RE.sub(r"\1", text_md)
    stripped = _BOLD_RE.sub(r"\1", stripped)
    stripped = _ITALIC_RE.sub(r"\1", stripped)
    stripped = _CODE_RE.sub(r"\1", stripped)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


@dataclass(frozen=True)
class ItemFacts:
    """
    The little of an item this module needs, so it can judge a document that is
    not yet rows and is no longer JSON.

    The three booleans mirror the CHECK constraints exactly. They are repeated
    here not because the database cannot be trusted but because an
    `IntegrityError` names a constraint, and the author of the plan needs the
    line: the database is the guarantee, this is the answer.
    """

    kind: str
    rigidity: str
    code: str | None
    text_plain: str
    has_window: bool = False
    has_criterion: bool = False
    is_goal_linked: bool = False
    # The goal of the quarter this line names, if it names one. Checked against
    # a set the caller looked up, not against the session: see the module
    # docstring — nothing here may query, or the truth table of every rejection
    # stops being testable in milliseconds.
    quarter_goal_id: int | None = None


def count_tasks(items: list[ItemFacts]) -> int:
    """How many lines of the plan are work tasks."""
    return sum(1 for item in items if item.kind == KIND_TASK)


def check_task_bar(items: list[ItemFacts], rule: DayRuleSet) -> None:
    """
    Refuse a plan that puts more tasks in the day than the canon allows.

    The one over the bar is named — the fifth task, not "the plan". A ceiling
    that reports itself as "validation error" is a ceiling nobody can act on:
    the author has to be told which line to delete, and the whole reason the bar
    exists is that the fifth task is the one that turns a day into overtime.
    """
    tasks = [item for item in items if item.kind == KIND_TASK]
    if len(tasks) <= rule.max_work_tasks:
        return
    offender = tasks[rule.max_work_tasks]
    raise PlanRejected(
        "too_many_tasks",
        f"в плане {len(tasks)} рабочих задач, канон разрешает "
        f"{rule.max_work_tasks}. Лишняя начинается с "
        f"{offender.code or offender.text_plain!r} — её место в другом дне, "
        "а не в этом.",
        code=offender.code,
        text=offender.text_plain,
    )


def check_hard_rigidity(items: list[ItemFacts], rule: DayRuleSet) -> None:
    """
    Refuse a plan where something that is not an edge of the day calls itself hard.

    "Не перезакручивать" means only the edges are fixed — waking, sport, the
    start of work, review, sleep. An anchor may be hard when it is one of
    `required_anchors`; a hard point may be hard because a commitment at a clock
    time is what that kind is for. Everything else is soft or free, and a task
    that wants to be unmovable has to become an anchor first, in the open.
    """
    allowed_anchors = set(rule.required_anchors)
    for item in items:
        if item.rigidity != RIGIDITY_HARD:
            continue
        if item.kind not in HARD_ALLOWED_KINDS:
            raise PlanRejected(
                "hard_is_not_an_edge",
                f"пункт {item.code or item.text_plain!r} объявлен жёстким, но "
                f"жёсткими бывают только края дня ({', '.join(HARD_ALLOWED_KINDS)}). "
                "Не перезакручивать: середина дня двигается.",
                code=item.code,
                text=item.text_plain,
            )
        if item.kind == KIND_ANCHOR and (item.code or "") not in allowed_anchors:
            raise PlanRejected(
                "hard_anchor_is_not_in_canon",
                f"жёсткий якорь {item.code or item.text_plain!r} не назван в "
                f"канон-списке required_anchors ({', '.join(sorted(allowed_anchors))}). "
                "Жёсткие точки заводит правило дня, а не отдельный план.",
                code=item.code,
                text=item.text_plain,
            )


def check_item_shape(items: list[ItemFacts]) -> None:
    """
    Refuse the plan for a line the CHECK constraints would refuse anyway.

    Duplicated on purpose, and the duplication is one-directional: the database
    is what makes these rules true for every writer, and this is what turns
    "constraint ck_plan_item_free_has_no_window violated" into "у пункта
    свободного блока стоит окно". Should the two ever disagree, the database
    wins and this function is the one with the bug — which is why every branch
    below is also covered by a test that writes past the service straight into
    the table.
    """
    for item in items:
        if item.rigidity == RIGIDITY_FREE and item.has_window:
            raise PlanRejected(
                "free_item_has_window",
                f"у пункта {item.code or item.text_plain!r} свободного блока "
                "проставлено окно. Свободный вечерний блок нечем расписать — "
                "это и есть «не перезакручивать».",
                code=item.code,
                text=item.text_plain,
            )
        if item.kind != KIND_TASK:
            continue
        if not item.has_window or not item.has_criterion:
            raise PlanRejected(
                "task_without_window_or_criterion",
                f"у задачи {item.code or item.text_plain!r} нет "
                + ("окна" if not item.has_window else "критерия «сделано»")
                + ". Канон от 2026-08-28: у рабочей задачи обязаны быть и окно, "
                "и критерий, иначе это не задача, а пожелание.",
                code=item.code,
                text=item.text_plain,
            )
        if not item.is_goal_linked:
            raise PlanRejected(
                "task_is_not_linked",
                f"задача {item.code or item.text_plain!r} не привязана ни к "
                "пункту квартала, ни к причине (unlinked_reason). Несвязанную "
                "задачу нельзя вписать молча — это чужая срочность, и это "
                "говорится вслух.",
                code=item.code,
                text=item.text_plain,
            )


def check_goal_exists(
    items: list[ItemFacts],
    known: frozenset[int],
    plan_goal_id: int | None = None,
) -> None:
    """
    Refuse a plan that points at a goal of the quarter nobody entered.

    `known` is looked up once by `app.crud.plan` and handed in, so this module
    keeps its promise of never touching a session. The foreign key on
    `plan_item.quarter_goal_id` is what makes the rule true for every writer;
    this is what turns it into an answer — an `IntegrityError` arrives as a 500
    naming a constraint, and the author needs the code of the task.

    The header of the plan («ради чего сегодня») is checked in the same pass and
    reported with no code: it is not a line, and pretending it is one would send
    the reader looking for a task that does not exist.
    """
    if plan_goal_id is not None and plan_goal_id not in known:
        raise PlanRejected(
            "goal_does_not_exist",
            f"план назван целью квартала {plan_goal_id}, а такой цели нет. "
            "«Ради чего сегодня» указывает на пункт квартала, который заведён.",
        )
    for item in items:
        goal_id = item.quarter_goal_id
        if goal_id is None or goal_id in known:
            continue
        raise PlanRejected(
            "goal_does_not_exist",
            f"задача {item.code or item.text_plain!r} ссылается на цель "
            f"квартала {goal_id}, а такой цели нет. Либо это опечатка, либо "
            "цель ещё не заведена — привязка к несуществующему пункту не "
            "считается привязкой.",
            code=item.code,
            text=item.text_plain,
        )


def validate_plan(
    items: list[ItemFacts],
    rule: DayRuleSet,
    known_goal_ids: frozenset[int],
    plan_goal_id: int | None = None,
) -> None:
    """
    Every whole-document rule, in the order the author would want to hear them.

    Line-shaped complaints first — a missing window is a typo and cheap to fix.
    The bar on the number of tasks last, because "delete the fifth task" is a
    decision about the day rather than a correction of the document.

    `known_goal_ids` are the ids of `quarter_goal` that exist; the caller reads
    them, because this module has no session.
    """
    check_item_shape(items)
    check_goal_exists(items, known_goal_ids, plan_goal_id)
    check_hard_rigidity(items, rule)
    check_task_bar(items, rule)
