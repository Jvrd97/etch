# [review:need-review] PHASE-03/94
# summary: GET /days?from&to answers a range of days in the shape the old /api/days had, GET /weeks/{iso} answers a week that exists whether or not its retro was written, and PUT /weeks/{iso} replaces the prose and recomputes the counters without touching each other's fields
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import week as week_crud
from app.day.week import BadWeekCode, iso_code, week_bounds
from app.schemas.week import DayListItem, WeekIn, WeekResponse

days_router = APIRouter(prefix="/days", tags=["day"])
weeks_router = APIRouter(prefix="/weeks", tags=["week"])

# The widest range one request may ask for. The timeline draws a year of squares
# at a time and the sidebar the whole history; five years is above both and still
# small enough that a mistyped `from=1970-01-01` costs a 422 rather than a table
# scan of every plan ever written.
MAX_RANGE_DAYS = 366 * 5

# How far back `from` reaches when it is not given: the calendar year around
# today, which is what the timeline opens on.
DEFAULT_RANGE_DAYS = 365


def _checked(iso: str) -> str:
    """
    The week code, or a 404 naming what a week code looks like.

    404 rather than 422: `/weeks/2026-W99` is a URL that names no week, which is
    the same kind of miss as a page that does not exist. A week that exists but
    has no retro is a 200 with empty prose — the two must not answer alike.
    """
    try:
        week_bounds(iso)
    except BadWeekCode as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return iso


@days_router.get("", response_model=list[DayListItem])
async def get_days(
    db: AsyncSession = Depends(get_db),
    from_date: date | None = Query(
        None,
        alias="from",
        description="Первая дата диапазона; без неё — год назад от сегодня",
    ),
    to_date: date | None = Query(
        None, alias="to", description="Последняя дата диапазона; без неё — сегодня"
    ),
) -> list[DayListItem]:
    """
    Дни диапазона: дата, заголовок плана, вердикт и счётчик задач.

    Форма ответа — прежний `/api/days` из `plan_server.py`: `date`, `title`,
    `verdict`, `done`, `total`. Боковая навигация и таймлайн жизни читают её без
    переписывания, а прозу они больше не разбирают регулярками.

    **Вердикт различает три состояния, а не два.** `won`, `lost` и `null` —
    «день не закрыт». `life.py` красил по регулярке из summary и не отличал
    незакрытый день от проигранного; квадрат теперь может быть пустым.

    `done`/`total` — рабочие задачи дня и закрытые из них. Прежний сервер считал
    здесь проставленные отметки любого вида: та же форма, но читаемое число.

    Границы по умолчанию — год назад и сегодня; «сегодня» считает граница суток,
    а не календарь браузера.
    """
    today = today_local()
    end = to_date if to_date is not None else today
    start = (
        from_date if from_date is not None else end - timedelta(days=DEFAULT_RANGE_DAYS)
    )
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Диапазон пуст: from={start.isoformat()} позже to={end.isoformat()}."
            ),
        )
    span = (end - start).days + 1
    if span > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Диапазон в {span} дней шире потолка в {MAX_RANGE_DAYS}. "
                "Запроси его частями."
            ),
        )
    return await week_crud.list_days(db, start, end)


@weeks_router.get("/{iso}", response_model=WeekResponse)
async def get_week(iso: str, db: AsyncSession = Depends(get_db)) -> WeekResponse:
    """
    Неделя `YYYY-Www` — счётчики, стрик на конец и написанное о ней.

    **Неделя без ретро существует и открывается.** Строки может не быть в базе
    вовсе; ручка заводит её и считает по дням, а `retro_md: ""` говорит, что
    разбор не написан. 404 остаётся за кодом, который не называет неделю
    (`2026-W99`), — это опечатка, а не пустая неделя.

    Счётчики пересчитываются на каждом чтении, и `computed_at` показывает,
    когда это было. Текст ретро пересчёт не трогает никогда.
    """
    week = await week_crud.recompute_week(db, _checked(iso))
    return week_crud.to_response(week, await week_crud.week_debt(db, week))


@weeks_router.put("/{iso}", response_model=WeekResponse)
async def put_week(
    iso: str, body: WeekIn, db: AsyncSession = Depends(get_db)
) -> WeekResponse:
    """
    Записать ретро недели: прозу и чеклист «На разбор в воскресенье».

    Счётчики не принимаются — их считает сервер по `day_summary`. Клиент,
    умеющий прислать `won_days`, был бы вторым мнением о том, сколько дней
    недели выиграно, и разошёлся бы с днями при первом же переоткрытии.
    """
    week = await week_crud.replace_week_text(db, _checked(iso), body)
    return week_crud.to_response(week, await week_crud.week_debt(db, week))


@weeks_router.get("", response_model=WeekResponse)
async def get_current_week(db: AsyncSession = Depends(get_db)) -> WeekResponse:
    """
    Текущая неделя.

    «Текущая» считается от `local_date()`, а не от календаря браузера: день идёт
    с 04:00, и в ночь с воскресенья на понедельник это ещё прошлая неделя.
    """
    week = await week_crud.recompute_week(db, iso_code(today_local()))
    return week_crud.to_response(week, await week_crud.week_debt(db, week))
