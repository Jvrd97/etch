# [review:need-review] PHASE-03/92
# summary: GET/PUT /training/state (the snapshot recomputed on every read, plus the gated suggestion), GET/POST/PATCH /body-complaints (a symptom opens a gate, closing it reopens the movements) and GET/POST /personal-records
"""
Ручки тренировки.

**Состояние пересчитывается на чтении.** `GET /training/state` не отдаёт строку
как есть: он сворачивает `training_day` и `body_complaint` заново и записывает
снимок. Иначе снимок расходился бы с источником ровно на то время, что прошло с
последней записи, и снова стал бы тем, чем был `training/state.md`, — файлом,
которому надо верить на слово.

**Жалоба закрывается `PATCH`-ем, а не удалением.** Восемь дней, на которые
переезжала проверка плеча, — часть истории, и строка, которая просто исчезла бы,
унесла бы их с собой.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import training as training_crud
from app.models.training import COMPLAINT_STATUSES, COMPLAINT_CLOSED, BodyComplaint
from app.schemas.training import (
    BodyComplaintIn,
    BodyComplaintPatch,
    BodyComplaintResponse,
    ExcludedResponse,
    FiredGateResponse,
    PersonalRecordIn,
    PersonalRecordResponse,
    SuggestionResponse,
    TrainingStateIn,
    TrainingStateResponse,
)
from app.training.gates import Suggestion, suggest

router = APIRouter(tags=["training"])


def _suggestion(offer: Suggestion) -> SuggestionResponse:
    """The gated offer as the wire carries it."""
    return SuggestionResponse(
        exercises=list(offer.exercises),
        excluded=[
            ExcludedResponse(exercise=one.exercise, gate=one.gate, reason=one.reason)
            for one in offer.excluded
        ],
        gates=[
            FiredGateResponse(code=gate.code, reason=gate.reason)
            for gate in offer.gates
        ],
        rir=offer.rir,
        volume_factor=offer.volume_factor,
    )


async def _state(db: AsyncSession) -> TrainingStateResponse:
    """
    Recompute the state, store it, and answer with it and its suggestion.

    One answer rather than three requests: the page draws the state, the offer
    and the open complaints together, and a suggestion fetched apart from the
    state it was computed from is one round trip away from contradicting it.
    """
    as_of = today_local()
    row, snapshot = await training_crud.recompute_state(db, as_of)
    complaints = await training_crud.list_complaints(db, open_only=True)
    return TrainingStateResponse(
        as_of=snapshot.as_of,
        last_heavy_pull=snapshot.last_heavy_pull,
        last_heavy_push=snapshot.last_heavy_push,
        last_legs=snapshot.last_legs,
        last_run=snapshot.last_run,
        last_outdoor=snapshot.last_outdoor,
        last_cardio=snapshot.last_cardio,
        near_failure_days=list(snapshot.near_failure_days),
        week_sets=dict(snapshot.week_sets),
        progression_stage={
            key: str(value) for key, value in (row.progression_stage or {}).items()
        },
        skipped_days=snapshot.skipped_days,
        recomputed_at=row.recomputed_at,
        open_complaints=[
            BodyComplaintResponse.model_validate(one) for one in complaints
        ],
        records=[
            PersonalRecordResponse.model_validate(one)
            for one in await training_crud.list_records(db)
        ],
        suggestion=_suggestion(suggest(snapshot)),
    )


@router.get("/training/state", response_model=TrainingStateResponse)
async def get_training_state(
    db: AsyncSession = Depends(get_db),
) -> TrainingStateResponse:
    """
    Состояние тренировок: даты последних паттернов, объём недели, пропуски.

    Снимок пересчитывается на каждом чтении из `training_day` и `body_complaint`
    и тут же записывается — строка `training_state` производная и источником
    истины не является. `recomputed_at` в ответе говорит, когда это случилось.

    Вместе со снимком приезжают личные рекорды — каждый с датой достижения и
    целью за ним — и предложение тренировки со сработавшими гейтами:
    открытая жалоба, 48 часов между тяжёлыми повторами паттерна, два
    near-failure дня, недельный потолок подходов, возврат после пропусков.
    """
    return await _state(db)


@router.put("/training/state", response_model=TrainingStateResponse)
async def put_training_state(
    body: TrainingStateIn, db: AsyncSession = Depends(get_db)
) -> TrainingStateResponse:
    """
    Записать авторскую часть состояния — где стоит прогрессия.

    Больше в состоянии человеком не пишется ничего: даты последних паттернов,
    объём недели и пропуски выводятся из строк и присланными значениями
    перезаписаны быть не могут. Иначе состояние стало бы вторым источником
    истины и первым, который разойдётся с фактами.
    """
    await training_crud.set_progression(db, body.progression_stage)
    return await _state(db)


@router.get("/body-complaints", response_model=list[BodyComplaintResponse])
async def list_body_complaints(
    open_only: bool = Query(False, description="Только незакрытые жалобы"),
    db: AsyncSession = Depends(get_db),
) -> list[BodyComplaintResponse]:
    """
    Жалобы на тело, новые сверху.

    Жалоба — симптом для гейта, а не медицинская запись: область, обстоятельство
    и тяжесть словами человека. Диагнозов, назначений и анализов здесь нет.
    """
    rows = await training_crud.list_complaints(db, open_only=open_only)
    return [BodyComplaintResponse.model_validate(one) for one in rows]


@router.post(
    "/body-complaints",
    response_model=BodyComplaintResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_body_complaint(
    body: BodyComplaintIn, db: AsyncSession = Depends(get_db)
) -> BodyComplaintResponse:
    """
    Открыть жалобу. Она сразу гейтит предложение тренировки по своей области.

    Дата по умолчанию — сегодня по границе суток, а не по календарю браузера:
    жалоба, записанная в 00:30, относится к дню, который ещё идёт.
    """
    row = await training_crud.create_complaint(
        db,
        opened_on=body.opened_on or today_local(),
        area=body.area,
        context=body.context,
        severity=body.severity,
    )
    return BodyComplaintResponse.model_validate(row)


@router.patch("/body-complaints/{complaint_id}", response_model=BodyComplaintResponse)
async def patch_body_complaint(
    complaint_id: UUID, body: BodyComplaintPatch, db: AsyncSession = Depends(get_db)
) -> BodyComplaintResponse:
    """
    Закрыть жалобу — и вернуть в предложение движения, которые она снимала.

    Канон закрытия: день с нагрузкой на эту область и без симптомов. Причина
    записывается, потому что «прошло само» и «проверено под нагрузкой» — разные
    основания, и через месяц их не отличить по одной дате.
    """
    if body.status not in COMPLAINT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Статус жалобы — одно из {list(COMPLAINT_STATUSES)}.",
        )
    if body.status != COMPLAINT_CLOSED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Жалобу можно только закрыть: заново открытая жалоба — это новая "
                "жалоба с собственной датой, иначе история переездов проверки "
                "теряется."
            ),
        )
    row: BodyComplaint | None = await training_crud.close_complaint(
        db,
        complaint_id,
        closed_on=body.closed_on or today_local(),
        reason=body.closed_reason,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Жалобы {complaint_id} нет.",
        )
    return BodyComplaintResponse.model_validate(row)


@router.get("/personal-records", response_model=list[PersonalRecordResponse])
async def list_personal_records(
    db: AsyncSession = Depends(get_db),
) -> list[PersonalRecordResponse]:
    """
    Личные рекорды, свежие сверху — каждый с датой достижения и целью за ним.

    Подходы едут строкой: «9/10/5/3» это и рекорд, и диагноз — первый подход до
    отказа съел остальные три, и одно число вместо строки выкинуло бы ровно ту
    часть, ради которой запись делается.
    """
    rows = await training_crud.list_records(db)
    return [PersonalRecordResponse.model_validate(one) for one in rows]


@router.post(
    "/personal-records",
    response_model=PersonalRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_personal_record(
    body: PersonalRecordIn, db: AsyncSession = Depends(get_db)
) -> PersonalRecordResponse:
    """Записать личный рекорд. Дата по умолчанию — сегодня по границе суток."""
    row = await training_crud.create_record(
        db,
        exercise=body.exercise,
        variant=body.variant,
        sets=body.sets,
        best_plain=body.best_plain,
        achieved_on=body.achieved_on or today_local(),
        target=body.target,
    )
    return PersonalRecordResponse.model_validate(row)
