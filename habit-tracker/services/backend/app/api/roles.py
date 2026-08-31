# [review:need-review] PHASE-03/134, PHASE-03/138, PHASE-03/139
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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import role as role_crud
from app.roles import classify
from app.roles.report import render_summary_md
from app.models.role import (
    SOURCE_MANUAL,
    Role,
    RoleAct,
    RoleRule,
    RoleTimeBlock,
)
from app.schemas.role import (
    RoleActIn,
    RoleActPatch,
    RoleActResponse,
    RoleCreate,
    RoleDayResponse,
    RoleDaySlice,
    RolePatch,
    RoleResponse,
    RoleRuleCreate,
    RoleRulePatch,
    RoleReclassifyIn,
    RoleReclassifyResponse,
    RoleRuleDryRun,
    RoleRuleDryRunExample,
    RoleRuleDryRunResponse,
    RoleRuleResponse,
    RoleShareResponse,
    RoleSummaryResponse,
    RoleSummarySlice,
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


def _block_dto(block: RoleTimeBlock, codes: dict[int, str]) -> RoleTimeBlockResponse:
    return RoleTimeBlockResponse(
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


def _act_dto(act: RoleAct, codes: dict[int, str]) -> RoleActResponse:
    return RoleActResponse(
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


@router.post("/role-rules/dry-run", response_model=RoleRuleDryRunResponse)
async def dry_run_rule(
    body: RoleRuleDryRun, db: AsyncSession = Depends(get_db)
) -> RoleRuleDryRunResponse:
    """
    Прогнать правило по истории, ничего не записав.

    Обязательная половина экрана правил, а не удобство: правило
    `window_title_regex` без проверки на реальных данных ловит либо ничего, либо
    всё, а на приёме «сначала сохрани, потом посмотри» человек молча перестаёт
    трогать правила.

    В ответе — сколько интервалов и актов зацепило бы правило и у какого
    существующего правила оно отбирает совпадения: правило, ловящее сто строк,
    из которых девяносто уже размечены верно, не улучшает разметку.
    """
    role = await _role_or_422(db, body.role_code)
    date_to = today_local()
    date_from = date_to - timedelta(days=body.days_back - 1)
    outcome = await classify.dry_run(
        db,
        role_id=role.id,
        source=body.source,
        matcher_kind=body.matcher_kind,
        pattern=body.pattern,
        priority=body.priority,
        date_from=date_from,
        date_to=date_to,
    )
    return RoleRuleDryRunResponse(
        date_from=outcome.date_from,
        date_to=outcome.date_to,
        scanned_rows=outcome.scanned_rows,
        matched_time_blocks=outcome.matched_time_blocks,
        matched_acts=outcome.matched_acts,
        taken_from=dict(outcome.taken_from),
        taken_from_nobody=outcome.taken_from_nobody,
        examples=[
            RoleRuleDryRunExample(
                kind=one.kind,
                work_day=one.work_day,
                label=one.label,
                current_role_id=one.current_role_id,
                taken_from_rule_id=one.taken_from_rule_id,
            )
            for one in outcome.examples
        ],
    )


@router.post("/roles/reclassify", response_model=RoleReclassifyResponse)
async def reclassify_period(
    body: RoleReclassifyIn, db: AsyncSession = Depends(get_db)
) -> RoleReclassifyResponse:
    """
    Разметить период заново по действующим правилам.

    Правило, добавленное сегодня, иначе размечает только завтрашние строки, и
    месяц, разложенный неверно, так неверным и остаётся — то есть срабатывает
    названный в ADR сигнал «автоматика не работает», хотя не работает не
    автоматика, а невозможность её починить задним числом.

    Записи, подтверждённые человеком, не трогаются, и их число названо в ответе.
    """
    if body.date_to < body.date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_to is earlier than date_from",
        )
    async with _written(db):
        outcome = await classify.reclassify(
            db, date_from=body.date_from, date_to=body.date_to
        )
    return RoleReclassifyResponse(
        date_from=outcome.date_from,
        date_to=outcome.date_to,
        scanned_rows=outcome.scanned_rows,
        changed_time_blocks=outcome.changed_time_blocks,
        changed_acts=outcome.changed_acts,
        protected=outcome.protected,
        before=[
            RoleShareResponse(
                role_id=one.role_id, minutes=one.minutes, share_pct=one.share_pct
            )
            for one in outcome.before
        ],
        after=[
            RoleShareResponse(
                role_id=one.role_id, minutes=one.minutes, share_pct=one.share_pct
            )
            for one in outcome.after
        ],
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """
    Убрать роль из справочника.

    Роль, на которую ссылается правило разметки, минута или акт, база удалить не
    даёт (`ON DELETE RESTRICT`), и отказ приезжает сюда `IntegrityError`.
    Отказывает именно база, а не проверка здесь: сервисную проверку обходят
    импорт, миграция и сессия `psql`, а молча осиротевшая разметка — это
    `unassigned`, появившийся из ниоткуда.
    """
    role = await role_crud.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role")
    async with _written(db):
        await db.delete(role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        blocks=[_block_dto(block, codes) for block in blocks],
        acts=[_act_dto(act, codes) for act in acts],
    )


# Как отдать свёртку. `json` — объект, `md` — тот же объект, отрендеренный в
# готовый блок отчёта. Два имени, и третьего не будет: формат — это проекция
# одного расчёта, а не второй расчёт.
FORMAT_JSON = "json"
FORMAT_MD = "md"
SUMMARY_FORMATS: tuple[str, ...] = (FORMAT_JSON, FORMAT_MD)

MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"


def _summary_dto(summary: role_crud.RoleSummary) -> RoleSummaryResponse:
    """Свёртка как её несёт провод, вместе с готовым текстом отчёта."""
    return RoleSummaryResponse(
        date_from=summary.date_from,
        date_to=summary.date_to,
        total_minutes=summary.total_minutes,
        roles=[
            RoleSummarySlice(
                role_id=one.role_id,
                role_code=one.role_code,
                title=one.title,
                minutes=one.minutes,
                share_pct=one.share_pct,
                target_share_pct=one.target_share_pct,
                delta_pct=one.delta_pct,
                act_counts=dict(one.act_counts),
                act_total=one.act_total,
            )
            for one in summary.roles
        ],
        unassigned_minutes=summary.unassigned_minutes,
        unassigned_share_pct=summary.unassigned_share_pct,
        window_from=summary.window_from,
        window_minutes=summary.window_minutes,
        window_unassigned_share_pct=summary.window_unassigned_share_pct,
        lag_threshold_pct=role_crud.UNASSIGNED_LAG_PCT,
        rules_lag=summary.rules_lag,
        markdown=render_summary_md(summary),
    )


@router.get("/roles/summary", response_model=None)
async def get_summary(
    date_from: date_type,
    date_to: date_type,
    response_format: str = Query(default=FORMAT_JSON, alias="format"),
    db: AsyncSession = Depends(get_db),
) -> RoleSummaryResponse | PlainTextResponse:
    """
    Свёртка ролей за произвольный период: доли, отклонения, акты, `unassigned`.

    - **date_from**, **date_to**: обе границы включительно
    - **format**: `json` — объект, `md` — готовый блок пятничного отчёта текстом

    Один эндпоинт на неделю и на месяц: второй расчёт под месяц разошёлся бы с
    первым молча, а сверять сводку недели со сводкой месяца никто не станет.

    Текст `md` и поле `markdown` объекта — один и тот же рендер: `format` это
    проекция одного расчёта, а не второй расчёт, поэтому числа в тексте
    совпадают с числами в JSON по построению, а не по договорённости.
    """
    if response_format not in SUMMARY_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"format must be one of: {', '.join(SUMMARY_FORMATS)}",
        )
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_to is earlier than date_from",
        )
    dto = _summary_dto(await role_crud.role_summary(db, date_from, date_to))
    if response_format == FORMAT_MD:
        return PlainTextResponse(dto.markdown, media_type=MARKDOWN_MEDIA_TYPE)
    return dto


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
