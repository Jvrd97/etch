# [review:need-review] PHASE-03/86
# summary: day persistence — seed of the rule rows, the rule in force on a date (publishing the day boundary as it goes), and lazy creation of a day with kind/is_nocode materialised
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

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import DayBoundary, use_boundary
from app.day.rules import (
    SEED_RULES,
    active_rule,
    day_kind,
    is_nocode_date,
    resolve_rule,
)
from app.models.day import Day, DayRuleSet


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
    """
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
                work_stop_at=seed.work_stop_at,
                max_work_tasks=seed.max_work_tasks,
                tasks_required_ratio=seed.tasks_required_ratio,
                overtime_disqualifies=seed.overtime_disqualifies,
                workdays=list(seed.workdays),
                nocode_days=list(seed.nocode_days),
                required_anchors=list(seed.required_anchors),
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
