# [review:need-review] PHASE-03/179
# summary: persistence of the breathing ceiling — the idempotent seed of the three profiles, the profile in force on a date (a confirmed activation's or the default), activations confirmed and declined, and the debt ledger: accrue on close, repay the oldest that fits, and the open total a week is judged with
"""
Database access for the profiles of the day rule and for the overtime debt.

The decisions live in `app.day.profiles` and `app.day.debt`, which are pure. This
module supplies the rows and writes the answers, and it is the only place that
knows the two modules exist.

`seed_profiles` is here for the same reason `seed_roles` is: `tests/conftest.py`
builds its schema with `create_all` and never sees a migration's seed, so the
three rows exist twice on purpose and both spellings are idempotent.

`settle_day` is the one entry point the closing of a day calls. It does both
halves in one transaction, in the one order that is correct: a day accrues its
own overage first and only then may repay somebody else's, so a twelve-hour day
cannot pay back the debt it is in the middle of creating.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.day import debt as debt_rules
from app.day.profiles import (
    Activation,
    DeadlineSignal,
    Profile,
    baseline_profile,
    resolve_profile,
)
from app.models.day_profile import (
    CONFIRMED_BY_HUMAN,
    DayRuleActivation,
    DayRuleProfile,
    OvertimeDebt,
)

__all__ = [
    "SEED_PROFILES",
    "SettledDay",
    "activations",
    "confirm_activation",
    "create_activation",
    "decline_activation",
    "deadline_signals",
    "declined_signal_ids",
    "get_activation",
    "list_profiles",
    "open_debt_minutes",
    "open_debts",
    "profile_for",
    "resolution_inputs",
    "seed_profiles",
    "settle_day",
]

# Дословный близнец `SEED_PROFILES` ревизии `b4d6f8a0c2e5`.
SEED_PROFILES: tuple[tuple[str, str, int, int, bool], ...] = (
    ("baseline", "Обычная неделя", 480, 540, True),
    ("deadline", "Неделя сдачи", 720, 720, False),
    ("recovery", "Неделя после сдачи", 360, 420, False),
)


@dataclass(frozen=True)
class SettledDay:
    """What closing one day did to the ledger."""

    accrued_minutes: int
    repaid_on: date | None


async def seed_profiles(db: AsyncSession) -> None:
    """
    Ensure the three named profiles exist, without disturbing the ones that do.

    A profile whose ceiling a person has since edited is left alone: the seed
    establishes that the code exists, not what it currently says.
    """
    existing = set((await db.execute(select(DayRuleProfile.code))).scalars().all())
    for code, title, cap, hard_cap, is_default in SEED_PROFILES:
        if code in existing:
            continue
        db.add(
            DayRuleProfile(
                code=code,
                title=title,
                work_cap_min=cap,
                work_hard_cap_min=hard_cap,
                is_default=is_default,
            )
        )
    await db.flush()


async def list_profiles(db: AsyncSession) -> list[DayRuleProfile]:
    """Every profile, default first and then by code for a stable order."""
    return list(
        (
            await db.execute(
                select(DayRuleProfile).order_by(
                    DayRuleProfile.is_default.desc(), DayRuleProfile.code
                )
            )
        )
        .scalars()
        .all()
    )


async def get_profile_by_code(db: AsyncSession, code: str) -> DayRuleProfile | None:
    """One profile by the code every request names it with."""
    return (
        await db.execute(select(DayRuleProfile).where(DayRuleProfile.code == code))
    ).scalar_one_or_none()


async def activations(db: AsyncSession) -> list[DayRuleActivation]:
    """Every activation ever written, newest range first."""
    return list(
        (
            await db.execute(
                select(DayRuleActivation).order_by(
                    DayRuleActivation.valid_from.desc(), DayRuleActivation.id.desc()
                )
            )
        )
        .scalars()
        .all()
    )


async def get_activation(
    db: AsyncSession, activation_id: int
) -> DayRuleActivation | None:
    """One activation by id."""
    return await db.get(DayRuleActivation, activation_id)


def _as_values(
    profiles: list[DayRuleProfile], rows: list[DayRuleActivation]
) -> tuple[list[Profile], list[Activation]]:
    """The rows as the pure resolver needs them: values, no session, no ORM."""
    return (
        [
            Profile(
                id=row.id,
                code=row.code,
                title=row.title,
                work_cap_min=row.work_cap_min,
                work_hard_cap_min=row.work_hard_cap_min,
                is_default=row.is_default,
            )
            for row in profiles
        ],
        [
            Activation(
                id=row.id,
                profile_id=row.profile_id,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                confirmed=row.confirmed_at is not None,
                reason=row.reason,
            )
            for row in rows
        ],
    )


@dataclass(frozen=True)
class ProfileInForce:
    """
    The profile a date is judged by, with the activation that put it there.

    The activation is part of the answer, not context around it: «потолок 12
    часов до пятницы» and «потолок 12 часов навсегда» are different states, and
    the screen has to be able to print the date the raise runs out.
    """

    profile: Profile
    valid_to: date | None
    reason: str


async def resolution_inputs(
    db: AsyncSession,
) -> tuple[list[Profile], list[Activation]]:
    """
    The profiles and activations as plain values, read once.

    For a caller that judges many days in one pass: `recompute_history` walks
    the whole history, and asking the database per day would turn one query into
    a hundred while giving the same answer.
    """
    return _as_values(await list_profiles(db), await activations(db))


async def profile_for(db: AsyncSession, on: date) -> ProfileInForce | None:
    """
    Which ceiling `on` is judged by, and until when. `None` with no directory.

    `valid_to` is `None` when the default answered — an ordinary day is not «до
    какого-то числа», it is simply the ordinary day. The whole answer is `None`
    on a database from before `#179`, and the caller then keeps judging the day
    by its own rule row.
    """
    profiles, rows = _as_values(await list_profiles(db), await activations(db))
    chosen = resolve_profile(profiles, rows, on)
    if chosen is None:
        return None
    covering = [
        row
        for row in rows
        if row.confirmed and row.covers(on) and row.profile_id == chosen.id
    ]
    if not covering:
        return ProfileInForce(profile=chosen, valid_to=None, reason="")
    winner = max(covering, key=lambda row: (row.valid_from, row.id))
    return ProfileInForce(
        profile=chosen, valid_to=winner.valid_to, reason=winner.reason
    )


async def baseline_cap(db: AsyncSession) -> int | None:
    """
    The ordinary ceiling in minutes — what debt is always measured against.

    Read from the default profile rather than from the rule row: the two agree
    today, and the profile is the one a person edits when they disagree. `None`
    with no directory, and then nothing accrues: a system nobody set up owes
    nothing.
    """
    profiles, _ = _as_values(await list_profiles(db), [])
    chosen = baseline_profile(profiles)
    return None if chosen is None else chosen.work_cap_min


async def create_activation(
    db: AsyncSession,
    *,
    profile_id: int,
    valid_from: date,
    valid_to: date,
    reason: str,
    source_signal_id: str | None,
    confirmed_at: datetime | None,
) -> DayRuleActivation:
    """
    Write one activation. Without `confirmed_at` it decides nothing.

    A row is written either way, because a proposal that was shown and refused
    has to be remembered — otherwise the same reason is offered again the next
    morning, and a proposal a person has to refuse daily becomes one they accept.
    """
    row = DayRuleActivation(
        profile_id=profile_id,
        valid_from=valid_from,
        valid_to=valid_to,
        reason=reason,
        source_signal_id=source_signal_id,
        confirmed_at=confirmed_at,
        confirmed_by=CONFIRMED_BY_HUMAN if confirmed_at is not None else None,
    )
    db.add(row)
    await db.flush()
    return row


async def confirm_activation(
    db: AsyncSession, row: DayRuleActivation, at: datetime
) -> DayRuleActivation:
    """A person said yes; from this moment the activation decides dates."""
    row.confirmed_at = at
    row.confirmed_by = CONFIRMED_BY_HUMAN
    row.declined_at = None
    await db.flush()
    return row


async def decline_activation(
    db: AsyncSession, row: DayRuleActivation, at: datetime
) -> DayRuleActivation:
    """
    A person said no, or took a raise back before its end.

    The row stays and loses its confirmation rather than being deleted: the
    refusal is the fact that stops the same proposal from coming back.
    """
    row.confirmed_at = None
    row.confirmed_by = None
    row.declined_at = at
    await db.flush()
    return row


async def declined_signal_ids(db: AsyncSession) -> frozenset[str]:
    """Signals a person has already refused; a proposal never repeats one."""
    rows = await db.execute(
        select(DayRuleActivation.source_signal_id).where(
            DayRuleActivation.declined_at.is_not(None),
            DayRuleActivation.source_signal_id.is_not(None),
        )
    )
    return frozenset(str(value) for value in rows.scalars().all() if value)


async def open_debts(db: AsyncSession) -> list[OvertimeDebt]:
    """Every debt still owed, oldest first — the order it is repaid in."""
    return list(
        (
            await db.execute(
                select(OvertimeDebt)
                .where(OvertimeDebt.repaid_on.is_(None))
                .order_by(OvertimeDebt.incurred_on)
            )
        )
        .scalars()
        .all()
    )


async def list_debts(db: AsyncSession) -> list[OvertimeDebt]:
    """Every debt, open and repaid, newest first."""
    return list(
        (
            await db.execute(
                select(OvertimeDebt).order_by(OvertimeDebt.incurred_on.desc())
            )
        )
        .scalars()
        .all()
    )


async def open_debt_minutes(db: AsyncSession, start: date, end: date) -> int:
    """
    Minutes still owed by the days of `[start, end]`.

    Scoped to the range because that is what a week is judged with: a debt
    incurred in August must not keep September's weeks from ever being won.
    """
    total = (
        await db.execute(
            select(func.coalesce(func.sum(OvertimeDebt.minutes_over), 0)).where(
                OvertimeDebt.repaid_on.is_(None),
                OvertimeDebt.incurred_on >= start,
                OvertimeDebt.incurred_on <= end,
            )
        )
    ).scalar_one()
    return int(total)


async def settle_day(
    db: AsyncSession, on: date, work_minutes: int | None
) -> SettledDay:
    """
    Accrue what this day owes, then let it repay the oldest debt that fits.

    In that order, and the order is the meaning: a twelve-hour day must not pay
    back the debt it is in the middle of creating. Re-running on the same date
    restates its own row rather than adding a second — closing a day twice is
    normal (`#143` closes it in two touches), and a ledger that grew on each
    touch would owe double by evening.

    A day nobody measured neither accrues nor repays, exactly as `evaluate_day`
    reads it: «не измерено» is not zero.
    """
    baseline = await baseline_cap(db)
    if baseline is None:
        return SettledDay(accrued_minutes=0, repaid_on=None)
    owed = debt_rules.accrue(work_minutes, baseline)

    # Этот день уже что-то погасил на прошлом касании. Закрытие дня бывает
    # дважды (`#143`), и второе не должно гасить второй долг — иначе вечер
    # возвращает вдвое больше, чем человек отработал короче.
    already = (
        (await db.execute(select(OvertimeDebt).where(OvertimeDebt.repaid_by_day == on)))
        .scalars()
        .first()
    )

    existing = await db.get(OvertimeDebt, on)
    if owed > 0:
        if existing is None:
            db.add(OvertimeDebt(incurred_on=on, minutes_over=owed))
        elif existing.repaid_on is None:
            existing.minutes_over = owed
    elif existing is not None and existing.repaid_on is None:
        await db.delete(existing)
    await db.flush()

    if already is not None:
        return SettledDay(accrued_minutes=owed, repaid_on=already.incurred_on)

    repaid = debt_rules.repay(
        [
            debt_rules.Debt(
                incurred_on=row.incurred_on,
                minutes_over=row.minutes_over,
                repaid_on=row.repaid_on,
            )
            for row in await open_debts(db)
            if row.incurred_on != on
        ],
        work_minutes,
        baseline,
    )
    if repaid is None:
        return SettledDay(accrued_minutes=owed, repaid_on=None)

    row = await db.get(OvertimeDebt, repaid.incurred_on)
    if row is not None:
        row.repaid_on = on
        row.repaid_by_day = on
        await db.flush()
    return SettledDay(accrued_minutes=owed, repaid_on=repaid.incurred_on)


async def deadline_signals(db: AsyncSession) -> list[DeadlineSignal]:
    """
    Tasks of the work ClickUp whose deadline is near.

    Empty until `#103` brings the work inbox into this database, and empty is the
    honest answer rather than a degraded one: with no signals `propose_profile`
    proposes nothing, and nothing is exactly what should be proposed when nobody
    has told the system about a deadline.

    A function rather than a constant so the seam is named: `#103` fills this in
    and nothing else in `#179` changes.
    """
    _ = db
    return []
