# [review:need-review] PHASE-03/86, PHASE-03/88, PHASE-03/92
# summary: day persistence — seed of the rule rows together with the catalogue of anchor kinds they name, the rule in force on a date (publishing the day boundary as it goes), lazy creation of a day with kind/is_nocode materialised, and the two writes that make "не открывал" a fact: touch_day and the day's notebook
"""
Database access for the day.

Two things are worth reading closely.

`rule_for_date` loads the whole rule table instead of filtering in SQL. The
table is a handful of rows by construction — the canon changes about once a
month — and one loaded table means the "in force on" rule is written once, in
`app.day.rules.covers`, instead of once in Python for the tests and once in SQL
for production, where the two would eventually disagree about the boundary date.

`ensure_day` materialises `kind` and `is_nocode` at creation and never touches
them again. Deriving them on read would re-label every past Tuesday the next
time the week schedule is edited, and the whole point of a versioned canon is
that last Tuesday stays what it was.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import DayBoundary, use_boundary
from app.crud import anchor as anchor_crud
from app.crud import journal as journal_crud
from app.day.rules import (
    SEED_RULES,
    active_rule,
    day_kind,
    is_nocode_date,
    resolve_rule,
)
from app.models.day import Day, DayRuleSet
from app.models.journal import JournalEntry

# The heading a notebook entry is created with. Only used on creation — see
# `set_notebook`.
NOTEBOOK_TITLE = "Блокнот дня"


async def list_rules(db: AsyncSession) -> list[DayRuleSet]:
    """Every rule row, oldest interval first."""
    result = await db.execute(select(DayRuleSet).order_by(DayRuleSet.valid_from))
    return list(result.scalars().all())


async def seed_rules(db: AsyncSession) -> None:
    """
    Ensure the seeded rule rows exist, without disturbing rows already there.

    Runs on a filled table as happily as on an empty one, so a test database
    built by `create_all` (which never sees the migration's seed) starts from the
    same canon as a migrated one. A row is recognised by its `valid_from`: that
    is what identifies a version of the canon, and an overlapping insert would be
    refused by the exclusion constraint anyway.

    The catalogue of anchor kinds is seeded here too, and not by accident: a rule
    row names its anchors by code, so a canon without the catalogue those codes
    live in is a foreign key waiting to fail (`#92`).
    """
    await anchor_crud.seed_anchor_kinds(db)
    existing = {rule.valid_from for rule in await list_rules(db)}
    for seed in SEED_RULES:
        if seed.valid_from in existing:
            continue
        db.add(
            DayRuleSet(
                valid_from=seed.valid_from,
                valid_to=seed.valid_to,
                timezone=seed.timezone,
                day_start_hour=seed.day_start_hour,
                work_cap_min=seed.work_cap_min,
                work_hard_cap_min=seed.work_hard_cap_min,
                overtime_lost_min=seed.overtime_lost_min,
                work_stop_at=seed.work_stop_at,
                max_work_tasks=seed.max_work_tasks,
                max_study_items=seed.max_study_items,
                tasks_required_ratio=seed.tasks_required_ratio,
                overtime_disqualifies=seed.overtime_disqualifies,
                workdays=list(seed.workdays),
                days_off=list(seed.days_off),
                nocode_days=list(seed.nocode_days),
                required_anchors=list(seed.required_anchors),
                wake_at=seed.wake_at,
                work_start=seed.work_start,
                review_at=seed.review_at,
                bedtime_max=seed.bedtime_max,
                free_evening_start=seed.free_evening_start,
                free_evening_end=seed.free_evening_end,
                relationship_anchor_required=seed.relationship_anchor_required,
                relationship_evening_start=seed.relationship_evening_start,
                relationship_evening_end=seed.relationship_evening_end,
                hard_edge_kinds=list(seed.hard_edge_kinds),
                anchors=list(seed.anchors),
                verdict_rule=dict(seed.verdict_rule),
                role_clause_enabled=seed.role_clause_enabled,
                role_clause_roles=seed.role_clause_roles,
                note_md=seed.note_md,
            )
        )
    await db.flush()


def publish_boundary(rules: list[DayRuleSet]) -> bool:
    """
    Hand the day boundary of the rule in force to `app.core.daytime`.

    Returns whether anything was published; an empty table leaves the settings
    fallback in place rather than raising, because a process is allowed to start
    against a database that has not been migrated yet.
    """
    if not rules:
        return False
    rule = active_rule(rules)
    use_boundary(
        DayBoundary(timezone=rule.timezone, day_start_hour=rule.day_start_hour)
    )
    return True


async def refresh_day_boundary(db: AsyncSession) -> bool:
    """Read the rule table and publish the boundary. Called at startup."""
    return publish_boundary(await list_rules(db))


async def rule_for_date(db: AsyncSession, on: date) -> DayRuleSet:
    """
    The rule that was in force on `on`, raising `NoRuleForDate` when none was.

    Publishes the current boundary on the way: any request that asks about a day
    has just paid for the rule table, so keeping `local_date()` in step with it
    costs nothing and removes the window in which a freshly inserted rule is
    ignored until the next restart.
    """
    rules = await list_rules(db)
    publish_boundary(rules)
    return resolve_rule(rules, on)


async def get_day(db: AsyncSession, on: date) -> Day | None:
    """The stored day, or None when nobody has created it yet."""
    result = await db.execute(select(Day).where(Day.day_date == on))
    return result.scalar_one_or_none()


async def ensure_day(db: AsyncSession, on: date) -> Day:
    """
    The day for `on`, created from the rule in force if it does not exist yet.

    `kind` and `is_nocode` are frozen here, at creation, from the rule that
    covered the date. `opened_at` stays NULL: creating the row is not the same
    event as a human opening the day, and telling those two apart is why the
    column exists.

    The insert tolerates a concurrent one (`ON CONFLICT DO NOTHING` on the
    primary key) — two tabs on the same date is the normal case, not the
    exceptional one.
    """
    existing = await get_day(db, on)
    if existing is not None:
        return existing

    rule = await rule_for_date(db, on)
    await db.execute(
        pg_insert(Day)
        .values(
            date=on,
            rule_set_id=rule.id,
            kind=day_kind(rule, on),
            is_nocode=is_nocode_date(rule, on),
        )
        .on_conflict_do_nothing(index_elements=["date"])
    )
    await db.flush()

    created = await get_day(db, on)
    if created is None:  # pragma: no cover - the insert either lands or conflicts
        raise RuntimeError(
            f"day {on.isoformat()} vanished between insert and read; the row was "
            "deleted by a concurrent writer."
        )
    return created


async def touch_day(db: AsyncSession, day: Day, *, opened: bool) -> Day:
    """
    Record that something happened to `day`, and whether a human did it.

    `last_touched_at` moves on every write. `opened_at` is set once and only
    when `opened` — that is, when the caller knows a person was looking at the
    day, not merely that some process read it. An import, a cron job and an
    agent all read days, and if reading counted as opening, "не открывал"
    would stop being a fact anything could establish.
    """
    now = datetime.now(timezone.utc)
    day.last_touched_at = now
    if opened and day.opened_at is None:
        day.opened_at = now
    await db.flush()
    return day


async def get_notebook(db: AsyncSession, on: date) -> JournalEntry | None:
    """
    The day's notebook, which is the day's journal entry.

    No table of its own: `journal_entries` is already where the prose of a day
    lives, and a second store would give "что я писал 30-го" two answers.
    """
    return await journal_crud.get_day_journal_entry(db, on)


async def set_notebook(db: AsyncSession, on: date, content: str) -> JournalEntry:
    """
    Replace the day's notebook text, keeping it a single entry per date.

    `replace` rather than `append`: the notebook is a text a person edits in
    place — every save carries what was already written plus the new sentence —
    and appending would double the whole note on every keystroke's worth of
    save. The title is only supplied when the entry is being created, so that a
    heading the person wrote by hand in the morning survives the evening save.
    """
    existing = await journal_crud.get_day_journal_entry(db, on)
    entry = await journal_crud.write_day_journal(
        db,
        on,
        mode="replace",
        title=None if existing is not None else NOTEBOOK_TITLE,
        content=content,
    )
    # `updated_at` is a server default and a server `onupdate`; without this the
    # attribute is expired after the flush and reading it would be a lazy load
    # in an async context.
    await db.refresh(entry)
    return entry
