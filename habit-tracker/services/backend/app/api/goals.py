# [review:need-review] PHASE-03/93
# summary: GET /goals answers the whole board (levels, milestones with their dependency codes, the goals of the current quarter), PATCH /goals/milestones/{code} moves one milestone and dates it when it is closed, PUT /goals/quarter/{quarter} writes the five goals of a quarter in place and names each refusal by the constraint that produced it
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import goal as goal_crud
from app.models.goal import MILESTONE_STATUSES, Milestone
from app.schemas.goal import (
    GoalLevelResponse,
    GoalsResponse,
    MilestonePatch,
    MilestoneResponse,
    QuarterGoalResponse,
    QuarterGoalsIn,
)

router = APIRouter(prefix="/goals", tags=["goals"])

# The refusals of the goal tables a person can actually cause, by the name the
# database gives them. Anything not listed here is a defect rather than a rule
# and is left to become a 500: answering «цели квартала — ровно пять пунктов» to
# an unidentified constraint is how a broken write gets reported as an ordinary
# bar being hit, and the reader goes looking for a sixth goal that is not there.
CONSTRAINT_MESSAGES: dict[str, str] = {
    "ck_quarter_goal_ord": "место цели — число от 1 до 5.",
    "uq_quarter_goal_quarter_ord": "место в списке занимается один раз.",
    "ck_quarter_goal_status": "статус цели квартала не из словаря.",
    "quarter_goal_milestone_code_fkey": "цель называет милстон, которого нет.",
}


def _constraint_name(error: IntegrityError) -> str | None:
    """
    The name postgres gave the rule that refused the write.

    asyncpg hangs it on the cause of the exception SQLAlchemy wraps. Read
    through `getattr` because the driver is not part of the type of
    `IntegrityError`, and checked for being a string so that a driver which
    reports no name leaves the answer unknown instead of stringified.
    """
    name = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    return name if isinstance(name, str) else None


def _milestone(one: Milestone, edges: dict[str, list[str]]) -> MilestoneResponse:
    """One milestone as its DTO, with «Открывается чем» already resolved."""
    return MilestoneResponse(
        code=one.code,
        title=one.title,
        done_criterion=one.done_criterion,
        when_text=one.when_text,
        ord=one.ord,
        status=one.status,
        done_on=one.done_on,
        depends_on=edges.get(one.code, []),
    )


async def _board(db: AsyncSession, quarter: str) -> GoalsResponse:
    """
    The levels, the milestones and one quarter, read together.

    One request rather than three: the screen is unreadable in pieces — a
    milestone without its dependencies is a line whose position in the order is
    invisible — and three round trips would render the board three times.
    """
    edges = await goal_crud.dependencies(db)
    return GoalsResponse(
        levels=[
            GoalLevelResponse.model_validate(level)
            for level in await goal_crud.list_levels(db)
        ],
        milestones=[
            _milestone(one, edges) for one in await goal_crud.list_milestones(db)
        ],
        quarter=quarter,
        goals=[
            QuarterGoalResponse.model_validate(one)
            for one in await goal_crud.list_quarter_goals(db, quarter)
        ],
    )


@router.get("", response_model=GoalsResponse)
async def get_goals(db: AsyncSession = Depends(get_db)) -> GoalsResponse:
    """
    Уровни 0-5, милстоны с графом зависимостей и цели текущего квартала.

    Квартал считается по границе суток, а не по календарю браузера: день идёт
    с 04:00, и первого числа в полночь текущим кварталом остаётся прошлый.
    """
    return await _board(db, goal_crud.quarter_code(today_local()))


@router.patch("/milestones/{code}", response_model=MilestoneResponse)
async def patch_milestone(
    code: str, body: MilestonePatch, db: AsyncSession = Depends(get_db)
) -> MilestoneResponse:
    """
    Перевести милстон в другой статус.

    `done` проставляет дату закрытия сегодняшним днём; любой другой статус её
    снимает — милстон, который не закрыт, не имеет даты закрытия.
    """
    if body.status not in MILESTONE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Статус «{body.status}» не из словаря милстонов: "
                f"{', '.join(MILESTONE_STATUSES)}."
            ),
        )
    milestone = await goal_crud.get_milestone(db, code)
    if milestone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Милстона {code} нет."
        )
    await goal_crud.set_milestone_status(db, milestone, body.status, today_local())
    return _milestone(milestone, await goal_crud.dependencies(db))


@router.put(
    "/quarter/{quarter}",
    response_model=GoalsResponse,
    responses={409: {"description": "Убираемую цель называет план прожитого дня"}},
)
async def put_quarter_goals(
    quarter: str, body: QuarterGoalsIn, db: AsyncSession = Depends(get_db)
) -> GoalsResponse:
    """
    Записать цели квартала — набором, поверх тех же строк.

    Набором, а не по одной: «больше пяти — цель размазана» — свойство набора, а
    не строки, которую пишут. Но **не пересозданием**: `quarter_goal.id` — это
    то, чем прожитый день назвал, ради чего он был прожит, и удаление с новой
    вставкой либо оборвало бы эту связь, либо просто упало бы на `RESTRICT`.
    Поэтому цели обновляются на месте по паре `(quarter, ord)`, а позиция,
    которой в новом наборе нет, снимается — и не снимается, если на неё
    ссылается план.

    422 — набор, из которого квартал не собрать (место занято дважды, статус не
    из словаря) или отказ базы, который ручка узнала по имени ограничения.
    409 — цель убирают из набора, а на неё ссылается план прожитого дня; ответ
    называет дни. Неопознанный отказ базы наверх идёт как есть: 500 честнее, чем
    422 про планку, которой никто не касался.
    """
    try:
        await goal_crud.replace_quarter_goals(db, quarter, body.goals)
    except goal_crud.QuarterGoalsRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Квартал {quarter} не записан: {rejected}",
        ) from rejected
    except goal_crud.QuarterGoalInUse as in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Квартал {quarter} не записан: {in_use}",
        ) from in_use
    except IntegrityError as error:
        message = CONSTRAINT_MESSAGES.get(_constraint_name(error) or "")
        if message is None:
            raise
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Квартал {quarter} не записан: {message}",
        ) from error
    return await _board(db, quarter)
