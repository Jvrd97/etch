# [review:need-review] PHASE-03/134, PHASE-03/137
# summary: persistence of the roles — the idempotent seed of the four-role directory, CRUD of the directory and the rules, the resolver's database half (rules in, role out, `unassigned` when nothing matched), and the write of minutes and acts that neither doubles a re-imported `(source, external_ref)` nor overwrites what a person confirmed
"""
Database access for the roles.

Three things here are worth reading closely, and the rest is plumbing.

`seed_roles` is the reason a test database and a migrated one start from the
same four rows: `tests/conftest.py` builds its schema with `create_all` and
never sees the migration's seed, so the seed exists twice on purpose — once in
the migration, once here — and both are idempotent.

`resolve_role` is the database half of the markup: it hands the rules to
`app.roles.matcher` and turns a miss into `unassigned` rather than into NULL.
The fallback lives here rather than in the matcher because it needs a row id,
and a pure function has no way to look one up.

`write_time_block` carries the whole of decision B4 in about ten lines. A row
identified by `(source, external_ref)` is *found and updated*, never inserted a
second time — that is what keeps an importer that runs twice from doubling the
day. And a row a person marked `confirmed` is left exactly as it is when the
writer is not a person: the importer's answer is discarded, not merged.

Read-then-write rather than an `ON CONFLICT` upsert, unlike the health buckets:
the decision to skip depends on the *stored* row's `confidence`, which an upsert
cannot branch on without an expression nobody could read afterwards. The system
is single-user and single-writer, so the race an upsert would close does not
exist here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import (
    CONFIDENCE_AUTO,
    CONFIDENCE_CONFIRMED,
    ROLE_CODE_FALLBACK,
    SOURCE_MANUAL,
    Role,
    RoleAct,
    RoleRule,
    RoleTimeBlock,
)
from app.day.evaluate import RoleActFact
from app.roles.catalog import SEED_ROLES
from app.roles.matcher import MatchSample, RuleCandidate, resolve_rule

# Constrained rather than bound: the two fact tables are the only rows that
# carry a `(source, external_ref)` pair, and naming them is what lets mypy
# check the shared lookup against each of them.
RowT = TypeVar("RowT", RoleTimeBlock, RoleAct)


@dataclass(frozen=True)
class RoleResolution:
    """The role a sample was charged to, and the rule that decided it."""

    role_id: int
    rule_id: int | None
    matched: bool


@dataclass(frozen=True)
class TimeBlockDraft:
    """Minutes as a writer states them, before the table has an opinion."""

    work_day: date
    role_id: int
    minutes: int
    source: str = SOURCE_MANUAL
    started_at: datetime | None = None
    ended_at: datetime | None = None
    confidence: str = CONFIDENCE_AUTO
    external_ref: str | None = None
    rule_id: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class ActDraft:
    """An act as a writer states it."""

    work_day: date
    role_id: int
    act_kind: str
    title: str
    source: str = SOURCE_MANUAL
    external_ref: str | None = None
    confidence: str = CONFIDENCE_AUTO
    occurred_at: datetime | None = None
    note: str | None = None


@dataclass(frozen=True)
class WriteOutcome(Generic[RowT]):
    """
    What happened to a write, spelled out instead of implied by the row.

    `kept_confirmed` is the case a caller has to be able to see: nothing was
    written, and that is the correct answer rather than a failure.
    """

    row: RowT
    created: bool
    kept_confirmed: bool


async def seed_roles(db: AsyncSession) -> None:
    """
    Ensure the four seeded roles exist, without disturbing the ones that do.

    Runs on a filled directory as happily as an empty one. A role whose title or
    target share a person has since edited is left alone: the seed establishes
    that the code exists, not what it currently says.
    """
    existing = set((await db.execute(select(Role.code))).scalars().all())
    for seed in SEED_ROLES:
        if seed.code in existing:
            continue
        db.add(
            Role(
                code=seed.code,
                title=seed.title,
                description=seed.description,
                target_share_pct=seed.target_share_pct,
                is_work=True,
                ord=seed.ord,
                is_active=True,
            )
        )
    await db.flush()


async def list_roles(db: AsyncSession, active_only: bool = False) -> list[Role]:
    """The directory in screen order: `ord` first, then id for a stable tail."""
    statement = select(Role).order_by(Role.ord, Role.id)
    if active_only:
        statement = statement.where(Role.is_active.is_(True))
    return list((await db.execute(statement)).scalars().all())


async def get_role_by_code(db: AsyncSession, code: str) -> Role | None:
    """One role by the code every request names it with."""
    return (
        await db.execute(select(Role).where(Role.code == code))
    ).scalar_one_or_none()


async def get_role(db: AsyncSession, role_id: int) -> Role | None:
    """One role by id — what a stored row points at."""
    return await db.get(Role, role_id)


async def create_role(
    db: AsyncSession,
    *,
    code: str,
    title: str,
    description: str | None = None,
    target_share_pct: int | None = None,
    is_work: bool = True,
    ord: int = 0,
    is_active: bool = True,
) -> Role:
    """Add a role to the directory."""
    role = Role(
        code=code,
        title=title,
        description=description,
        target_share_pct=target_share_pct,
        is_work=is_work,
        ord=ord,
        is_active=is_active,
    )
    db.add(role)
    await db.flush()
    return role


def apply_role_patch(role: Role, patch: dict[str, object]) -> Role:
    """
    Write the named fields of a role and leave the rest.

    A dictionary of exactly the fields a request carried, so that «target share
    set to null» and «target share not mentioned» stay two different acts.
    """
    for name, value in patch.items():
        setattr(role, name, value)
    return role


async def list_rules(
    db: AsyncSession, source: str | None = None, active_only: bool = True
) -> list[RoleRule]:
    """
    The markup, strongest first.

    Ordered by `(priority, id)` — the same order the resolver picks a winner in,
    so the screen of `#139` shows the rules in the order they actually apply.
    """
    statement = select(RoleRule).order_by(RoleRule.priority, RoleRule.id)
    if source is not None:
        statement = statement.where(RoleRule.source == source)
    if active_only:
        statement = statement.where(RoleRule.is_active.is_(True))
    return list((await db.execute(statement)).scalars().all())


async def get_rule(db: AsyncSession, rule_id: int) -> RoleRule | None:
    """One rule by id."""
    return await db.get(RoleRule, rule_id)


async def create_rule(
    db: AsyncSession,
    *,
    role_id: int,
    source: str,
    matcher_kind: str,
    pattern: str,
    priority: int,
    is_active: bool = True,
) -> RoleRule:
    """Add one line to the markup."""
    rule = RoleRule(
        role_id=role_id,
        source=source,
        matcher_kind=matcher_kind,
        pattern=pattern,
        priority=priority,
        is_active=is_active,
    )
    db.add(rule)
    await db.flush()
    return rule


async def fallback_role_id(db: AsyncSession) -> int:
    """
    The id of `unassigned`.

    Raises when the directory has never been seeded, and that is on purpose: a
    system that cannot name «не отнесено» has no safe way to record a minute,
    and inventing the row here would hide a database that was never migrated.
    """
    role = await get_role_by_code(db, ROLE_CODE_FALLBACK)
    if role is None:
        raise LookupError(
            f"role directory has no '{ROLE_CODE_FALLBACK}' row: run the "
            "migration or seed_roles() before attributing work"
        )
    return role.id


async def resolve_role(db: AsyncSession, sample: MatchSample) -> RoleResolution:
    """
    The role of one sample: the winning rule's, or `unassigned` when none won.

    The rules are read whole rather than filtered in SQL by matcher kind: the
    table is a personal taxonomy of tens of rows, and pushing the choice into
    the database would put the tie-break — the part that has to be identical
    everywhere — in two places at once.
    """
    rules = await list_rules(db, source=sample.source)
    match = resolve_rule(
        sample,
        [
            RuleCandidate(
                id=rule.id,
                role_id=rule.role_id,
                source=rule.source,
                matcher_kind=rule.matcher_kind,
                pattern=rule.pattern,
                priority=rule.priority,
            )
            for rule in rules
        ],
    )
    if match is None:
        return RoleResolution(
            role_id=await fallback_role_id(db), rule_id=None, matched=False
        )
    return RoleResolution(role_id=match.role_id, rule_id=match.rule_id, matched=True)


def _is_person(confidence: str) -> bool:
    """Whether a write speaks for a person rather than for an importer."""
    return confidence == CONFIDENCE_CONFIRMED


async def _find_by_external_ref(
    db: AsyncSession, model: type[RowT], source: str, external_ref: str | None
) -> RowT | None:
    """The row a `(source, external_ref)` pair already occupies, if any."""
    if external_ref is None:
        return None
    return (
        await db.execute(
            select(model).where(
                model.source == source, model.external_ref == external_ref
            )
        )
    ).scalar_one_or_none()


async def write_time_block(
    db: AsyncSession, draft: TimeBlockDraft
) -> WriteOutcome[RoleTimeBlock]:
    """
    Record minutes, once per `(source, external_ref)`.

    Three outcomes, and the caller can tell them apart:

    * no `external_ref` — a new row, always. Two honest manual records of ninety
      minutes on hiring are two records, not a duplicate to be folded.
    * a known `(source, external_ref)` whose stored row is `confirmed`, written
      by anything other than a person — nothing changes, `kept_confirmed`.
    * a known `(source, external_ref)` otherwise — the stored row is rewritten,
      so a second pass of the importer restates the day instead of inflating it.
    """
    existing = await _find_by_external_ref(
        db, RoleTimeBlock, draft.source, draft.external_ref
    )
    if existing is None:
        block = RoleTimeBlock(
            work_day=draft.work_day,
            role_id=draft.role_id,
            source=draft.source,
            started_at=draft.started_at,
            ended_at=draft.ended_at,
            minutes=draft.minutes,
            confidence=draft.confidence,
            external_ref=draft.external_ref,
            rule_id=draft.rule_id,
            note=draft.note,
        )
        db.add(block)
        await db.flush()
        return WriteOutcome(row=block, created=True, kept_confirmed=False)

    if _is_person(existing.confidence) and not _is_person(draft.confidence):
        return WriteOutcome(row=existing, created=False, kept_confirmed=True)

    existing.work_day = draft.work_day
    existing.role_id = draft.role_id
    existing.started_at = draft.started_at
    existing.ended_at = draft.ended_at
    existing.minutes = draft.minutes
    existing.confidence = draft.confidence
    existing.rule_id = draft.rule_id
    existing.note = draft.note
    await db.flush()
    return WriteOutcome(row=existing, created=False, kept_confirmed=False)


async def write_act(db: AsyncSession, draft: ActDraft) -> WriteOutcome[RoleAct]:
    """
    Record an act, once per `(source, external_ref)`.

    Same three outcomes as `write_time_block`, and for the same reasons: a
    commit re-read by an importer must not turn one ADR into two, and a person's
    correction of what the act was must survive the next pass.
    """
    existing = await _find_by_external_ref(
        db, RoleAct, draft.source, draft.external_ref
    )
    if existing is None:
        act = RoleAct(
            work_day=draft.work_day,
            role_id=draft.role_id,
            act_kind=draft.act_kind,
            title=draft.title,
            source=draft.source,
            external_ref=draft.external_ref,
            confidence=draft.confidence,
            occurred_at=draft.occurred_at,
            note=draft.note,
        )
        db.add(act)
        await db.flush()
        return WriteOutcome(row=act, created=True, kept_confirmed=False)

    if _is_person(existing.confidence) and not _is_person(draft.confidence):
        return WriteOutcome(row=existing, created=False, kept_confirmed=True)

    existing.work_day = draft.work_day
    existing.role_id = draft.role_id
    existing.act_kind = draft.act_kind
    existing.title = draft.title
    existing.confidence = draft.confidence
    existing.occurred_at = draft.occurred_at
    existing.note = draft.note
    await db.flush()
    return WriteOutcome(row=existing, created=False, kept_confirmed=False)


async def get_time_block(db: AsyncSession, block_id: int) -> RoleTimeBlock | None:
    """One record of minutes by id."""
    return await db.get(RoleTimeBlock, block_id)


async def get_act(db: AsyncSession, act_id: int) -> RoleAct | None:
    """One act by id."""
    return await db.get(RoleAct, act_id)


async def day_time_blocks(db: AsyncSession, work_day: date) -> list[RoleTimeBlock]:
    """Every record of minutes charged to one day, oldest first."""
    return list(
        (
            await db.execute(
                select(RoleTimeBlock)
                .where(RoleTimeBlock.work_day == work_day)
                .order_by(RoleTimeBlock.id)
            )
        )
        .scalars()
        .all()
    )


async def day_acts(db: AsyncSession, work_day: date) -> list[RoleAct]:
    """Every act of one day, oldest first."""
    return list(
        (
            await db.execute(
                select(RoleAct).where(RoleAct.work_day == work_day).order_by(RoleAct.id)
            )
        )
        .scalars()
        .all()
    )


async def day_act_facts(db: AsyncSession, work_day: date) -> list[RoleActFact]:
    """
    Акты дня вместе с названиями их ролей — то, чем судит клауз роли (`#137`).

    Одним запросом с join, а не «акты, потом справочник по одному»: вердикт дня
    считается на каждое открытие страницы дня, и запрос на строку превратил бы
    его в запрос на акт.

    Название роли едет вместе с кодом, потому что код решает клауз, а название
    читает человек, и собирать второе из первого по словарю в питоне значило бы
    завести копию справочника, которая отстанет от переименования.
    """
    result = await db.execute(
        select(RoleAct, Role.code, Role.title)
        .join(Role, Role.id == RoleAct.role_id)
        .where(RoleAct.work_day == work_day)
        .order_by(RoleAct.id)
    )
    return [
        RoleActFact(
            role_code=code, role_title=title, act_kind=act.act_kind, title=act.title
        )
        for act, code, title in result.all()
    ]


async def titles_by_code(db: AsyncSession) -> dict[str, str]:
    """
    Названия ролей по коду — расшифровка клауза, у которого актов нет.

    Отдельным запросом, потому что нужен он ровно тогда, когда `day_act_facts`
    вернул пусто: сказать «ни одного акта CTO или архитектора» больше не из чего.
    """
    result = await db.execute(select(Role.code, Role.title))
    return {code: title for code, title in result.all()}


__all__ = [
    "ActDraft",
    "RoleResolution",
    "TimeBlockDraft",
    "WriteOutcome",
    "apply_role_patch",
    "create_role",
    "create_rule",
    "day_act_facts",
    "day_acts",
    "day_time_blocks",
    "fallback_role_id",
    "get_act",
    "get_role",
    "get_role_by_code",
    "get_rule",
    "get_time_block",
    "list_roles",
    "list_rules",
    "resolve_role",
    "seed_roles",
    "titles_by_code",
    "write_act",
    "write_time_block",
]
