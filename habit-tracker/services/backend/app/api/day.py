# [review:need-review] PHASE-03/86
# summary: GET /day (today by the day boundary) and GET /day/{date} — the day, the rule in force on it, and an explicit "no plan" instead of a 404
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.day.rules import NoRuleForDate
from app.models.day import Day, DayRuleSet
from app.schemas.day import DayDetailResponse, DayResponse, DayRuleSetResponse

router = APIRouter(prefix="/day", tags=["day"])


def _detail(day: Day, rule: DayRuleSet) -> DayDetailResponse:
    """Assemble the response; the plan half stays empty until #87 fills it."""
    return DayDetailResponse(
        day=DayResponse(
            date=day.day_date,
            kind=day.kind,
            is_nocode=day.is_nocode,
            opened_at=day.opened_at,
            last_touched_at=day.last_touched_at,
        ),
        rule=DayRuleSetResponse.model_validate(rule),
    )


async def _day_detail(db: AsyncSession, on: date) -> DayDetailResponse:
    """
    The day for `on`, creating it lazily if this is the first time it is asked for.

    Creation on a read is deliberate: a day exists because the date arrived, not
    because somebody pressed something, and materialising `kind`/`is_nocode` at
    that moment is what freezes them against a later edit of the week schedule.
    """
    try:
        day = await day_crud.ensure_day(db, on)
        rule = await day_crud.rule_for_date(db, on)
    except NoRuleForDate as error:
        # A date outside every recorded interval of the canon. Not a missing
        # day — a day nothing describes, and inventing a rule for it would
        # produce a verdict nobody ever lived under.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return _detail(day, rule)


@router.get("", response_model=DayDetailResponse)
async def get_today(db: AsyncSession = Depends(get_db)) -> DayDetailResponse:
    """
    Сегодняшний день.

    «Сегодня» считает `local_date()` по границе суток из действующего правила,
    а не календарь браузера: в 00:30 это ещё вчерашний день, и страница обязана
    открыть тот же день, что и все остальные потребители.
    """
    return await _day_detail(db, today_local())


@router.get("/{on}", response_model=DayDetailResponse)
async def get_day(on: date, db: AsyncSession = Depends(get_db)) -> DayDetailResponse:
    """
    День по дате `YYYY-MM-DD`.

    Отдаёт сам день, правило, по которому он считается, и явное «плана нет»
    вместо 404: пустой день — это ответ, а не ошибка.

    404 остаётся за датой, которую не покрывает ни одно записанное правило.
    """
    return await _day_detail(db, on)
