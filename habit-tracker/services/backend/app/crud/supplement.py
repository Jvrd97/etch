# [review:need-review] PHASE-03/223
# summary: database access for supplements — create/list/edit/archive/restore, and the intake mark that is idempotent on the key and on (supplement, logical day); the list answers taken_today in one extra query
"""
Database access for the supplement directory and the intake mark (`#223`).

**Число запросов не зависит от числа добавок.** Список читает добавки одним
запросом и отметки текущих суток вторым.

**Время ставит вызывающий.** `created_at`/`archived_at`/`taken_at` приходят
аргументом из `app.core.daytime.now_utc()`: единственные часы проекта, которые
тест умеет остановить, а день отметки считается от того же момента.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supplement import Supplement, SupplementIntake, SupplementIntakeKey
from app.schemas.supplement import SupplementCreate, SupplementUpdate

__all__ = [
    "archive_supplement",
    "create_supplement",
    "get_supplement",
    "alias_intake_key",
    "intake_by_idempotency_key",
    "intake_on_day",
    "list_supplements",
    "record_intake",
    "restore_supplement",
    "taken_on",
    "update_supplement",
]


async def create_supplement(
    db: AsyncSession, payload: SupplementCreate, now: datetime
) -> Supplement:
    supplement = Supplement(**payload.model_dump(), created_at=now)
    db.add(supplement)
    await db.commit()
    return supplement


async def get_supplement(db: AsyncSession, supplement_id: int) -> Supplement | None:
    return await db.get(Supplement, supplement_id)


async def list_supplements(
    db: AsyncSession, *, include_archived: bool
) -> list[Supplement]:
    statement = select(Supplement).order_by(Supplement.created_at, Supplement.id)
    if not include_archived:
        statement = statement.where(Supplement.archived_at.is_(None))
    return list((await db.execute(statement)).scalars().all())


async def taken_on(db: AsyncSession, day: date) -> set[int]:
    """Ids of the supplements with a mark on the logical day `day`."""
    result = await db.execute(
        select(SupplementIntake.supplement_id).where(
            SupplementIntake.intake_date == day
        )
    )
    return set(result.scalars().all())


async def update_supplement(
    db: AsyncSession, supplement: Supplement, payload: SupplementUpdate
) -> Supplement:
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(supplement, field, value)
    await db.commit()
    return supplement


async def archive_supplement(
    db: AsyncSession, supplement: Supplement, now: datetime
) -> Supplement:
    """Archive; archiving an archived supplement keeps the first moment."""
    if supplement.archived_at is None:
        supplement.archived_at = now
        await db.commit()
    return supplement


async def restore_supplement(db: AsyncSession, supplement: Supplement) -> Supplement:
    supplement.archived_at = None
    await db.commit()
    return supplement


async def intake_by_idempotency_key(
    db: AsyncSession, idempotency_key: str
) -> SupplementIntake | None:
    result = await db.execute(
        select(SupplementIntake)
        .join(SupplementIntakeKey, SupplementIntakeKey.intake_id == SupplementIntake.id)
        .where(SupplementIntakeKey.key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def intake_on_day(
    db: AsyncSession, supplement_id: int, day: date
) -> SupplementIntake | None:
    result = await db.execute(
        select(SupplementIntake).where(
            SupplementIntake.supplement_id == supplement_id,
            SupplementIntake.intake_date == day,
        )
    )
    return result.scalar_one_or_none()


async def record_intake(
    db: AsyncSession,
    supplement: Supplement,
    *,
    day: date,
    taken_at: datetime,
    idempotency_key: str | None,
) -> SupplementIntake:
    """
    Insert the mark and its key; a unique violation (a concurrent twin) is the caller's.

    The caller has already looked for a replay; the unique day and the key's primary
    key are the backstop for the race between that lookup and this insert.
    """
    intake = SupplementIntake(
        supplement_id=supplement.id, intake_date=day, taken_at=taken_at
    )
    db.add(intake)
    if idempotency_key is not None:
        await db.flush()
        db.add(SupplementIntakeKey(key=idempotency_key, intake_id=intake.id))
    await db.commit()
    return intake


async def alias_intake_key(
    db: AsyncSession, intake: SupplementIntake, idempotency_key: str
) -> None:
    """Remember a key that the day's dedup answered with an existing mark."""
    db.add(SupplementIntakeKey(key=idempotency_key, intake_id=intake.id))
    await db.commit()
