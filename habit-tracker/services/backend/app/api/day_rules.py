# [review:need-review] PHASE-03/152
# summary: GET /day-rule-sets answers the whole history plus the earliest date a new version may start on, GET /day-rule-sets/current the version in force, POST /day-rule-sets publishes a new one — and there is deliberately no PUT, PATCH or DELETE, because a rule that has judged days is never edited
"""
The canon of a day, read and versioned over HTTP instead of in `psql`.

The absence is the contract: this router has no way to change a row that
exists. Publishing a version is the only write, the past keeps the numbers it
was lived under, and the price of changing the canon is one date field instead
of an `UPDATE` typed into a database console at midnight.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import day_rules as rules_crud
from app.day.rules import NoRuleForDate, active_rule
from app.schemas.day import (
    DayRuleSetHistoryResponse,
    DayRuleSetPublish,
    DayRuleSetResponse,
)

router = APIRouter(prefix="/day-rule-sets", tags=["day"])

# What an empty rule table means to a reader: not "нет данных" but "система не
# знает, что такое день". Spelled once, used by both readers.
EMPTY_TABLE_DETAIL = (
    "Правил дня нет ни одного: система не знает, что такое день. Строки "
    "заводит миграция; пустая таблица — это незапущенная миграция, а не "
    "отсутствие настроек."
)


@router.get("", response_model=DayRuleSetHistoryResponse)
async def get_history(
    db: AsyncSession = Depends(get_db),
) -> DayRuleSetHistoryResponse:
    """
    Все версии канона, старая первой, и то, что нужно для публикации следующей.

    Одним ответом, а не тремя: экран правил показывает действующую версию,
    историю и форму «новая версия с даты» на одной странице, и три запроса
    отрисовали бы её трижды.

    `today` и `earliest_valid_from` считает сервер. Календарь браузера здесь
    не годится: сутки поворачиваются в час, записанный в самом правиле, и в
    00:30 браузерное «завтра» — это ещё серверное «сегодня», то есть ровно та
    дата, с которой публиковать нельзя.
    """
    rules = await day_crud.list_rules(db)
    day_crud.publish_boundary(rules)
    today = today_local()
    return DayRuleSetHistoryResponse(
        today=today,
        earliest_valid_from=rules_crud.earliest_valid_from(today),
        current_id=None if not rules else active_rule(rules).id,
        rules=[DayRuleSetResponse.model_validate(rule) for rule in rules],
    )


@router.get("/current", response_model=DayRuleSetResponse)
async def get_current(db: AsyncSession = Depends(get_db)) -> DayRuleSetResponse:
    """
    Действующая версия канона.

    Отдельная ручка ради потребителей, которым история не нужна: скилла дня,
    локального агента, отладки через curl.
    """
    try:
        rule = await rules_crud.current_rule(db)
    except NoRuleForDate as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=EMPTY_TABLE_DETAIL
        ) from error
    return DayRuleSetResponse.model_validate(rule)


@router.post("", response_model=DayRuleSetResponse, status_code=status.HTTP_201_CREATED)
async def post_rule_set(
    draft: DayRuleSetPublish, db: AsyncSession = Depends(get_db)
) -> DayRuleSetResponse:
    """
    Выпустить новую версию канона с даты `valid_from`.

    Действующая версия закрывается этой же датой, новая вставляется — одной
    транзакцией. Дырки между версиями не остаётся: интервал полуоткрытый,
    граничный день принадлежит новой версии, и либо обе записи проходят, либо
    ни одна.

    **Вердикты прошедших дней не пересчитываются.** День судится по правилу,
    которое покрывало его дату, а это правило остаётся тем, чем было: у него
    меняется только конец интервала. Публикация с потолком в семь часов не
    делает вчерашние девять часов проигрышем задним числом.

    Дата начала не позже сегодняшней — 422: по сегодняшнему дню вердикт уже
    считается. Период, перекрывающий записанный, — 409 от базы, переведённое в
    предложение.

    Ручки правки существующей версии здесь нет и не будет: строка, по которой
    уже посчитаны вердикты, неприкосновенна, и единственный путь изменить канон
    — эта ручка.
    """
    try:
        created = await rules_crud.publish_rule_set(db, draft)
    except rules_crud.RuleStartsTooEarly as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except rules_crud.RuleOverlap as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return DayRuleSetResponse.model_validate(created)
