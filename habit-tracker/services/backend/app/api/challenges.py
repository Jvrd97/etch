# [review:need-review] PHASE-03/127, PHASE-03/128
# summary: the challenge endpoints — create, list and read all bring the verdicts up to today before answering (there is no scheduler to do it for them), PATCH edits the promise without touching a single past verdict, and POST /recompute is the same materialization asked for out loud
"""
Периметр обязательств.

Каждое чтение доводит материализацию до сегодняшнего дня. Это не побочный
эффект чтения ради удобства, а единственный способ вообще: планировщика в
проекте нет, весь код исполняется внутри HTTP-запроса.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import challenge as challenge_crud
from app.crud.challenge import ChallengeRejected
from app.models.challenge import Challenge
from app.schemas.challenge import (
    ChallengeDayIn,
    ChallengeDayResponse,
    ChallengeDetailResponse,
    ChallengeIn,
    ChallengePatch,
    ChallengeResponse,
)

router = APIRouter(prefix="/challenges", tags=["challenges"])

CHALLENGE_NOT_FOUND = "челлендж {challenge_id} не найден"
DAY_OUTSIDE_WINDOW = (
    "день {day} лежит вне окна челленджа ({starts_on} — {ends_on}): "
    "засчитать можно только день, который в обязательство входит"
)


def _response(
    challenge: Challenge, counts: challenge_crud.ChallengeCounts
) -> ChallengeResponse:
    """Челлендж вместе со счётом, который печатает карточка."""
    return ChallengeResponse(
        id=challenge.id,
        title=challenge.title,
        category_id=challenge.category_id,
        field_id=challenge.field_id,
        rule_kind=challenge.rule_kind,
        target=challenge.target,
        starts_on=challenge.starts_on,
        ends_on=challenge.ends_on,
        failure_mode=challenge.failure_mode,
        allowed_misses=challenge.allowed_misses,
        status=challenge.status,
        failed_on=challenge.failed_on,
        total_days=counts.total_days,
        day_number=counts.day_number,
        done_count=counts.done_count,
        misses_used=counts.misses_used,
        misses_left=counts.misses_left,
        today_verdict=counts.today_verdict,
        created_at=challenge.created_at,
    )


async def _bring_up_to_date(
    db: AsyncSession, challenge: Challenge, today: date
) -> challenge_crud.ChallengeCounts:
    """
    Досчитать вердикты до сегодня, пересчитать статус и вернуть счёт.

    Порядок здесь не свободный: статус выводится из дней, поэтому сначала дни.
    Обратный порядок отдавал бы вчерашний статус вместе с сегодняшним счётом.
    """
    await challenge_crud.materialize(db, challenge, today=today)
    days = await challenge_crud.load_days(db, challenge.id)
    challenge_crud.apply_outcome(challenge, days, today=today)
    return challenge_crud.counts_of(challenge, days, today=today)


async def _require(db: AsyncSession, challenge_id: int) -> Challenge:
    """Челлендж или 404."""
    challenge = await challenge_crud.get_challenge(db, challenge_id)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CHALLENGE_NOT_FOUND.format(challenge_id=challenge_id),
        )
    return challenge


@router.post("", response_model=ChallengeResponse, status_code=status.HTTP_201_CREATED)
async def create_challenge(
    payload: ChallengeIn, db: AsyncSession = Depends(get_db)
) -> ChallengeResponse:
    """Завести обязательство и сразу досчитать его дни, если окно уже идёт."""
    try:
        challenge = await challenge_crud.create_challenge(
            db,
            title=payload.title,
            category_id=payload.category_id,
            field_id=payload.field_id,
            rule_kind=payload.rule_kind,
            target=payload.target,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
            failure_mode=payload.failure_mode,
            allowed_misses=payload.allowed_misses,
        )
    except ChallengeRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=rejected.message
        ) from rejected

    today = today_local()
    counts = await _bring_up_to_date(db, challenge, today)
    await db.commit()
    return _response(challenge, counts)


@router.get("", response_model=list[ChallengeResponse])
async def list_challenges(
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeResponse]:
    """Все обязательства, каждое досчитанное до вчерашнего дня включительно."""
    today = today_local()
    challenges = await challenge_crud.list_challenges(db)
    answer = [
        _response(challenge, await _bring_up_to_date(db, challenge, today))
        for challenge in challenges
    ]
    await db.commit()
    return answer


@router.get("/{challenge_id}", response_model=ChallengeDetailResponse)
async def get_challenge(
    challenge_id: int, db: AsyncSession = Depends(get_db)
) -> ChallengeDetailResponse:
    """Одно обязательство со всеми его днями."""
    today = today_local()
    challenge = await _require(db, challenge_id)
    await challenge_crud.materialize(db, challenge, today=today)
    days = await challenge_crud.load_days(db, challenge.id)
    challenge_crud.apply_outcome(challenge, days, today=today)
    counts = challenge_crud.counts_of(challenge, days, today=today)
    await db.commit()
    return ChallengeDetailResponse(
        **_response(challenge, counts).model_dump(),
        days=[ChallengeDayResponse.model_validate(row) for row in days],
    )


@router.patch("/{challenge_id}", response_model=ChallengeResponse)
async def patch_challenge(
    challenge_id: int, payload: ChallengePatch, db: AsyncSession = Depends(get_db)
) -> ChallengeResponse:
    """
    Поправить обязательство, не трогая ни одного прошедшего вердикта.

    Новая цель действует с этого момента вперёд. Пересчитывать прошлые дни по
    ней значило бы задним числом объявить сделанное несделанным — а история
    обязательства и есть то, ради чего у него отдельная таблица.
    """
    challenge = await _require(db, challenge_id)
    fields = payload.model_dump(exclude_unset=True)
    for name, value in fields.items():
        setattr(challenge, name, value)
    await db.flush()

    today = today_local()
    days = await challenge_crud.load_days(db, challenge.id)
    # Бюджет мог поменяться этим же запросом, поэтому статус пересчитывается —
    # но брошенный руками челлендж пересчёт назад не отыграет.
    challenge_crud.apply_outcome(challenge, days, today=today)
    counts = challenge_crud.counts_of(challenge, days, today=today)
    await db.commit()
    return _response(challenge, counts)


@router.put("/{challenge_id}/days/{day}", response_model=ChallengeDetailResponse)
async def set_day_verdict(
    challenge_id: int,
    day: date,
    payload: ChallengeDayIn,
    db: AsyncSession = Depends(get_db),
) -> ChallengeDetailResponse:
    """
    Засчитать или не засчитать день руками.

    Прямая реализация «ручной ввод правит автоматику»: строка получает
    `source='manual'`, и пересчёт её больше не трогает — ни в этот раз, ни через
    три `recompute`.

    Статус после этого считается заново, и это единственный путь, которым
    челлендж возвращается из `failed` в `active`. Без него «засчитываю этот
    день» было бы косметикой на дне, который уже никого не спасает.
    """
    challenge = await _require(db, challenge_id)
    if not (challenge.starts_on <= day <= challenge.ends_on):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DAY_OUTSIDE_WINDOW.format(
                day=day.isoformat(),
                starts_on=challenge.starts_on.isoformat(),
                ends_on=challenge.ends_on.isoformat(),
            ),
        )

    today = today_local()
    await challenge_crud.materialize(db, challenge, today=today)
    await challenge_crud.set_manual_verdict(
        db, challenge, day, verdict=payload.verdict, note=payload.note
    )
    days = await challenge_crud.load_days(db, challenge.id)
    challenge_crud.apply_outcome(challenge, days, today=today, by_hand=True)
    counts = challenge_crud.counts_of(challenge, days, today=today)
    await db.commit()
    return ChallengeDetailResponse(
        **_response(challenge, counts).model_dump(),
        days=[ChallengeDayResponse.model_validate(row) for row in days],
    )


@router.post("/{challenge_id}/recompute", response_model=ChallengeResponse)
async def recompute_challenge(
    challenge_id: int, db: AsyncSession = Depends(get_db)
) -> ChallengeResponse:
    """
    Та же материализация, попрошенная вслух.

    Идемпотентна по построению: upsert по `(challenge_id, day)` не плодит строк,
    а ручные вердикты не трогает.
    """
    today = today_local()
    challenge = await _require(db, challenge_id)
    counts = await _bring_up_to_date(db, challenge, today)
    await db.commit()
    return _response(challenge, counts)
