# [review:need-review] PHASE-03/223
# summary: /supplements — add, list (with taken_today), edit, archive, restore, and POST /{id}/intakes, the idempotent «принял» mark on the logical day; no name or dose in any log line
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.core.database import get_db
from app.crud import supplement as supplement_crud
from app.models.supplement import Supplement, SupplementIntake
from app.schemas.supplement import (
    IntakeRequest,
    IntakeResponse,
    SupplementCreate,
    SupplementListItem,
    SupplementResponse,
    SupplementUpdate,
)

router = APIRouter(prefix="/supplements", tags=["supplements"])


async def _existing(db: AsyncSession, supplement_id: int) -> Supplement:
    supplement = await supplement_crud.get_supplement(db, supplement_id)
    if supplement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supplement with id {supplement_id} not found",
        )
    return supplement


@router.post("", response_model=SupplementResponse, status_code=status.HTTP_201_CREATED)
async def create_supplement(
    payload: SupplementCreate, db: AsyncSession = Depends(get_db)
) -> Supplement:
    """Завести добавку: название, доза, единица и необязательное время приёма."""
    return await supplement_crud.create_supplement(db, payload, daytime.now_utc())


@router.get("", response_model=list[SupplementListItem])
async def list_supplements(
    include_archived: bool = Query(False, description="Показать и архивные"),
    db: AsyncSession = Depends(get_db),
) -> list[SupplementListItem]:
    """
    Добавки по порядку заведения; `taken_today` — отметка за текущие логические
    сутки сервера (до 04:00 это ещё вчерашний день).
    """
    supplements = await supplement_crud.list_supplements(
        db, include_archived=include_archived
    )
    taken = await supplement_crud.taken_on(db, daytime.today_local())
    return [
        SupplementListItem(
            **SupplementResponse.model_validate(s).model_dump(),
            taken_today=s.id in taken,
        )
        for s in supplements
    ]


@router.patch("/{supplement_id}", response_model=SupplementResponse)
async def update_supplement(
    supplement_id: int,
    payload: SupplementUpdate,
    db: AsyncSession = Depends(get_db),
) -> Supplement:
    """Правка присланных полей. `intake_time: null` снимает время приёма."""
    supplement = await _existing(db, supplement_id)
    return await supplement_crud.update_supplement(db, supplement, payload)


@router.post("/{supplement_id}/archive", response_model=SupplementResponse)
async def archive_supplement(
    supplement_id: int, db: AsyncSession = Depends(get_db)
) -> Supplement:
    """
    В архив: добавка уходит из плана с этого дня, история отметок остаётся.
    Повторный вызов момент архивации не двигает.
    """
    supplement = await _existing(db, supplement_id)
    return await supplement_crud.archive_supplement(db, supplement, daytime.now_utc())


@router.post("/{supplement_id}/restore", response_model=SupplementResponse)
async def restore_supplement(
    supplement_id: int, db: AsyncSession = Depends(get_db)
) -> Supplement:
    """Вернуть из архива."""
    supplement = await _existing(db, supplement_id)
    return await supplement_crud.restore_supplement(db, supplement)


@router.post(
    "/{supplement_id}/intakes",
    response_model=IntakeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def mark_intake(
    supplement_id: int,
    response: Response,
    payload: IntakeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SupplementIntake:
    """
    Отметка «принял» за текущие логические сутки сервера.

    День решает сервер (`app.core.daytime`): отметка в 03:30 — вчерашняя. Клиент
    может прислать `intake_date` как сверку часов; расхождение — 409.

    - **201** — отметка записана; **200** — повтор: тот же `Idempotency-Key`
      или уже стоящая отметка этой добавки за этот день (вторая не создаётся)
    - **404** — добавки нет; **409** — добавка в архиве либо день клиента не совпал
    """
    supplement = await _existing(db, supplement_id)
    if not supplement.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Supplement {supplement_id} is archived",
        )

    taken_at = daytime.now_utc()
    day = daytime.local_date(taken_at)
    client_day: date | None = payload.intake_date if payload else None
    if client_day is not None and client_day != day:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"the day has turned: client says {client_day.isoformat()}, "
                f"the server says {day.isoformat()}"
            ),
        )

    if idempotency_key is not None:
        replay = await supplement_crud.intake_by_idempotency_key(db, idempotency_key)
        if replay is not None:
            response.status_code = status.HTTP_200_OK
            return replay
    already = await supplement_crud.intake_on_day(db, supplement_id, day)
    if already is not None:
        response.status_code = status.HTTP_200_OK
        return already

    try:
        return await supplement_crud.record_intake(
            db,
            supplement,
            day=day,
            taken_at=taken_at,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        # A concurrent twin won the race between the lookups and the insert; the
        # unique constraints are the backstop. Answer with the winner.
        await db.rollback()
        winner = None
        if idempotency_key is not None:
            winner = await supplement_crud.intake_by_idempotency_key(
                db, idempotency_key
            )
        winner = winner or await supplement_crud.intake_on_day(db, supplement_id, day)
        if winner is None:
            raise
        response.status_code = status.HTTP_200_OK
        return winner
