# [review:need-review] PHASE-03/86, PHASE-03/87
# summary: GET /day (today by the day boundary) and GET /day/{date} — the day, the rule in force on it, and its plan with schedule and overlaps; POST /day/{date}/plan takes the whole plan as one document and answers 422 naming the line that broke a rule
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import plan as plan_crud
from app.day.plan_validate import PlanRejected
from app.day.rules import NoRuleForDate
from app.models.day import Day, DayRuleSet
from app.schemas.day import DayDetailResponse, DayResponse, DayRuleSetResponse
from app.schemas.plan import PlanDocument, PlanRejection, PlanResponse

router = APIRouter(prefix="/day", tags=["day"])


def _day(day: Day) -> DayResponse:
    """The day itself, without the rule or the plan hanging off it."""
    return DayResponse(
        date=day.day_date,
        kind=day.kind,
        is_nocode=day.is_nocode,
        opened_at=day.opened_at,
        last_touched_at=day.last_touched_at,
    )


async def _detail(db: AsyncSession, day: Day, rule: DayRuleSet) -> DayDetailResponse:
    """The whole answer for one date: the day, the rule it is judged by, the plan."""
    stored = await plan_crud.get_plan(db, day.day_date)
    plan = None if stored is None else await plan_crud.to_response(db, stored)
    return DayDetailResponse(
        day=_day(day),
        rule=DayRuleSetResponse.model_validate(rule),
        plan=plan,
        has_plan=plan is not None,
    )


async def _resolve(db: AsyncSession, on: date) -> tuple[Day, DayRuleSet]:
    """
    The day for `on` and the rule it is judged by, creating the day if needed.

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
    return day, rule


@router.get("", response_model=DayDetailResponse)
async def get_today(db: AsyncSession = Depends(get_db)) -> DayDetailResponse:
    """
    Сегодняшний день.

    «Сегодня» считает `local_date()` по границе суток из действующего правила,
    а не календарь браузера: в 00:30 это ещё вчерашний день, и страница обязана
    открыть тот же день, что и все остальные потребители.
    """
    day, rule = await _resolve(db, today_local())
    return await _detail(db, day, rule)


@router.get("/{on}", response_model=DayDetailResponse)
async def get_day(on: date, db: AsyncSession = Depends(get_db)) -> DayDetailResponse:
    """
    День по дате `YYYY-MM-DD`.

    Отдаёт сам день, правило, по которому он считается, и план — секциями,
    пунктами, расписанием и списком наложившихся окон. Плана нет — `plan: null`
    и `has_plan: false`, а не 404: пустой день это ответ, а не ошибка.

    404 остаётся за датой, которую не покрывает ни одно записанное правило.
    """
    day, rule = await _resolve(db, on)
    return await _detail(db, day, rule)


@router.post(
    "/{on}/plan",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": PlanRejection}},
)
async def post_plan(
    on: date, document: PlanDocument, db: AsyncSession = Depends(get_db)
) -> PlanResponse:
    """
    Принять план дня целиком и заменить им прежний.

    План приезжает одним документом, а не по пунктам: планка рабочих задач и
    «жёсткими бывают только края дня» — свойства плана, а не строки, и по одной
    строке их не проверить.

    Отказ отвечает 422 и **называет пункт**: код нарушившей задачи в
    `item_code`, формулировку правила в `message`. Отказ ничего не удаляет —
    прежний план дня остаётся на месте.
    """
    day, rule = await _resolve(db, on)
    try:
        stored = await plan_crud.replace_plan(db, day.day_date, rule, document)
    except PlanRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=rejected.as_detail(),
        ) from rejected
    return await plan_crud.to_response(db, stored)
