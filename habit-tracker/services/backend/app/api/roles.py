# [review:need-review] PHASE-03/134, PHASE-03/135, PHASE-03/140
# summary: the roles endpoints — directory and rules CRUD, minutes and acts written/corrected/deleted by hand, and GET /roles/day[/{date}] returning the distribution of the day's minutes together with its acts; a request naming an unknown role or asking for zero minutes comes back 422 (the second because the table refused it, not because a check here did)
"""
HTTP surface of the roles.

Two things about the shape of this module.

**Ручной ввод первичен.** Every write here is reachable with no automation at
all: `POST /role-time-blocks` with a role code, a number of minutes and a note
is «полтора часа на найм» and nothing else has to exist for it to work. The
importers of `#135` and `#136` will call the same two writes with an
`external_ref` attached; that is the only difference between them and a person.

**Ноль минут отвергает база.** There is no `minutes > 0` check in this file or
in the schema. The request goes to the table, the `CHECK` refuses it, and the
`IntegrityError` becomes a 422 — so a row inserted by `psql` or by a future
importer is refused by the same authority as a row inserted by the form.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import activity as activity_crud
from app.crud import plan as plan_crud
from app.crud import role as role_crud
from app.models.role import (
    SOURCE_APP_USAGE,
    SOURCE_MANUAL,
    Role,
    RoleAct,
    RoleRule,
    RoleTimeBlock,
)
from app.roles import classify
from app.schemas.role import (
    RoleActIn,
    RoleActPatch,
    RoleActResponse,
    RoleClassifyDay,
    RoleClassifyIn,
    RoleClassifyResponse,
    RoleCreate,
    RoleDayResponse,
    RoleDaySlice,
    RolePatch,
    RoleResponse,
    RoleRuleCreate,
    RoleRulePatch,
    RoleRuleResponse,
    RoleTimeBlockIn,
    RoleTimeBlockPatch,
    RoleTimeBlockResponse,
)

router = APIRouter(tags=["roles"])

# Percent, as the share of the day is reported.
FULL_SHARE_PCT = 100


async def _role_or_422(db: AsyncSession, code: str) -> Role:
    """
    The role a request names, or a 422 saying which code was not found.

    422 rather than 404: the code came in a body as a value, and the thing that
    is missing is not the resource being addressed.
    """
    role = await role_crud.get_role_by_code(db, code)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown role code: {code}",
        )
    return role


def _rule_dto(rule: RoleRule, codes: dict[int, str]) -> RoleRuleResponse:
    return RoleRuleResponse(
        id=rule.id,
        role_id=rule.role_id,
        role_code=codes[rule.role_id],
        source=rule.source,
        matcher_kind=rule.matcher_kind,
        pattern=rule.pattern,
        priority=rule.priority,
        is_active=rule.is_active,
    )


def _rule_summary(rule: RoleRule | None) -> str | None:
    """
    The rule that produced a row, in one line a person can argue with.

    `bundle_id = com.microsoft.VSCode` rather than `rule 7`: the whole reason
    `#135` stores `rule_id` is that markup nobody can question is markup nobody
    can correct, and an id alone is not a question anybody can ask.
    """
    if rule is None:
        return None
    return f"{rule.matcher_kind} = {rule.pattern}"


def _block_dto(
    block: RoleTimeBlock,
    codes: dict[int, str],
    rules: dict[int, RoleRule] | None = None,
    apps: dict[str, str] | None = None,
) -> RoleTimeBlockResponse:
    rule = (rules or {}).get(block.rule_id) if block.rule_id is not None else None
    return RoleTimeBlockResponse(
        is_automatic=block.source == SOURCE_APP_USAGE,
        rule_summary=_rule_summary(rule),
        app_name=(apps or {}).get(block.external_ref or ""),
        id=block.id,
        work_day=block.work_day,
        role_id=block.role_id,
        role_code=codes[block.role_id],
        source=block.source,
        started_at=block.started_at,
        ended_at=block.ended_at,
        minutes=block.minutes,
        confidence=block.confidence,
        external_ref=block.external_ref,
        rule_id=block.rule_id,
        note=block.note,
        # What the screen marks: a record a person typed, as opposed to one an
        # importer computed. Derived from the source rather than stored twice.
        is_manual=block.source == SOURCE_MANUAL,
    )


def _act_dto(
    act: RoleAct,
    codes: dict[int, str],
    plan_lines: dict[str, PlanLine] | None = None,
) -> RoleActResponse:
    """
    One act on the wire, with the line of the plan it came from when it has one.

    The line is resolved rather than stored beside the act: `external_ref`
    already names it, and a copy of the text would be the copy that goes stale
    the first time the wording of the task is corrected.
    """
    line = (plan_lines or {}).get(act.external_ref or "")
    return RoleActResponse(
        plan_item_id=line.item_id if line else None,
        plan_item_text=line.text if line else None,
        id=act.id,
        work_day=act.work_day,
        role_id=act.role_id,
        role_code=codes[act.role_id],
        act_kind=act.act_kind,
        title=act.title,
        source=act.source,
        external_ref=act.external_ref,
        confidence=act.confidence,
        occurred_at=act.occurred_at,
        note=act.note,
        is_manual=act.source == SOURCE_MANUAL,
    )


async def _measured_apps(db: AsyncSession, work_day: date_type) -> dict[str, str]:
    """
    The application behind each automatic row, by the `external_ref` it carries.

    `#135` writes `external_ref` as `"<interval id>:<work day>"`, so the row is
    traced back to the interval it was measured from and from there to the
    catalogue. Resolved rather than stored beside the block: a display name a
    person renames must not leave two answers behind.
    """
    intervals = await activity_crud.day_intervals(db, work_day)
    names = await activity_crud.app_names(db)
    return {
        f"{interval.id}:{work_day.isoformat()}": names[interval.app_id]
        for interval in intervals
        if interval.app_id is not None and interval.app_id in names
    }


@dataclass(frozen=True)
class PlanLine:
    """One line of the plan an act can be opened up to."""

    item_id: uuid.UUID
    text: str


async def _plan_lines(db: AsyncSession, work_day: date_type) -> dict[str, PlanLine]:
    """
    Every line of the day's plan by the `external_ref` an act would name it with.

    Keyed by the string form because that is what the column holds: an act
    written by `#140` carries `str(plan_item.id)` and nothing else has to be
    parsed to find its line.
    """
    plan = await plan_crud.get_plan(db, work_day)
    if plan is None:
        return {}
    return {
        str(item.id): PlanLine(item_id=item.id, text=item.text_plain)
        for section in plan.sections
        for item in section.items
    }


async def _role_codes(db: AsyncSession) -> dict[int, str]:
    """Role id to code, read once per request instead of per row."""
    return {role.id: role.code for role in await role_crud.list_roles(db)}


@asynccontextmanager
async def _written(db: AsyncSession) -> AsyncIterator[None]:
    """
    Run a write and commit it, turning the table's refusal into a 422.

    Wraps the flush as well as the commit, because that is where the `CHECK` on
    `minutes` actually fires: `write_time_block` flushes to learn the row's id,
    and a zero is refused there rather than at the end of the request. The only
    constraint a request can currently trip is that one, and it is deliberately
    the table's to enforce rather than this module's.

    The answer names the constraint and nothing else. Postgres attaches the
    whole failing row to a violation, and that row carries a person's note —
    «найм», a correspondent, a document name — which has no business travelling
    back out in an error string.
    """
    try:
        yield
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "the record was refused by the database constraint "
                f"{_constraint_name(error)}"
            ),
        ) from error


def _constraint_name(error: IntegrityError) -> str:
    """
    The constraint a violation names, without the row that violated it.

    asyncpg exposes it as an attribute; a driver that does not is answered with
    the class of the error, which is still a diagnosis and still carries no
    values.
    """
    name = getattr(error.orig, "constraint_name", None)
    if isinstance(name, str) and name:
        return name
    return type(error.orig).__name__


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(db: AsyncSession = Depends(get_db)) -> list[RoleResponse]:
    """
    Справочник ролей.

    Целевая доля приезжает как есть и подписывается на экране гипотезой: она
    описывает намерение квартала, а не норму, по которой судится день.
    """
    return [
        RoleResponse.model_validate(role) for role in await role_crud.list_roles(db)
    ]


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate, db: AsyncSession = Depends(get_db)
) -> RoleResponse:
    """Завести роль. Код уникален — им пользуются правила, минуты и акты."""
    if await role_crud.get_role_by_code(db, body.code) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"role code already exists: {body.code}",
        )
    async with _written(db):
        role = await role_crud.create_role(
            db,
            code=body.code,
            title=body.title,
            description=body.description,
            target_share_pct=body.target_share_pct,
            is_work=body.is_work,
            ord=body.ord,
            is_active=body.is_active,
        )
    return RoleResponse.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def patch_role(
    role_id: int, body: RolePatch, db: AsyncSession = Depends(get_db)
) -> RoleResponse:
    """
    Поправить роль: название, описание, целевую долю, порядок, активность.

    Код не меняется: его называют правила, минуты и акты, и переименование
    молча оставило бы их без роли.
    """
    role = await role_crud.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role")
    async with _written(db):
        role_crud.apply_role_patch(role, body.model_dump(exclude_unset=True))
    return RoleResponse.model_validate(role)


@router.get("/role-rules", response_model=list[RoleRuleResponse])
async def list_rules(db: AsyncSession = Depends(get_db)) -> list[RoleRuleResponse]:
    """
    Правила разметки, сильные первыми.

    Порядок тот же, в котором резолвер выбирает победителя: меньший `priority`,
    при равенстве — меньший id.
    """
    codes = await _role_codes(db)
    rules = await role_crud.list_rules(db, active_only=False)
    return [_rule_dto(rule, codes) for rule in rules]


@router.post(
    "/role-rules",
    response_model=RoleRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    body: RoleRuleCreate, db: AsyncSession = Depends(get_db)
) -> RoleRuleResponse:
    """
    Завести правило разметки.

    Экран правки правил — отдельный тикет; здесь правила заводятся запросом, и
    этого достаточно, чтобы конфликт двух правил был проверяем.
    """
    role = await _role_or_422(db, body.role_code)
    async with _written(db):
        rule = await role_crud.create_rule(
            db,
            role_id=role.id,
            source=body.source,
            matcher_kind=body.matcher_kind,
            pattern=body.pattern,
            priority=body.priority,
            is_active=body.is_active,
        )
    return _rule_dto(rule, await _role_codes(db))


@router.patch("/role-rules/{rule_id}", response_model=RoleRuleResponse)
async def patch_rule(
    rule_id: int, body: RoleRulePatch, db: AsyncSession = Depends(get_db)
) -> RoleRuleResponse:
    """Поправить правило: роль, образец, вес или выключить его совсем."""
    rule = await role_crud.get_rule(db, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role rule")
    async with _written(db):
        if body.role_code is not None:
            rule.role_id = (await _role_or_422(db, body.role_code)).id
        if body.pattern is not None:
            rule.pattern = body.pattern
        if body.priority is not None:
            rule.priority = body.priority
        if body.is_active is not None:
            rule.is_active = body.is_active
    return _rule_dto(rule, await _role_codes(db))


@router.post(
    "/role-time-blocks",
    response_model=RoleTimeBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_time_block(
    body: RoleTimeBlockIn, db: AsyncSession = Depends(get_db)
) -> RoleTimeBlockResponse:
    """
    Записать минуты роли.

    День берётся из тела, а если его там нет — считается границей суток
    сервера (`app.core.daytime`), а не календарём браузера.

    Повторная запись с тем же `(source, external_ref)` переписывает ту же
    строку, а не заводит вторую: день от повторного прохода импортёра не
    удваивается. Строку, помеченную человеком как `confirmed`, импортёр не
    трогает вовсе — ответ 200 с сохранённой строкой, а не 201.
    """
    role = await _role_or_422(db, body.role_code)
    async with _written(db):
        outcome = await role_crud.write_time_block(
            db,
            role_crud.TimeBlockDraft(
                work_day=body.work_day or today_local(),
                role_id=role.id,
                minutes=body.minutes,
                source=body.source,
                started_at=body.started_at,
                ended_at=body.ended_at,
                confidence=body.confidence,
                external_ref=body.external_ref,
                rule_id=body.rule_id,
                note=body.note,
            ),
        )
    return _block_dto(outcome.row, await _role_codes(db))


@router.patch("/role-time-blocks/{block_id}", response_model=RoleTimeBlockResponse)
async def patch_time_block(
    block_id: int, body: RoleTimeBlockPatch, db: AsyncSession = Depends(get_db)
) -> RoleTimeBlockResponse:
    """
    Поправить запись минут руками.

    Это вторая половина «ручное поверх автоматики»: что бы ни посчитал
    импортёр, строку можно перевесить на другую роль, переизмерить и пометить
    `confirmed` — после чего импортёр её не тронет.
    """
    block = await role_crud.get_time_block(db, block_id)
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="time block")
    async with _written(db):
        if body.role_code is not None:
            block.role_id = (await _role_or_422(db, body.role_code)).id
        if body.minutes is not None:
            block.minutes = body.minutes
        if body.work_day is not None:
            block.work_day = body.work_day
        if body.confidence is not None:
            block.confidence = body.confidence
        if body.note is not None:
            block.note = body.note
    return _block_dto(block, await _role_codes(db))


@router.delete("/role-time-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_block(
    block_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    """Убрать запись минут: запись, которой не было, — это удаление, не ноль."""
    block = await role_crud.get_time_block(db, block_id)
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="time block")
    async with _written(db):
        await db.delete(block)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/role-acts", response_model=RoleActResponse, status_code=status.HTTP_201_CREATED
)
async def create_act(
    body: RoleActIn, db: AsyncSession = Depends(get_db)
) -> RoleActResponse:
    """
    Записать акт роли: вид, заголовок и день.

    Акт — не производная от минут: решение про бюджет занимает пятнадцать минут
    и разворачивает квартал. Идемпотентность та же, что у минут.
    """
    role = await _role_or_422(db, body.role_code)
    async with _written(db):
        outcome = await role_crud.write_act(
            db,
            role_crud.ActDraft(
                work_day=body.work_day or today_local(),
                role_id=role.id,
                act_kind=body.act_kind,
                title=body.title,
                source=body.source,
                external_ref=body.external_ref,
                confidence=body.confidence,
                occurred_at=body.occurred_at,
                note=body.note,
            ),
        )
    return _act_dto(outcome.row, await _role_codes(db))


@router.patch("/role-acts/{act_id}", response_model=RoleActResponse)
async def patch_act(
    act_id: int, body: RoleActPatch, db: AsyncSession = Depends(get_db)
) -> RoleActResponse:
    """Поправить акт руками — роль, вид, заголовок, день или уверенность."""
    act = await role_crud.get_act(db, act_id)
    if act is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role act")
    async with _written(db):
        if body.role_code is not None:
            act.role_id = (await _role_or_422(db, body.role_code)).id
        if body.act_kind is not None:
            act.act_kind = body.act_kind
        if body.title is not None:
            act.title = body.title
        if body.work_day is not None:
            act.work_day = body.work_day
        if body.confidence is not None:
            act.confidence = body.confidence
        if body.note is not None:
            act.note = body.note
    return _act_dto(act, await _role_codes(db))


@router.delete("/role-acts/{act_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_act(act_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """Убрать акт."""
    act = await role_crud.get_act(db, act_id)
    if act is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role act")
    async with _written(db):
        await db.delete(act)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _day(db: AsyncSession, work_day: date_type) -> RoleDayResponse:
    """
    Where one day went and which roles happened on it, in one answer.

    The share is integer percent of the day's total minutes, and it is computed
    here rather than stored: it is a ratio of two numbers that both change on
    every write, and a stored share is a share that is wrong by the next one.
    """
    roles = await role_crud.list_roles(db)
    codes = {role.id: role.code for role in roles}
    blocks = await role_crud.day_time_blocks(db, work_day)
    acts = await role_crud.day_acts(db, work_day)
    plan_lines = await _plan_lines(db, work_day)
    rules = {
        rule.id: rule for rule in await role_crud.list_rules(db, active_only=False)
    }
    apps = await _measured_apps(db, work_day)

    minutes: dict[int, int] = {role.id: 0 for role in roles}
    for block in blocks:
        minutes[block.role_id] = minutes.get(block.role_id, 0) + block.minutes
    act_counts: dict[int, int] = {role.id: 0 for role in roles}
    for act in acts:
        act_counts[act.role_id] = act_counts.get(act.role_id, 0) + 1

    total = sum(minutes.values())
    return RoleDayResponse(
        work_day=work_day,
        total_minutes=total,
        roles=[
            RoleDaySlice(
                role_id=role.id,
                role_code=role.code,
                title=role.title,
                minutes=minutes[role.id],
                share_pct=(
                    round(minutes[role.id] * FULL_SHARE_PCT / total) if total else 0
                ),
                target_share_pct=role.target_share_pct,
                act_count=act_counts[role.id],
            )
            for role in roles
        ],
        blocks=[_block_dto(block, codes, rules, apps) for block in blocks],
        acts=[_act_dto(act, codes, plan_lines) for act in acts],
    )


@router.get("/roles/day", response_model=RoleDayResponse)
async def get_today(db: AsyncSession = Depends(get_db)) -> RoleDayResponse:
    """
    Сегодняшний день ролей.

    Дату считает сервер по границе суток — экран не знает, какое сегодня
    число, и не должен знать: единственный ответ на этот вопрос живёт в
    `app.core.daytime`.
    """
    return await _day(db, today_local())


@router.get("/roles/day/{work_day}", response_model=RoleDayResponse)
async def get_day(
    work_day: date_type, db: AsyncSession = Depends(get_db)
) -> RoleDayResponse:
    """Распределение минут и акты конкретного дня."""
    return await _day(db, work_day)


@router.post("/roles/classify", response_model=RoleClassifyResponse)
async def post_classify(
    body: RoleClassifyIn, db: AsyncSession = Depends(get_db)
) -> RoleClassifyResponse:
    """
    Разметить активность за диапазон дат заново.

    Ручной прогон нужен ровно для одного случая — правило поправили, и неделю
    надо пересчитать. Обычный путь другой: разметка идёт сама на приёме пачки
    интервалов (`POST /agent/activity`), чтобы экран ролей не ждал кнопки.

    Прогон **переписывает** день, а не дополняет его: строки идемпотентны по
    `(source, external_ref)`, а то, что человек подтвердил, разметка не трогает
    вовсе — и это видно числом `kept_confirmed` в ответе.
    """
    if body.date_to < body.date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_to раньше date_from",
        )
    results = await classify.classify_range(db, body.date_from, body.date_to)
    await db.commit()
    return RoleClassifyResponse(
        days=[
            RoleClassifyDay(
                work_day=result.work_day,
                mode=result.mode,
                intervals=result.intervals,
                blocks_written=result.blocks_written,
                kept_confirmed=result.kept_confirmed,
                minutes=result.minutes,
                unassigned_minutes=result.unassigned_minutes,
                skipped_off_mode=result.skipped_off_mode,
                skipped_short=result.skipped_short,
            )
            for result in results
        ]
    )
