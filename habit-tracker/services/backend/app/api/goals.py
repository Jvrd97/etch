# [review:need-review] PHASE-03/93
# summary: GET /goals answers the whole board (levels, milestones with their dependency codes, the goals of the current quarter), PATCH /goals/milestones/{code} moves one milestone and dates it when it is closed, PUT /goals/quarter/{quarter} replaces the five goals of a quarter and turns the database's refusal of a sixth into a 422
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import goal as goal_crud
from app.models.goal import MILESTONE_STATUSES, Milestone, QuarterGoal
from app.schemas.goal import (
    GoalLevelResponse,
    GoalsResponse,
    MilestonePatch,
    MilestoneResponse,
    QuarterGoalResponse,
    QuarterGoalsIn,
)

router = APIRouter(prefix="/goals", tags=["goals"])


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


@router.put("/quarter/{quarter}", response_model=GoalsResponse)
async def put_quarter_goals(
    quarter: str, body: QuarterGoalsIn, db: AsyncSession = Depends(get_db)
) -> GoalsResponse:
    """
    Заменить цели квартала целиком.

    Набором, а не по одной: «больше пяти — цель размазана» — свойство набора, и
    отвергает шестую цель база (`ck_quarter_goal_ord`, `uq_quarter_goal_quarter_ord`),
    а не сервис. Ручка только называет отказ: 422 вместо 500 с именем ограничения.
    """
    try:
        await goal_crud.replace_quarter_goals(
            db,
            quarter,
            [
                QuarterGoal(
                    quarter=quarter,
                    ord=one.ord,
                    text_md=one.text_md,
                    milestone_code=one.milestone_code,
                    status=one.status,
                )
                for one in body.goals
            ],
        )
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Квартал {quarter} не записан: цели квартала — ровно пять "
                "пунктов с местами 1..5, и место занимается один раз. "
                f"База отказала: {error.orig}"
            ),
        ) from error
    return await _board(db, quarter)
