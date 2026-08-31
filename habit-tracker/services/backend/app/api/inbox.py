# [review:need-review] PHASE-03/97
# summary: the inbox endpoints — the feed of signals with the same 366-day range limit table and health use, the source directory, and the manual poll a person presses (and the mac agent calls) until the worker of #99 exists
"""
Входящие: лента сигналов, справочник источников и ручной прогон.

Прогон здесь ручной намеренно. Расписание живёт в отдельном процессе-воркере
(ADR-0016, D4) и приезжает в `#99`; ручка остаётся и после него — ею пользуются
маковый агент, отладка и человек, которому надо перечитать источник сейчас, а не
через пятнадцать минут.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import inbox as inbox_crud
from app.models.inbox import SignalSource
from app.schemas.inbox import (
    CredentialsIn,
    PollResponse,
    SignalResponse,
    SourcePatch,
    SourceResponse,
)

router = APIRouter(prefix="/inbox", tags=["inbox"])

# Тот же потолок, что у table и health: год с хвостом. Разные ответы на «какой
# диапазон слишком длинный» в одном API — способ сделать лимит незапоминаемым.
MAX_RANGE_DAYS = 366

# Сколько строк отдаёт лента за раз. Экран показывает неразобранное, а не архив.
DEFAULT_LIMIT = 200


@router.get("/signals", response_model=list[SignalResponse])
async def list_signals(
    state: str | None = Query(default=None),
    source_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[SignalResponse]:
    """
    Лента входящих, свежие сверху.

    - **state**: `new` | `parsed` | `ignored` | `duplicate`
    - **date_from**, **date_to**: по локальной дате сигнала, не более 366 дней
    """
    if date_from is not None and date_to is not None:
        if date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_from must be <= date_to",
            )
        range_days = (date_to - date_from).days + 1
        if range_days > MAX_RANGE_DAYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"date range is too long: {range_days} days requested, "
                    f"maximum is {MAX_RANGE_DAYS} days"
                ),
            )

    rows = await inbox_crud.list_signals(
        db,
        state=state,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return [SignalResponse.model_validate(row) for row in rows]


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(db: AsyncSession = Depends(get_db)) -> list[SourceResponse]:
    """Справочник источников: что подключено, что заготовка, когда читали."""
    rows = await inbox_crud.list_sources(db)
    return [_as_source(row) for row in rows]


def _as_source(row: SignalSource) -> SourceResponse:
    """
    Строка источника наружу — без секрета в любом виде.

    `has_secret` собирается здесь, а не в модели: в базе лежит шифротекст, и
    единственное, что о нём можно сказать снаружи, — есть он или нет.
    """
    return SourceResponse(
        id=row.id,
        provider=row.provider,
        account=row.account,
        label=row.label,
        direction=row.direction,
        is_active=row.is_active,
        poll_interval_s=row.poll_interval_s,
        credential_ref=row.credential_ref,
        has_secret=row.secret_ciphertext is not None,
        settings={str(k): str(v) for k, v in (row.settings or {}).items()},
        last_polled_at=row.last_polled_at,
        last_error_code=row.last_error_code,
    )


@router.put("/sources/{source_id}/credentials", response_model=SourceResponse)
async def set_credentials(
    source_id: int, payload: CredentialsIn, db: AsyncSession = Depends(get_db)
) -> SourceResponse:
    """
    Задать источнику ключ и настройки — прямо здесь, без захода на сервер.

    Секрет сохраняется зашифрованным и обратно не отдаётся никогда: ответ
    говорит «задан», и это всё, что экрану нужно знать.
    """
    source = await db.get(SignalSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
        )
    await inbox_crud.set_credentials(
        db, source, secret=payload.secret, settings=payload.settings
    )
    return _as_source(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def patch_source(
    source_id: int, payload: SourcePatch, db: AsyncSession = Depends(get_db)
) -> SourceResponse:
    """Включить, выключить, переименовать или сменить интервал опроса."""
    source = await db.get(SignalSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
        )
    if payload.is_active is not None:
        source.is_active = payload.is_active
    if payload.label is not None:
        source.label = payload.label
    if payload.poll_interval_s is not None:
        source.poll_interval_s = payload.poll_interval_s
    await db.commit()
    await db.refresh(source)
    return _as_source(source)


@router.post("/sources/{source_id}/poll", response_model=PollResponse)
async def poll_source(
    source_id: int, db: AsyncSession = Depends(get_db)
) -> PollResponse:
    """
    Прочитать источник сейчас.

    Отказ приезжает кодом состояния и машинным кодом в теле: «выключен», «нет
    адаптера» и «нет токена» — три разных состояния, и экран показывает их
    по-разному. Текста ответа провайдера здесь нет никогда.
    """
    source = await db.get(SignalSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
        )
    try:
        outcome = await inbox_crud.poll_source(db, source)
    except inbox_crud.PollRefused as refusal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": refusal.code, "message": refusal.message},
        ) from refusal
    return PollResponse(ingested=outcome.ingested, updated=outcome.updated)
