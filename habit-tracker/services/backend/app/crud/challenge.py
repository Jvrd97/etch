# [review:need-review] PHASE-03/127
# summary: lazy materialization of a challenge — one query of the window's entries, `verdict_for_day` over each day, and an upsert on `(challenge_id, day)` that refuses to touch a row a person set by hand; plus the counts the card prints
"""
Челлендж: чтение окна, ленивая материализация вердиктов, счёт.

**Материализация ленивая, потому что планировщика нет.** Весь код исполняется
внутри HTTP-запроса, поэтому вердикты доводятся до сегодняшнего дня при чтении
челленджа — плюс явный `recompute`. Следствие принято сознательно: челлендж, о
котором забыли на неделю, досчитается разом при следующем открытии, а не
останется с дырой в середине.

**Идемпотентность живёт на естественном ключе.** Upsert по
`(challenge_id, day)`: два `recompute` подряд оставляют то же число строк и те
же вердикты, потому что второй заход приземляется на строки первого.

**Вердикт закрытого дня пишется один раз.** Условие `ON CONFLICT DO UPDATE`
пропускает только день, который ещё идёт, и день, оставшийся в `pending` с
прошлого захода. Отсюда свойство, ради которого челлендж вообще стал таблицей:
поднятая сегодня планка не объявляет несделанной прошлую неделю.

**Ручной вердикт пересчёт не перетирает.** `source <> 'manual'` стоит в том же
условии, то есть в базе, а не в ветке Python: приоритет ручного ввода над
автоматикой — свойство записи, а не аккуратности вызывающего.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.rules import (
    SOURCE_COMPUTED,
    SOURCE_MANUAL,
    VERDICT_MISS,
    VERDICT_PENDING,
    ChallengeRule,
    DaySample,
    Verdict,
    verdict_for_day,
)
from app.core.daytime import today_local
from app.models import Entry, EntryValue, Field
from app.models.challenge import Challenge, ChallengeDay
from app.models.field import FieldType

logger = logging.getLogger(__name__)


class ChallengeRejected(Exception):
    """Челлендж не заводится: правило указывает на то, чего нет."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


FIELD_NOT_IN_CATEGORY = (
    "поле {field_id} не принадлежит категории {category_id}: правило челленджа "
    "указывает на пару, которой нет"
)


@dataclass(frozen=True)
class ChallengeCounts:
    """Счёт обязательства: то, что печатает карточка."""

    total_days: int
    day_number: int
    done_count: int
    misses_used: int
    today_verdict: Verdict | None


def rule_of(challenge: Challenge) -> ChallengeRule:
    """Правило челленджа как чистое значение, без строки таблицы вокруг."""
    return ChallengeRule(kind=challenge.rule_kind, target=challenge.target)


async def _field_type(db: AsyncSession, field_id: int) -> FieldType | None:
    """Тип поля, по которому считается правило."""
    result = await db.execute(select(Field.field_type).where(Field.id == field_id))
    return result.scalar_one_or_none()


async def _samples(
    db: AsyncSession, challenge: Challenge, upto: date
) -> dict[date, DaySample]:
    """
    Что записано в окне челленджа, по дням.

    Один запрос на всё окно, а не по запросу на день: окно ограничено 92 днями,
    и 92 обращения в базу ради одной карточки — это тот случай, когда ленивость
    материализации перестала бы окупаться.

    `isouter` на значениях существенен: запись без значения в нужном поле — всё
    равно запись, и `has_entry` у такого дня истинен. Именно этим «день, в
    который человек открыл трекер и ничего не налил» отличается от дня, про
    который неизвестно ничего.
    """
    result = await db.execute(
        select(Entry.entry_date, EntryValue.value)
        .join(
            EntryValue,
            (EntryValue.entry_id == Entry.id)
            & (EntryValue.field_id == challenge.field_id),
            isouter=True,
        )
        .where(
            Entry.category_id == challenge.category_id,
            Entry.entry_date >= challenge.starts_on,
            Entry.entry_date <= upto,
        )
    )

    collected: dict[date, list[str | None]] = {}
    for entry_date, value in result.all():
        bucket = collected.setdefault(entry_date, [])
        if value is not None:
            bucket.append(value)

    return {
        day: DaySample(has_entry=True, values=tuple(values))
        for day, values in collected.items()
    }


EMPTY_DAY = DaySample(has_entry=False, values=())


async def materialize(
    db: AsyncSession, challenge: Challenge, *, today: date | None = None
) -> int:
    """
    Довести вердикты челленджа до сегодняшнего дня включительно.

    Возвращает число дней, по которым прошёлся. Сегодняшний день пишется тоже —
    как `pending` или уже `done`; промахом он станет, когда `local_date()`
    назовёт следующее число. Дни после сегодняшнего не пишутся вовсе: у них
    ещё нет ни данных, ни повода для строки.
    """
    now_day = today if today is not None else today_local()
    upto = min(challenge.ends_on, now_day)
    if upto < challenge.starts_on:
        return 0

    field_type = await _field_type(db, challenge.field_id)
    if field_type is None:
        # Поле удалить нельзя (RESTRICT), но читатель не обязан в это верить.
        return 0

    samples = await _samples(db, challenge, upto)
    rule = rule_of(challenge)

    rows: list[dict[str, object]] = []
    day = challenge.starts_on
    while day <= upto:
        verdict = verdict_for_day(
            rule,
            field_type,
            samples.get(day, EMPTY_DAY),
            is_closed=day < now_day,
        )
        rows.append(
            {
                "challenge_id": challenge.id,
                "day": day,
                "verdict": verdict,
                "source": SOURCE_COMPUTED,
            }
        )
        day += timedelta(days=1)

    statement = pg_insert(ChallengeDay).values(rows)
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_challenge_day",
            set_={"verdict": statement.excluded.verdict},
            where=(
                # Ручной вердикт первичен: пересчёт его не трогает никогда.
                (ChallengeDay.source != SOURCE_MANUAL)
                # Вердикт закрытого дня пишется один раз — правилом своего
                # времени. Поднятая сегодня планка не делает несделанной
                # прошлую неделю; меняться может только день, который ещё идёт,
                # и день, оставшийся в `pending` с прошлого захода.
                & (
                    (ChallengeDay.verdict == VERDICT_PENDING)
                    | (ChallengeDay.day >= now_day)
                )
            ),
        )
    )
    await db.flush()

    # Только идентификаторы: заголовок челленджа — это то, что человек про себя
    # обещал, и в логе ему делать нечего.
    logger.info(
        "challenge %s materialized %s days up to %s", challenge.id, len(rows), upto
    )
    return len(rows)


async def load_days(db: AsyncSession, challenge_id: int) -> Sequence[ChallengeDay]:
    """Материализованные дни челленджа, по возрастанию даты."""
    result = await db.execute(
        select(ChallengeDay)
        .where(ChallengeDay.challenge_id == challenge_id)
        .order_by(ChallengeDay.day)
    )
    return result.scalars().all()


def counts_of(
    challenge: Challenge, days: Sequence[ChallengeDay], *, today: date
) -> ChallengeCounts:
    """
    Счёт обязательства по его дням.

    Чистая функция над уже прочитанными строками: карточка, список и вердикт
    статуса считают одно и то же одним кодом.
    """
    total_days = (challenge.ends_on - challenge.starts_on).days + 1
    if today < challenge.starts_on:
        day_number = 0
    elif today > challenge.ends_on:
        day_number = total_days
    else:
        day_number = (today - challenge.starts_on).days + 1

    done_count = sum(1 for row in days if row.verdict == "done")
    misses_used = sum(1 for row in days if row.verdict == VERDICT_MISS)
    today_verdict: Verdict | None = None
    for row in days:
        if row.day == today:
            today_verdict = row.verdict  # type: ignore[assignment]
            break

    return ChallengeCounts(
        total_days=total_days,
        day_number=day_number,
        done_count=done_count,
        misses_used=misses_used,
        today_verdict=today_verdict,
    )


async def create_challenge(
    db: AsyncSession,
    *,
    title: str,
    category_id: int,
    field_id: int,
    rule_kind: str,
    target: object,
    starts_on: date,
    ends_on: date,
    failure_mode: str,
    allowed_misses: int,
) -> Challenge:
    """
    Завести обязательство.

    Пара `(category_id, field_id)` проверяется до вставки: внешние ключи
    удержат каждый идентификатор по отдельности, но не то, что поле относится
    именно к этой категории, — а правило по чужому полю всегда считало бы
    пустой день.
    """
    result = await db.execute(
        select(Field.id).where(Field.id == field_id, Field.category_id == category_id)
    )
    if result.scalar_one_or_none() is None:
        raise ChallengeRejected(
            FIELD_NOT_IN_CATEGORY.format(field_id=field_id, category_id=category_id)
        )

    challenge = Challenge(
        title=title,
        category_id=category_id,
        field_id=field_id,
        rule_kind=rule_kind,
        target=target,
        starts_on=starts_on,
        ends_on=ends_on,
        failure_mode=failure_mode,
        allowed_misses=allowed_misses,
    )
    db.add(challenge)
    await db.flush()
    await db.refresh(challenge)
    return challenge


async def get_challenge(db: AsyncSession, challenge_id: int) -> Challenge | None:
    """Одно обязательство по идентификатору."""
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    return result.scalar_one_or_none()


async def list_challenges(db: AsyncSession) -> Sequence[Challenge]:
    """
    Все обязательства, свежие сверху.

    Завершённые остаются в списке: «сколько раз я это заваливал» — и есть та
    история, ради которой челлендж не стал полем у категории.
    """
    result = await db.execute(
        select(Challenge).order_by(Challenge.starts_on.desc(), Challenge.id.desc())
    )
    return result.scalars().all()
