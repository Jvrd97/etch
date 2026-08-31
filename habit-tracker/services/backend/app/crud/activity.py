# [review:need-review] PHASE-03/135, PHASE-03/158, PHASE-03/160
# summary: database access for the agent's tables — the catalogue lookup that refuses an unknown bundle, the batch upsert of intervals on `(source, started_at, app_id)`, the intervals of one work day read through `day_bounds()`, and the mode of a date, where a manual row overrides the schedule and nothing else does
"""
Database access for the activity the macOS agent records.

Two things here decide behaviour; the rest is queries.

**Незнакомый bundle отвергается, а не заводится.** `tracked_app` is also the list
of whose window titles may ever be kept, so a catalogue that grows from the data
stream is a catalogue that silently widens what the system is allowed to
remember. `UnknownApp` carries the bundle id, and the API turns it into a 422.

**Режим дня: ручная строка перебивает расписание.** No `day_mode` row is the
normal state — the mode is then whatever `mode_schedule` says about that weekday.
A row exists only where a person decided, and it wins for that date alone. Same
semantics as `override=YYYY-MM-DD:on|off` in `~/.claude/nocode/config`.

The intervals of a day are read by `started_at` inside `day_bounds()` rather than
by the `local_date` column the writer filled in: which day a moment belongs to is
`app.core.daytime`'s question alone, and a column filled by a client is a second
opinion about it. The column stays useful as an index and as what the agent
believed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import day_bounds
from app.models.activity import (
    ACTIVITY_SOURCE_AGENT,
    ACTIVITY_SOURCE_MANUAL,
    MATCH_BUNDLE_ID,
    MATCH_BUNDLE_PREFIX,
    MATCH_TITLE_REGEX,
    MODE_SOURCE_SCHEDULE,
    SETTINGS_ROW_ID,
    TITLE_DROPPED,
    ActivityInterval,
    AgentSetting,
    DayMode,
    ModeSchedule,
    TitleRule,
    TrackedApp,
)

# Шаг нумерации правил при перестановке. Не единица: между двумя правилами
# должно оставаться место, чтобы вставить третье, не перенумеровывая список.
ORDER_STEP = 10

__all__ = [
    "ORDER_STEP",
    "BackwardInterval",
    "BadPattern",
    "DayModeAnswer",
    "IntervalDraft",
    "UnknownApp",
    "IntervalPatch",
    "KeyBelongsToAnotherRecord",
    "TaskTime",
    "app_names",
    "create_manual_interval",
    "create_title_rule",
    "day_intervals",
    "day_mode",
    "get_interval",
    "get_settings",
    "get_title_rule",
    "list_apps",
    "list_title_rules",
    "reorder_title_rules",
    "rule_hits",
    "patch_interval",
    "rule_matches",
    "seed_settings",
    "task_time_seconds",
    "upsert_intervals",
    "validate_pattern",
]


class UnknownApp(LookupError):
    """
    A batch named a bundle the catalogue does not carry.

    Carries the bundle id, because the answer a person needs is «заведи вот это»
    and not «одно из приложений неизвестно».
    """

    def __init__(self, bundle_id: str) -> None:
        super().__init__(bundle_id)
        self.bundle_id = bundle_id


@dataclass(frozen=True)
class IntervalDraft:
    """One interval as the agent states it, before the table has an opinion."""

    bundle_id: str | None
    started_at: datetime
    ended_at: datetime
    local_date: date
    utc_offset_minutes: int = 0
    title: str | None = None
    title_source: str = TITLE_DROPPED
    idle_seconds: int = 0
    switch_count: int = 0
    source: str = ACTIVITY_SOURCE_AGENT
    note: str | None = None


@dataclass(frozen=True)
class DayModeAnswer:
    """
    Which kind of day a date is, and who said so.

    `source` matters as much as `kind`: «выходной по расписанию» and «выходной,
    потому что человек так решил» are the same day and different facts, and the
    screen that shows a mode has to be able to say which one it is looking at.
    """

    kind: str
    nocode: bool
    source: str


async def list_apps(db: AsyncSession) -> list[TrackedApp]:
    """The catalogue, in the order a screen lists it."""
    return list(
        (await db.execute(select(TrackedApp).order_by(TrackedApp.display_name)))
        .scalars()
        .all()
    )


async def app_names(db: AsyncSession) -> dict[int, str]:
    """Application id to display name, read once per request instead of per row."""
    rows = await db.execute(select(TrackedApp.id, TrackedApp.display_name))
    return {row.id: row.display_name for row in rows}


async def _app_ids(db: AsyncSession) -> dict[str, int]:
    """Bundle id to catalogue id, for resolving a whole batch in one query."""
    rows = await db.execute(select(TrackedApp.bundle_id, TrackedApp.id))
    return {row.bundle_id: row.id for row in rows}


async def upsert_intervals(
    db: AsyncSession, drafts: list[IntervalDraft]
) -> list[ActivityInterval]:
    """
    Write a batch of intervals, once per `(source, started_at, app_id)`.

    The whole batch is resolved against the catalogue before a single row is
    written, so an unknown bundle leaves nothing behind — a batch is accepted or
    refused, never half-applied.

    `ON CONFLICT DO UPDATE` is what makes a re-sent batch land on the rows it
    already wrote. That is the reason this stream needs no `Idempotency-Key`:
    the natural key is the idempotency, exactly as in the health contour's
    `upsert_buckets`.

    With `titles_enabled` off (`#158`) no title reaches a row, whatever the
    batch said. The mac applies the switch first; this is the second lock, and
    it is the one a stale build or a hand-written `curl` cannot walk past.
    """
    if not drafts:
        return []

    # Рубильник `#158` действует и на сервере, а не только на маке. Агент —
    # клиент, а клиенту нельзя доверять единственную проверку того, что
    # заголовков не будет: старая сборка, отладочный `curl`, восстановленная
    # очередь. Выключен рубильник — заголовок не доезжает до строки.
    titles_allowed = (await get_settings(db)).titles_enabled

    known = await _app_ids(db)
    for draft in drafts:
        if draft.bundle_id is not None and draft.bundle_id not in known:
            raise UnknownApp(draft.bundle_id)

    written: list[ActivityInterval] = []
    for draft in drafts:
        app_id = known.get(draft.bundle_id) if draft.bundle_id else None
        title = draft.title if titles_allowed else None
        title_source = draft.title_source if titles_allowed else TITLE_DROPPED
        statement = pg_insert(ActivityInterval).values(
            source=draft.source,
            app_id=app_id,
            started_at=draft.started_at,
            ended_at=draft.ended_at,
            local_date=draft.local_date,
            utc_offset_minutes=draft.utc_offset_minutes,
            title=title,
            title_source=title_source,
            idle_seconds=draft.idle_seconds,
            switch_count=draft.switch_count,
            note=draft.note,
        )
        stored = await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_activity_interval_natural",
                set_={
                    "ended_at": statement.excluded.ended_at,
                    "local_date": statement.excluded.local_date,
                    "utc_offset_minutes": statement.excluded.utc_offset_minutes,
                    "title": statement.excluded.title,
                    "title_source": statement.excluded.title_source,
                    "idle_seconds": statement.excluded.idle_seconds,
                    "switch_count": statement.excluded.switch_count,
                    "note": statement.excluded.note,
                },
            ).returning(ActivityInterval.id)
        )
        written.append(await _reload(db, stored.scalar_one()))
    await db.flush()
    return written


async def _reload(db: AsyncSession, interval_id: int) -> ActivityInterval:
    """
    The stored row, read back rather than assembled from the draft.

    `duration_seconds` is generated by postgres, so the only way to know it is to
    ask; assembling the row here would invent the one number the table is the
    authority on.
    """
    row = (
        await db.execute(
            select(ActivityInterval).where(ActivityInterval.id == interval_id)
        )
    ).scalar_one()
    await db.refresh(row)
    return row


async def day_intervals(db: AsyncSession, work_day: date) -> list[ActivityInterval]:
    """
    Every interval that overlaps the work day `work_day`, in the order it happened.

    Overlap rather than «начался в этот день»: a session from 03:30 to 04:30 is
    half of one day and half of the next, and a query keyed on the start would
    hand the second half to nobody. `app.roles.classify` cuts what this returns.

    Against `day_bounds()` rather than against the `local_date` column the writer
    filled in: which day a moment belongs to is `app.core.daytime`'s question
    alone, and a column filled by a client is a second opinion about it. The
    column stays useful as an index and as what the agent believed.
    """
    start, end = day_bounds(work_day)
    result = await db.execute(
        select(ActivityInterval)
        .where(ActivityInterval.started_at < end, ActivityInterval.ended_at > start)
        .order_by(ActivityInterval.started_at, ActivityInterval.id)
    )
    return list(result.scalars().all())


async def day_mode(db: AsyncSession, on: date) -> DayModeAnswer:
    """
    Which kind of day `on` is: a person's decision, or the schedule's default.

    A weekday the schedule has no row for answers `work`: a schedule that has
    lost a row must not turn a working day into a day nothing is measured on,
    which is the failure that would be hardest to notice.
    """
    stored = await db.get(DayMode, on)
    if stored is not None:
        return DayModeAnswer(
            kind=stored.kind, nocode=stored.nocode, source=stored.source
        )

    # `date.isoweekday()` is 1=Mon…7=Sun; the schedule counts 0=Sun…6=Sat.
    weekday = on.isoweekday() % 7
    row = (
        await db.execute(select(ModeSchedule).where(ModeSchedule.weekday == weekday))
    ).scalar_one_or_none()
    if row is None:
        return DayModeAnswer(kind="work", nocode=False, source=MODE_SOURCE_SCHEDULE)
    return DayModeAnswer(kind=row.kind, nocode=row.nocode, source=MODE_SOURCE_SCHEDULE)


class BadPattern(ValueError):
    """
    A `title_regex` rule was saved with an expression `re` cannot compile.

    Refused on write rather than on use. A broken pattern that reaches the mac
    matches nothing and silently leaves the title to whatever rule sits below it
    — which, since the rules are ordered and the first match wins, can be a
    `keep`. «Правило, которое молча ничего не матчит» is exactly the failure the
    privacy policy cannot afford.
    """

    def __init__(self, pattern: str, reason: str) -> None:
        super().__init__(reason)
        self.pattern = pattern
        self.reason = reason


def validate_pattern(match_kind: str, pattern: str) -> None:
    """Refuse a `title_regex` rule whose expression does not compile."""
    if match_kind != MATCH_TITLE_REGEX:
        return
    try:
        re.compile(pattern)
    except re.error as error:
        raise BadPattern(pattern, str(error)) from error


async def list_title_rules(db: AsyncSession) -> list[TitleRule]:
    """
    The policy in the order it is applied: `ord` first, `id` to break a tie.

    The same order the mac applies it in and the same order the screen has to
    show, because first match wins and the order is therefore meaning rather
    than presentation.
    """
    return list(
        (await db.execute(select(TitleRule).order_by(TitleRule.ord, TitleRule.id)))
        .scalars()
        .all()
    )


async def get_title_rule(db: AsyncSession, rule_id: int) -> TitleRule | None:
    """One rule by id."""
    return await db.get(TitleRule, rule_id)


async def create_title_rule(
    db: AsyncSession,
    *,
    ord: int,
    match_kind: str,
    pattern: str,
    action: str,
    note: str | None = None,
    is_active: bool = True,
) -> TitleRule:
    """Add one line to the policy, refusing a pattern that does not compile."""
    validate_pattern(match_kind, pattern)
    rule = TitleRule(
        ord=ord,
        match_kind=match_kind,
        pattern=pattern,
        action=action,
        note=note,
        is_active=is_active,
    )
    db.add(rule)
    await db.flush()
    return rule


async def reorder_title_rules(db: AsyncSession, order: list[int]) -> list[TitleRule]:
    """
    Renumber the policy from a list of rule ids, first in the list first applied.

    A whole list rather than «move this one up»: the order is what decides which
    rule wins, and a screen that sent one move at a time would leave the policy
    in an intermediate order between two requests — with `keep` above a `drop`
    for as long as the second request took.
    """
    rules = {rule.id: rule for rule in await list_title_rules(db)}
    missing = [rule_id for rule_id in order if rule_id not in rules]
    if missing:
        raise LookupError(f"unknown title rule ids: {missing}")
    for position, rule_id in enumerate(order):
        rules[rule_id].ord = position * ORDER_STEP
    await db.flush()
    return await list_title_rules(db)


def rule_matches(rule: TitleRule, bundle_id: str | None, title: str | None) -> bool:
    """
    Whether one rule would fire on one interval, as the mac decides it.

    A broken stored pattern misses rather than raises — a row that got in another
    way (`psql`, a restored dump) must not take the whole count down with it.
    """
    if rule.match_kind == MATCH_BUNDLE_ID:
        return bundle_id == rule.pattern
    if rule.match_kind == MATCH_BUNDLE_PREFIX:
        return bundle_id is not None and bundle_id.startswith(rule.pattern)
    if rule.match_kind == MATCH_TITLE_REGEX:
        if title is None:
            return False
        try:
            return re.search(rule.pattern, title) is not None
        except re.error:
            return False
    return False


async def rule_hits(db: AsyncSession, since: date) -> dict[int, int]:
    """
    How many intervals since `since` each rule touches, by rule id.

    Counted by re-applying the rules to what is stored, because the rules
    themselves run on the mac and the interval carries no record of which one
    fired. The number answers the question the screen exists to answer — «это
    правило вообще работает или в нём опечатка» — and a rule that fires on
    nothing shows a zero instead of looking exactly like a working one.

    One honest limit, and it is on the screen rather than hidden here: a
    `title_regex` rule whose action is `drop` removed the title before it was
    stored, so it cannot be counted against titles it already erased. Rules on
    `bundle_id` and `bundle_prefix` — which is most of the policy — count exactly.
    """
    rules = await list_title_rules(db)
    bundles = {app.id: app.bundle_id for app in await list_apps(db)}
    result = await db.execute(
        select(ActivityInterval).where(ActivityInterval.local_date >= since)
    )
    hits = {rule.id: 0 for rule in rules}
    for interval in result.scalars().all():
        bundle = bundles.get(interval.app_id) if interval.app_id else None
        for rule in rules:
            if rule_matches(rule, bundle, interval.title):
                hits[rule.id] += 1
                # First match wins on the mac, and the count says the same thing.
                break
    return hits


async def seed_settings(db: AsyncSession) -> AgentSetting:
    """
    Ensure the single row of agent settings exists, without disturbing it.

    The migration inserts it; `tests/conftest.py` builds its schema with
    `create_all` and never sees a migration, so the seed lives twice on purpose —
    exactly as `role_crud.seed_roles` does, and for the same reason. Idempotent:
    a row a person has already switched is left alone.
    """
    row = await db.get(AgentSetting, SETTINGS_ROW_ID)
    if row is None:
        row = AgentSetting(id=SETTINGS_ROW_ID)
        db.add(row)
        await db.flush()
    return row


async def get_settings(db: AsyncSession) -> AgentSetting:
    """
    The one row of agent settings, seeded by the migration.

    Raises when it is missing rather than inventing it: a database that never got
    the migration must say so, not answer with defaults that look like a decision.
    """
    row = await db.get(AgentSetting, SETTINGS_ROW_ID)
    if row is None:
        raise LookupError(
            "agent_setting has no row: run the migration before reading the "
            "agent configuration"
        )
    return row


# --- правка постфактум и подсчёт по объединению диапазонов (#160) -----------
#
# Ручной ввод объявлен первичным, автоматика — подсказкой. Здесь это перестаёт
# быть декларацией.


class BackwardInterval(ValueError):
    """Границы интервала попросили поставить так, что конец раньше начала."""


class KeyBelongsToAnotherRecord(ValueError):
    """
    Тот же `Idempotency-Key` пришёл с другим телом.

    Повтор после обрыва обязан вернуть ту же строку; тот же ключ с другими
    границами — это не повтор, а ошибка вызывающего, и молча отдать ему чужую
    запись значило бы потерять его собственную.
    """


@dataclass(frozen=True)
class IntervalPatch:
    """
    A correction of one interval, field by field.

    `fields` names what the request actually carried, because `None` is a
    legitimate value for a task link and for a note: «убрать привязку» and «не
    трогать привязку» are different orders and a sentinel would merge them. The
    two ends are outside that — an interval with no start is not a state, so
    absence there simply means «оставить как есть».
    """

    started_at: datetime | None = None
    ended_at: datetime | None = None
    plan_task_id: int | None = None
    clickup_task_id: str | None = None
    note: str | None = None
    fields: frozenset[str] = frozenset()

    def has(self, name: str) -> bool:
        return name in self.fields


async def get_interval(db: AsyncSession, interval_id: int) -> ActivityInterval | None:
    """One interval by id."""
    return await db.get(ActivityInterval, interval_id)


async def patch_interval(
    db: AsyncSession, interval: ActivityInterval, patch: IntervalPatch, at: datetime
) -> ActivityInterval:
    """
    Move the ends of an interval, link it to a task, leave a note.

    `source` is deliberately left alone: the interval is still what the agent
    measured, and rewriting it to `manual` would lose the fact that a person
    corrected a measurement rather than typing one. What is recorded instead is
    `is_corrected` and `corrected_at` — «я поправил» has to stay distinguishable
    from «агент так посчитал», or the number is trusted in neither direction.

    An end before the start is refused here as well as by the table's CHECK, so
    the caller gets a 422 that names the rule rather than an `IntegrityError`.
    """
    started: datetime = (
        patch.started_at if patch.started_at is not None else interval.started_at
    )
    ended: datetime = (
        patch.ended_at if patch.ended_at is not None else interval.ended_at
    )
    if ended < started:
        raise BackwardInterval(
            f"конец {ended.isoformat()} раньше начала {started.isoformat()}"
        )

    interval.started_at = started
    interval.ended_at = ended
    if patch.has("plan_task_id"):
        interval.plan_task_id = patch.plan_task_id
    if patch.has("clickup_task_id"):
        interval.clickup_task_id = patch.clickup_task_id
    if patch.has("note"):
        interval.note = patch.note
    interval.is_corrected = True
    interval.corrected_at = at
    await db.flush()
    await db.refresh(interval)
    return interval


async def create_manual_interval(
    db: AsyncSession, draft: IntervalDraft, *, idempotency_key: str
) -> tuple[ActivityInterval, bool]:
    """
    Record an interval a person typed. Returns the row and whether it is new.

    Idempotent by the header rather than by the natural key, and that difference
    is the whole point: a manual record carries no `app_id`, NULLs in a unique
    key are distinct in postgres, and two honest records starting at the same
    minute are two records. The key is what tells a retry from a second record.

    A key already used with different ends is refused rather than answered with
    the row it names — that is a caller's mistake, and handing back somebody
    else's interval would lose the one they meant to write.
    """
    existing = (
        await db.execute(
            select(ActivityInterval).where(
                ActivityInterval.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.started_at != draft.started_at
            or existing.ended_at != draft.ended_at
        ):
            raise KeyBelongsToAnotherRecord(idempotency_key)
        return existing, False

    if draft.ended_at < draft.started_at:
        raise BackwardInterval(
            f"конец {draft.ended_at.isoformat()} раньше начала "
            f"{draft.started_at.isoformat()}"
        )

    row = ActivityInterval(
        source=ACTIVITY_SOURCE_MANUAL,
        app_id=None,
        started_at=draft.started_at,
        ended_at=draft.ended_at,
        local_date=draft.local_date,
        utc_offset_minutes=draft.utc_offset_minutes,
        title=None,
        title_source=TITLE_DROPPED,
        note=draft.note,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row, True


@dataclass(frozen=True)
class TaskTime:
    """Seconds spent on one task, counted as the union of its intervals."""

    plan_task_id: int | None
    clickup_task_id: str | None
    seconds: int


async def task_time_seconds(
    db: AsyncSession, work_day: date
) -> tuple[list[TaskTime], int]:
    """
    Time per task and time on nothing, as the **union** of ranges.

    `SUM(duration_seconds)` would give a plausible and wrong number: overlapping
    records are allowed on purpose — a person may write «созвон» over an hour the
    agent charged to Chrome — and adding them would count that hour twice. The
    union is the only number in this theme that may be called «время по задаче»,
    and postgres computes it: `range_agg(tstzrange(started_at, ended_at))`.

    Returns the tasks and, separately, the seconds that belong to no task at all
    — «работа сверх плана», visible in the same hour rather than out of the
    evening notebook.
    """
    start, end = day_bounds(work_day)
    statement = text(
        """
        SELECT
            plan_task_id,
            clickup_task_id,
            (
                SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (upper(r) - lower(r)))), 0)
                FROM unnest(range_agg(tstzrange(started_at, ended_at))) AS r
            )::bigint AS seconds
        FROM activity_interval
        WHERE started_at < :day_end AND ended_at > :day_start
        GROUP BY plan_task_id, clickup_task_id
        ORDER BY seconds DESC
        """
    )
    rows = (
        await db.execute(statement, {"day_start": start, "day_end": end})
    ).fetchall()

    tasks: list[TaskTime] = []
    untasked = 0
    for row in rows:
        if row.plan_task_id is None and row.clickup_task_id is None:
            untasked += int(row.seconds)
            continue
        tasks.append(
            TaskTime(
                plan_task_id=row.plan_task_id,
                clickup_task_id=row.clickup_task_id,
                seconds=int(row.seconds),
            )
        )
    return tasks, untasked
