# [review:need-review] PHASE-03/121, PHASE-03/124, PHASE-03/125, PHASE-03/130
# summary: the quick-mark endpoints — the directory read with the day's state on it, the button entered, patched, reordered and deleted by hand with every reason it is refused, and the one write path POST /quick-marks/{id}/events, whose answer carries the new state so a tap costs one network call; the undo of the last tap and the split of taps by source
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

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import local_date
from app.crud import category as category_crud
from app.crud import quick_mark as quick_mark_crud
from app.models.quick_mark import QuickMark
from app.schemas.quick_mark import (
    SURFACES,
    HotkeyTaken,
    QuickMarkOrderIn,
    QuickMarkUpdate,
    QuickMarkCreate,
    QuickMarkEventRequest,
    QuickMarkEventResponse,
    QuickMarkResponse,
    QuickMarkSourceUsage,
    QuickMarkTodayResponse,
    QuickMarkUndoResponse,
)

router = APIRouter(prefix="/quick-marks", tags=["quick-marks"])


def _to_today_response(
    listed: quick_mark_crud.ListedMark, on: date
) -> QuickMarkTodayResponse:
    """One button plus the day it was read for, as the wire carries it."""
    return QuickMarkTodayResponse(
        **QuickMarkResponse.model_validate(listed.mark).model_dump(),
        entry_date=on,
        today_total=listed.state.today_total,
        done=listed.state.done,
        planned=listed.planned,
        plan_item_id=listed.planned_item_id,
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


def _etag(marks: list[QuickMarkTodayResponse]) -> str:
    """
    Отпечаток выдачи целиком, а не `updated_at` справочника.

    Окно агента опрашивает эту ручку каждые несколько секунд, и меняется в
    ответе чаще всего не строка справочника, а состояние дня: чужой тап сдвинул
    сумму. Отпечаток по `quick_marks.updated_at` этого не заметил бы и отдавал
    бы 304 на изменившийся день — то есть окно врало бы ровно про то, ради чего
    его открыли.
    """
    payload = json.dumps(
        [one.model_dump(mode="json") for one in marks],
        ensure_ascii=False,
        sort_keys=True,
    )
    return '"' + sha256(payload.encode("utf-8")).hexdigest()[:32] + '"'


@router.get("", response_model=list[QuickMarkTodayResponse])
async def list_quick_marks(
    response: Response,
    date_: date | None = Query(
        None,
        alias="date",
        description="День, состояние которого навесить на кнопки; по умолчанию сегодня",
    ),
    surface: str | None = Query(
        None,
        description=(
            "Кто спрашивает: web | agent | ios. `agent` оставляет только "
            "кнопки с `show_in_agent`. Неизвестное значение — 422"
        ),
    ),
    active_only: bool = True,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Справочник кнопок, обогащённый состоянием дня.

    Пустой справочник — валидный ответ (`[]`), а не ошибка: кнопки заводятся
    руками, и до первой из них Today просто не показывает секцию.

    `date` по умолчанию — день, которому принадлежит текущий момент по
    `local_date()`. Клиенту не нужно знать ни часовой пояс, ни час начала дня.

    Кнопки, названные планом на запрошенный день, помечены `planned` и стоят
    первыми (#130). Порядок считает сервер: выдача одна на веб, окно агента и
    iOS, и порядок, посчитанный в браузере, был бы порядком, которого нет у двух
    остальных. `date` за прошедший день отдаёт план **того** дня.
    """
    if surface is not None and surface not in SURFACES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"unknown surface {surface!r}; expected one of {', '.join(SURFACES)}"
            ),
        )
    on = date_ if date_ is not None else local_date(datetime.now(timezone.utc))
    marks = await quick_mark_crud.list_quick_marks(
        db, on=on, active_only=active_only, surface=surface
    )
    body = [_to_today_response(listed, on) for listed in marks]
    tag = _etag(body)
    if if_none_match is not None and if_none_match == tag:
        # Пустой ответ без тела: опрос окна не имеет права качать двадцать строк
        # каждые несколько секунд ради того, что не изменилось.
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    response.headers["ETag"] = tag
    return body


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

    # Клавиша проверяется до записи (#125): отказ обязан назвать кнопку, которая
    # её держит, а `IntegrityError` называет имя индекса — по нему форму не
    # починить, и заполненное в ней теряется.
    if payload.hotkey is not None:
        owner = await quick_mark_crud.hotkey_owner(db, payload.hotkey)
        if owner is not None:
            raise _hotkey_conflict(payload.hotkey, owner)

    try:
        mark = await quick_mark_crud.create_quick_mark(db, payload)
    except IntegrityError:
        # Сеть на гонку двух вкладок: индекс остаётся гарантией, эта ветка —
        # ответом, когда обе прошли проверку до записи.
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


def _hotkey_conflict(hotkey: str, owner: QuickMark) -> HTTPException:
    """
    409, называющий кнопку, которая держит клавишу.

    Не «нарушение уникальности»: человеку нужно знать, у кого её отобрать, и
    вернуться в форму, не потеряв заполненное. Поэтому в теле и id, и подпись.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=HotkeyTaken(
            message=(
                f"клавиша {hotkey!r} уже стоит у кнопки {owner.label!r} (id {owner.id})"
            ),
            hotkey=hotkey,
            quick_mark_id=owner.id,
            label=owner.label,
        ).model_dump(),
    )


@router.get("/events/sources", response_model=list[QuickMarkSourceUsage])
async def quick_mark_source_usage(
    from_: date | None = Query(
        None, alias="from", description="Первый день периода включительно"
    ),
    to: date | None = Query(None, description="Последний день периода включительно"),
    db: AsyncSession = Depends(get_db),
) -> list[QuickMarkSourceUsage]:
    """
    Откуда отметки приходят на самом деле.

    Тот самый вопрос, ради которого в журнале появился `source`: если за месяц
    почти всё пришло из одного клиента, второй путь закрывается по данным, а не
    по вкусу. Отменённые тапы считаются отдельной колонкой, а не вычитаются, —
    клиент, у которого половина тапов отменяется, это факт о клиенте.

    Клиенты, которые за период не написали ничего, в ответе отсутствуют: ответ
    описывает спрошенные дни, а строка нулей была бы утверждением о клиенте,
    который ничего не писал.
    """
    usage = await quick_mark_crud.source_usage(db, since=from_, until=to)
    return [
        QuickMarkSourceUsage(source=row.source, events=row.events, undone=row.undone)
        for row in usage
    ]


@router.post("/events/{event_id}/undo", response_model=QuickMarkUndoResponse)
async def undo_quick_mark_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
) -> QuickMarkUndoResponse:
    """
    Отменить последний тап.

    Кнопка нажимается одной клавишей, поэтому и отменяться обязана одним
    действием: без этого ошибочный тап чинится походом в редактор записи, и
    цена ошибки съедает выигрыш от скорости.

    Правило узкое намеренно. Отменяется **только** последний неотменённый тап
    этой кнопки и **только** если значение с тех пор не менялось мимо журнала.
    Расхождение журнала и `entry_values` разрешено ADR-0018 — ручной ввод
    первичен, — поэтому по правленому руками значению приходит отказ, а не
    попытка починить расхождение вычитанием.

    - **200** — тап отменён; в ответе новое состояние дня
    - **404** — такого события нет
    - **409** — уже отменён, не последний, либо значение правили руками
    """
    event = await quick_mark_crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quick mark event with id {event_id} not found",
        )

    mark = await quick_mark_crud.get_quick_mark(db, event.quick_mark_id)
    if mark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quick mark with id {event.quick_mark_id} not found",
        )

    try:
        undone = await quick_mark_crud.undo_event(
            db, mark, event, at=datetime.now(timezone.utc)
        )
    except quick_mark_crud.UndoRefused as refused:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=refused.message
        ) from None

    return QuickMarkUndoResponse(
        event_id=undone.event_id,
        quick_mark_id=undone.quick_mark_id,
        entry_date=undone.entry_date,
        undone_at=undone.undone_at,
        today_total=undone.state.today_total,
        done=undone.state.done,
    )


@router.patch(
    "/order",
    response_model=list[QuickMarkResponse],
)
async def reorder_quick_marks(
    payload: QuickMarkOrderIn, db: AsyncSession = Depends(get_db)
) -> list[QuickMarkResponse]:
    """
    Переставить кнопки: список id сверху вниз.

    Отдельная ручка, а не `order` в патче: перестановка меняет номера сразу
    нескольких кнопок, и построчная запись оставила бы справочник с дырами и
    дублями — то же решение, что у пунктов плана в `#110`.

    Стоит выше `/{quick_mark_id}`, потому что иначе `order` читался бы как id.

    Кнопки, которых нет в списке, уезжают под него в прежнем порядке: экран мог
    собрать порядок до того, как соседняя вкладка завела новую кнопку.
    """
    marks = await quick_mark_crud.reorder_quick_marks(db, payload.ids)
    return [QuickMarkResponse.model_validate(mark) for mark in marks]


@router.patch(
    "/{quick_mark_id}",
    response_model=QuickMarkResponse,
    responses={409: {"model": HotkeyTaken}},
)
async def update_quick_mark(
    quick_mark_id: int,
    payload: QuickMarkUpdate,
    db: AsyncSession = Depends(get_db),
) -> QuickMarkResponse:
    """
    Поправить кнопку: только присланные поля.

    Проверяется кнопка целиком, а не присланное: `kind`, `field_id` и `step` —
    одно утверждение, и патч, меняющий только `kind`, способен сделать
    невозможной пару, которую он не трогал.

    - **404** — такой кнопки нет
    - **409** — клавиша уже стоит у другой кнопки; в теле её id и подпись
    - **422** — справочник отверг правку; в `detail` перечислены все причины
    """
    mark = await quick_mark_crud.get_quick_mark(db, quick_mark_id)
    if mark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quick mark with id {quick_mark_id} not found",
        )

    merged = quick_mark_crud.merged_for_validation(mark, payload)
    category = await category_crud.get_category(db, merged.category_id)
    errors = quick_mark_crud.validate_quick_mark(merged, category)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors)
        )

    # Клавиша проверяется до записи, а не по `IntegrityError`: отказ обязан
    # назвать занявшую кнопку, а `IntegrityError` называет имя индекса.
    if merged.hotkey is not None:
        owner = await quick_mark_crud.hotkey_owner(
            db, merged.hotkey, exclude_id=mark.id
        )
        if owner is not None:
            raise _hotkey_conflict(merged.hotkey, owner)

    updated = await quick_mark_crud.update_quick_mark(db, mark, payload)
    return QuickMarkResponse.model_validate(updated)


@router.delete("/{quick_mark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quick_mark(
    quick_mark_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    """
    Удалить кнопку.

    Записанные значения остаются: `entries` и `entry_values` этой ручкой не
    трогаются вовсе. Выпитая вода остаётся выпитой, а удаление кнопки — это про
    экран, а не про прожитый день.

    Выключение (`is_active = false`) — не то же самое: оно убирает кнопку с
    экрана, оставляя её в справочнике вместе с клавишей.
    """
    mark = await quick_mark_crud.get_quick_mark(db, quick_mark_id)
    if mark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quick mark with id {quick_mark_id} not found",
        )
    await quick_mark_crud.delete_quick_mark(db, mark)
