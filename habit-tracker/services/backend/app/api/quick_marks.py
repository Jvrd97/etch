# [review:need-review] PHASE-03/121
# summary: the quick-mark endpoints — the directory read with the day's state on it, the button entered by hand with every reason it is refused, and the one write path `POST /quick-marks/{id}/events`, whose answer carries the new state so a tap costs one network call
"""
The whole contract of a quick mark: read the buttons, tap one.

Two endpoints are the entire surface the floating window of the macOS agent
needs — `GET /quick-marks?date=` and `POST /quick-marks/{id}/events` — and
neither of them mentions a category, a field or a display mode. The third,
`POST /quick-marks`, exists because the directory starts empty and the buttons
are entered by hand until the management screen of `#125` arrives.

The day of a tap is decided by `app.core.daytime.local_date()` on the moment the
request is served. There is no timezone setting in this module and no second
answer to "какое сегодня число".
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import local_date
from app.crud import category as category_crud
from app.crud import quick_mark as quick_mark_crud
from app.models.quick_mark import QuickMark
from app.schemas.quick_mark import (
    QuickMarkCreate,
    QuickMarkEventRequest,
    QuickMarkEventResponse,
    QuickMarkResponse,
    QuickMarkTodayResponse,
)

router = APIRouter(prefix="/quick-marks", tags=["quick-marks"])


def _to_today_response(
    mark: QuickMark, state: quick_mark_crud.DayState, on: date
) -> QuickMarkTodayResponse:
    """One button plus the day it was read for, as the wire carries it."""
    return QuickMarkTodayResponse(
        **QuickMarkResponse.model_validate(mark).model_dump(),
        entry_date=on,
        today_total=state.today_total,
        done=state.done,
    )


def _to_event_response(
    recorded: quick_mark_crud.RecordedEvent,
) -> QuickMarkEventResponse:
    """The recorded tap and the state it produced."""
    return QuickMarkEventResponse(
        event_id=recorded.event_id,
        quick_mark_id=recorded.quick_mark_id,
        entry_id=recorded.entry_id,
        entry_date=recorded.entry_date,
        occurred_at=recorded.occurred_at,
        today_total=recorded.state.today_total,
        done=recorded.state.done,
    )


@router.get("", response_model=list[QuickMarkTodayResponse])
async def list_quick_marks(
    date_: date | None = Query(
        None,
        alias="date",
        description="День, состояние которого навесить на кнопки; по умолчанию сегодня",
    ),
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[QuickMarkTodayResponse]:
    """
    Справочник кнопок, обогащённый состоянием дня.

    Пустой справочник — валидный ответ (`[]`), а не ошибка: кнопки заводятся
    руками, и до первой из них Today просто не показывает секцию.

    `date` по умолчанию — день, которому принадлежит текущий момент по
    `local_date()`. Клиенту не нужно знать ни часовой пояс, ни час начала дня.
    """
    on = date_ if date_ is not None else local_date(datetime.now(timezone.utc))
    marks = await quick_mark_crud.list_quick_marks(db, on=on, active_only=active_only)
    return [_to_today_response(mark, state, on) for mark, state in marks]


@router.post("", response_model=QuickMarkResponse, status_code=status.HTTP_201_CREATED)
async def create_quick_mark(
    payload: QuickMarkCreate,
    db: AsyncSession = Depends(get_db),
) -> QuickMarkResponse:
    """
    Завести кнопку.

    Проверяется то, чего в `POST /entries` нет вообще: поле принадлежит своей
    категории, `kind` совместим с типом поля, у числовой кнопки есть шаг, а
    `relapse` стоит на avoid-категории. Причины возвращаются списком — одна
    правка чинит всё сразу.

    - **422** — справочник отверг кнопку; в `detail` перечислены все причины
    - **409** — такой `hotkey` уже занят другой кнопкой
    """
    category = await category_crud.get_category(db, payload.category_id)
    errors = quick_mark_crud.validate_quick_mark(payload, category)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors)
        )

    try:
        mark = await quick_mark_crud.create_quick_mark(db, payload)
    except IntegrityError:
        # The only unique thing about a button is its hotkey, and the partial
        # index is what enforces it. Naming the key rather than the label keeps
        # the message free of anything the user typed.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"hotkey {payload.hotkey!r} is already taken by another quick mark",
        ) from None
    return QuickMarkResponse.model_validate(mark)


@router.post(
    "/{quick_mark_id}/events",
    response_model=QuickMarkEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_quick_mark_event(
    quick_mark_id: int,
    payload: QuickMarkEventRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> QuickMarkEventResponse:
    """
    Отметить: один вызов на тап.

    Клиент присылает id кнопки — что она значит и куда ложится, решает сервер.
    Ответ несёт новое состояние дня (`today_total`, `done`), поэтому экран
    перерисовывается без второго запроса.

    День отметки — `local_date()` от момента запроса. Клиент может прислать
    `entry_date`, но это не адрес записи, а сверка часов: расхождение — 409, а
    не тихая запись во вчера.

    - **201** — тап записан; **200** — повтор того же `Idempotency-Key`
    - **404** — такой кнопки нет
    - **409** — кнопка выключена, либо `entry_date` не совпал с днём сервера
    """
    mark = await quick_mark_crud.get_quick_mark(db, quick_mark_id)
    if mark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quick mark with id {quick_mark_id} not found",
        )
    if not mark.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Quick mark {quick_mark_id} is not active",
        )

    at = datetime.now(timezone.utc)
    on = local_date(at)
    if payload.entry_date is not None and payload.entry_date != on:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"the day has turned: client says {payload.entry_date.isoformat()}, "
                f"the server says {on.isoformat()}"
            ),
        )

    if idempotency_key is not None:
        existing = await quick_mark_crud.event_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return _to_event_response(
                await quick_mark_crud.replayed_event(db, mark, existing)
            )

    try:
        recorded = await quick_mark_crud.record_event(
            db,
            mark,
            at=at,
            value=payload.value,
            utc_offset_minutes=payload.utc_offset_minutes,
            source=payload.source,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        # A concurrent replay won the race between the lookup and the insert;
        # the unique constraint is the backstop. Re-read and answer with the
        # winner, exactly as `POST /entries` does.
        await db.rollback()
        if idempotency_key is None:
            raise
        winner = await quick_mark_crud.event_by_idempotency_key(db, idempotency_key)
        if winner is None:
            raise
        response.status_code = status.HTTP_200_OK
        return _to_event_response(
            await quick_mark_crud.replayed_event(db, mark, winner)
        )

    return _to_event_response(recorded)
