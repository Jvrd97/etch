# [review:need-review] PHASE-03/92
# summary: training persistence — one row per date with what was planned, done, skipped and set aside as the minimum, the recompute that writes `training_state` as a snapshot and carries the authored progression through untouched, the complaints that gate a suggestion, and the personal records
"""
Database access for training.

**Строка состояния переписывается целиком и только пересчётом.** `training_state`
хранит производное; единственная авторская колонка — `progression_stage`, и она
переносится через пересчёт как есть. Поэтому два пересчёта подряд дают ту же
строку и двигают только `recomputed_at` — что и есть приёмка тикета.

**Жалоба закрывается датой и причиной, а не исчезновением.** Канон закрытия —
день с нагрузкой на область и без симптомов; строка, которая просто пропала бы,
унесла бы с собой восемь дней, на которые проверка переезжала.

**Ничего отсюда не уходит в модель и в логи.** Жалоба на тело — симптом для
гейта, а не медицинская запись: `app.training.gates` получает только область,
LLM — ничего.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.training import (
    COMPLAINT_CLOSED,
    COMPLAINT_OPEN,
    TRAINING_STATE_ID,
    BodyComplaint,
    PersonalRecord,
    TrainingDay,
    TrainingState,
)
from app.training.state import (
    ComplaintFact,
    TrainingDayFact,
    TrainingSnapshot,
    recompute,
)

__all__ = [
    "close_complaint",
    "complaint_facts",
    "create_complaint",
    "create_record",
    "day_facts",
    "get_state",
    "get_training_day",
    "list_complaints",
    "list_records",
    "list_training_days",
    "recompute_state",
    "set_progression",
    "upsert_training_day",
]


def _now() -> datetime:
    """An aware moment, as every timestamptz in this service is written."""
    return datetime.now(timezone.utc)


async def get_training_day(db: AsyncSession, on: date) -> TrainingDay | None:
    """The training of one date, or None when the date has none recorded."""
    result = await db.execute(select(TrainingDay).where(TrainingDay.day_date == on))
    return result.scalar_one_or_none()


async def list_training_days(db: AsyncSession) -> list[TrainingDay]:
    """Every recorded day of training, oldest first."""
    result = await db.execute(select(TrainingDay).order_by(TrainingDay.day_date))
    return list(result.scalars().all())


async def upsert_training_day(
    db: AsyncSession,
    on: date,
    *,
    patterns: Sequence[str] | None = None,
    heavy_patterns: Sequence[str] | None = None,
    planned_md: str | None = None,
    done_md: str | None = None,
    skipped: bool | None = None,
    outdoor_done: bool | None = None,
    near_failure: bool | None = None,
    note_md: str | None = None,
    minimum_md: str | None = None,
    minimum_item_id: uuid.UUID | None = None,
    sets: dict[str, int] | None = None,
) -> TrainingDay:
    """
    Write the training of `on`, leaving alone every field the caller did not name.

    Field-by-field rather than whole-row because the two writers arrive at
    different times: `/day-open` plans in the morning and knows nothing about
    what happened, `/day-close` records the fact in the evening and must not
    erase the plan by omitting it.
    """
    row = await get_training_day(db, on)
    if row is None:
        row = TrainingDay(day_date=on)
        db.add(row)

    if patterns is not None:
        row.patterns = list(patterns)
    if heavy_patterns is not None:
        row.heavy_patterns = list(heavy_patterns)
    if planned_md is not None:
        row.planned_md = planned_md
    if done_md is not None:
        row.done_md = done_md
    if skipped is not None:
        row.skipped = skipped
    if outdoor_done is not None:
        row.outdoor_done = outdoor_done
    if near_failure is not None:
        row.near_failure = near_failure
    if note_md is not None:
        row.note_md = note_md
    if minimum_md is not None:
        row.minimum_md = minimum_md
    if minimum_item_id is not None:
        row.minimum_item_id = minimum_item_id
    if sets is not None:
        row.sets = dict(sets)

    await db.flush()
    return row


async def list_complaints(
    db: AsyncSession, *, open_only: bool = False
) -> list[BodyComplaint]:
    """Complaints, newest first; `open_only` is what a gate asks for."""
    statement = select(BodyComplaint).order_by(BodyComplaint.opened_on.desc())
    if open_only:
        statement = statement.where(BodyComplaint.status == COMPLAINT_OPEN)
    result = await db.execute(statement)
    return list(result.scalars().all())


async def create_complaint(
    db: AsyncSession,
    *,
    opened_on: date,
    area: str,
    context: str | None,
    severity: str | None,
) -> BodyComplaint:
    """Open a complaint. It starts `open` and closes only by an explicit answer."""
    row = BodyComplaint(
        id=uuid.uuid4(),
        opened_on=opened_on,
        area=area,
        context=context,
        severity=severity,
        status=COMPLAINT_OPEN,
    )
    db.add(row)
    await db.flush()
    return row


async def close_complaint(
    db: AsyncSession, complaint_id: uuid.UUID, *, closed_on: date, reason: str | None
) -> BodyComplaint | None:
    """
    Close a complaint, dating it and recording why.

    Returns None when there is no such row, so the API answers 404 rather than
    inventing a complaint that was never opened.
    """
    result = await db.execute(
        select(BodyComplaint).where(BodyComplaint.id == complaint_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.status = COMPLAINT_CLOSED
    row.closed_on = closed_on
    row.closed_reason = reason
    await db.flush()
    return row


async def list_records(db: AsyncSession) -> list[PersonalRecord]:
    """Personal records, most recent achievement first."""
    result = await db.execute(
        select(PersonalRecord).order_by(PersonalRecord.achieved_on.desc())
    )
    return list(result.scalars().all())


async def create_record(
    db: AsyncSession,
    *,
    exercise: str,
    variant: str | None,
    sets: str | None,
    best_plain: int | None,
    achieved_on: date,
    target: str | None,
) -> PersonalRecord:
    """Record one personal best, with the date it was reached."""
    row = PersonalRecord(
        id=uuid.uuid4(),
        exercise=exercise,
        variant=variant,
        sets=sets,
        best_plain=best_plain,
        achieved_on=achieved_on,
        target=target,
    )
    db.add(row)
    await db.flush()
    return row


def day_facts(rows: Sequence[TrainingDay]) -> list[TrainingDayFact]:
    """ORM rows as the plain values the pure recompute takes."""
    return [
        TrainingDayFact(
            day_date=row.day_date,
            patterns=tuple(row.patterns or ()),
            heavy_patterns=tuple(row.heavy_patterns or ()),
            sets={key: int(value) for key, value in (row.sets or {}).items()},
            skipped=row.skipped,
            outdoor_done=row.outdoor_done,
            near_failure=row.near_failure,
        )
        for row in rows
    ]


def complaint_facts(rows: Sequence[BodyComplaint]) -> list[ComplaintFact]:
    """
    Complaints reduced to what a gate weighs: the area, the date, the status.

    The context and the severity stay behind on purpose — they are the sentence
    a person wrote about a symptom, and nothing that decides a suggestion needs
    to carry it around.
    """
    return [
        ComplaintFact(area=row.area, opened_on=row.opened_on, status=row.status)
        for row in rows
    ]


async def get_state(db: AsyncSession) -> TrainingState | None:
    """The stored snapshot, or None before the first recompute."""
    result = await db.execute(
        select(TrainingState).where(TrainingState.id == TRAINING_STATE_ID)
    )
    return result.scalar_one_or_none()


async def set_progression(
    db: AsyncSession, progression_stage: dict[str, str]
) -> TrainingState:
    """
    Write the one authored field of the state — where the progression stands.

    «Объём 4x6-8 RIR 1-2» is a decision about the next four weeks, not a number
    derivable from what happened, so it is the single thing here a person sends
    and the single thing the recompute carries through untouched.
    """
    row = await get_state(db)
    if row is None:
        row = TrainingState(id=TRAINING_STATE_ID, recomputed_at=_now())
        db.add(row)
    row.progression_stage = dict(progression_stage)
    await db.flush()
    return row


async def recompute_state(
    db: AsyncSession, as_of: date
) -> tuple[TrainingState, TrainingSnapshot]:
    """
    Fold every recorded day into the snapshot and store it.

    Идемпотентен по построению: каждое записанное значение — функция строк,
    которых сам пересчёт не трогает, а единственная авторская колонка
    переносится как есть. Второй прогон подряд меняет только `recomputed_at`.
    """
    snapshot = recompute(
        day_facts(await list_training_days(db)),
        complaint_facts(await list_complaints(db)),
        as_of,
    )

    row = await get_state(db)
    if row is None:
        row = TrainingState(id=TRAINING_STATE_ID, progression_stage={})
        db.add(row)

    row.last_heavy_pull = snapshot.last_heavy_pull
    row.last_heavy_push = snapshot.last_heavy_push
    row.last_legs = snapshot.last_legs
    row.last_run = snapshot.last_run
    row.last_outdoor = snapshot.last_outdoor
    row.last_cardio = snapshot.last_cardio
    row.near_failure_days = list(snapshot.near_failure_days)
    row.week_sets = dict(snapshot.week_sets)
    row.skipped_days = snapshot.skipped_days
    row.recomputed_at = _now()

    await db.flush()
    return row, snapshot
