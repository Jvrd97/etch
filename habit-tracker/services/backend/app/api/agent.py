# [review:need-review] PHASE-03/135, PHASE-03/158, PHASE-03/160
# summary: the agent's HTTP surface — POST /agent/activity takes a batch of intervals (capped at 500, 422 naming the bundle the catalogue does not carry) and runs the role markup for every day it touched so the roles screen does not wait for a manual run, GET /agent/activity/{date} rolls the day up per application, GET /agent/day-mode/{date} says which kind of day it is and who decided, and (since #158) the title rules are read, written, reordered and counted, the kill switch of window titles is flipped, GET /agent/config hands the whole lot to the agent, and (since #160) one interval is corrected in place, a record is typed by hand under an Idempotency-Key, and the day answers with time per task counted as the union of ranges
"""
HTTP surface of the macOS agent.

Two decisions shape this module.

**Пачка либо принята целиком, либо отвергнута целиком.** An unknown bundle is a
422 that names it, and nothing from that batch is written — the catalogue is also
the list of whose window titles may ever be kept, and letting a data stream widen
it would widen what the system is allowed to remember.

**Разметка идёт сразу за приёмом.** `#135` exists so that `/roles` shows where
the day went with no manual action at all; a markup that had to be triggered by
hand would be a markup nobody triggers. The same run is available on its own as
`POST /roles/classify` for the case «поправил правило — переразметь неделю».

Ни одного заголовка окна в логах этого модуля нет и быть не может: заголовки
проходят через схему и `crud`, а печатается здесь только счётчик.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import now_utc, today_local
from app.crud import activity as activity_crud
from app.models.activity import ACTIVITY_SOURCE_MANUAL, ActivityInterval
from app.roles import classify
from app.schemas.activity import (
    ActivityAppSlice,
    ActivityBatchIn,
    ActivityBatchResponse,
    ActivityDayResponse,
    ActivityIntervalPatch,
    ActivityIntervalResponse,
    ActivityTaskSlice,
    AgentConfigResponse,
    AgentSettingsIn,
    AgentSettingsResponse,
    DayModeResponse,
    ManualIntervalIn,
    TitleRuleIn,
    TitleRuleOrderIn,
    TitleRulePatch,
    TitleRuleResponse,
)

router = APIRouter(prefix="/agent", tags=["agent"])

SECONDS_PER_MINUTE = 60

# What a roll-up calls the time of an interval that names no application: a
# manual record has a note, not a bundle, and «—» on a screen is worse than a word.
MANUAL_APP_NAME = "вручную"

# Окно, за которое считаются срабатывания правила. Неделя, потому что вопрос,
# на который отвечает число, — «это правило вообще работает», а рабочая неделя
# успевает задеть каждое приложение, которым человек пользуется.
HITS_WINDOW_DAYS = 7


def _interval_dto(
    interval: ActivityInterval, bundles: dict[int, str], names: dict[int, str]
) -> ActivityIntervalResponse:
    return ActivityIntervalResponse(
        id=interval.id,
        source=interval.source,
        app_id=interval.app_id,
        bundle_id=bundles.get(interval.app_id) if interval.app_id else None,
        app_name=names.get(interval.app_id) if interval.app_id else None,
        plan_task_id=interval.plan_task_id,
        clickup_task_id=interval.clickup_task_id,
        corrected_at=interval.corrected_at,
        started_at=interval.started_at,
        ended_at=interval.ended_at,
        duration_seconds=interval.duration_seconds,
        local_date=interval.local_date,
        title_source=interval.title_source,
        idle_seconds=interval.idle_seconds,
        switch_count=interval.switch_count,
        is_corrected=interval.is_corrected,
        note=interval.note,
    )


@router.post(
    "/activity",
    response_model=ActivityBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_activity(
    batch: ActivityBatchIn, db: AsyncSession = Depends(get_db)
) -> ActivityBatchResponse:
    """
    Принять пачку интервалов и сразу разметить дни, которых она коснулась.

    Идемпотентность даёт естественный ключ `(source, started_at, app_id)`:
    повторно присланная после обрыва пачка ложится на те же строки и ничего не
    удваивает, поэтому `Idempotency-Key` этому потоку не нужен.

    422 — приложение, которого нет в каталоге `tracked_app`; в теле его
    `bundle_id`. Ни одной строки от такой пачки в базе не остаётся: каталог
    пополняется решением человека, а не потоком данных.
    """
    try:
        written = await activity_crud.upsert_intervals(
            db,
            [
                activity_crud.IntervalDraft(
                    bundle_id=item.bundle_id,
                    started_at=item.started_at,
                    ended_at=item.ended_at,
                    local_date=item.local_date,
                    utc_offset_minutes=item.utc_offset_minutes,
                    title=item.title,
                    title_source=item.title_source,
                    idle_seconds=item.idle_seconds,
                    switch_count=item.switch_count,
                    source=item.source,
                    note=item.note,
                )
                for item in batch.intervals
            ],
        )
    except activity_crud.UnknownApp as unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Приложения {unknown.bundle_id} нет в каталоге tracked_app. "
                "Заведите его — каталог пополняется решением, а не потоком данных."
            ),
        ) from unknown

    # Which days the batch touched is the server's answer, not the client's:
    # `local_date()` is the single reading of «которому дню принадлежит момент»,
    # and an interval that crosses the boundary touches two days, not one.
    days = sorted(
        {day for interval in written for day in classify.touched_days(interval)}
    )
    for day in days:
        await classify.classify_day(db, day)
    await db.commit()
    return ActivityBatchResponse(
        intervals_written=len(written), classified_days=len(days)
    )


@router.get("/activity/{work_day}", response_model=ActivityDayResponse)
async def get_activity(
    work_day: date_type, db: AsyncSession = Depends(get_db)
) -> ActivityDayResponse:
    """
    Где прошёл день: свёртка по приложениям плюс интервалы, из которых она вышла.

    День считается по границе суток сервера, не по колонке `local_date`, которую
    заполнил клиент: единственный ответ на «какое это число» живёт в
    `app.core.daytime`.
    """
    intervals = await activity_crud.day_intervals(db, work_day)
    mode = await activity_crud.day_mode(db, work_day)
    tasks, untasked = await activity_crud.task_time_seconds(db, work_day)
    apps = await activity_crud.list_apps(db)
    bundles = {app.id: app.bundle_id for app in apps}
    names = {app.id: app.display_name for app in apps}

    seconds: dict[int | None, int] = {}
    for interval in intervals:
        seconds[interval.app_id] = (
            seconds.get(interval.app_id, 0) + interval.duration_seconds
        )

    slices = [
        ActivityAppSlice(
            app_id=app_id,
            bundle_id=bundles.get(app_id) if app_id else None,
            app_name=names.get(app_id, MANUAL_APP_NAME) if app_id else MANUAL_APP_NAME,
            minutes=total // SECONDS_PER_MINUTE,
        )
        for app_id, total in seconds.items()
    ]
    slices.sort(key=lambda row: (-row.minutes, row.app_name))

    return ActivityDayResponse(
        work_day=work_day,
        mode=mode.kind,
        total_minutes=sum(row.minutes for row in slices),
        apps=slices,
        tasks=[
            ActivityTaskSlice(
                plan_task_id=task.plan_task_id,
                clickup_task_id=task.clickup_task_id,
                minutes=task.seconds // SECONDS_PER_MINUTE,
            )
            for task in tasks
        ],
        untasked_minutes=untasked // SECONDS_PER_MINUTE,
        intervals=[_interval_dto(row, bundles, names) for row in intervals],
    )


@router.patch("/activity/{interval_id}", response_model=ActivityIntervalResponse)
async def patch_activity(
    interval_id: int,
    body: ActivityIntervalPatch,
    db: AsyncSession = Depends(get_db),
) -> ActivityIntervalResponse:
    """
    Поправить интервал постфактум: границы, задача, заметка.

    `source` остаётся прежним — интервал по-прежнему то, что измерил агент, а
    факт правки записывается отдельно, в `is_corrected` и `corrected_at`.
    Иначе «я поправил» становится неотличимо от «агент так посчитал», и доверия
    к цифре нет ни в одну сторону.

    422 — конец раньше начала. Строка при этом не меняется: проверка стоит до
    записи, а не после неё.
    """
    interval = await activity_crud.get_interval(db, interval_id)
    if interval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="activity interval"
        )
    try:
        stored = await activity_crud.patch_interval(
            db,
            interval,
            activity_crud.IntervalPatch(
                started_at=body.started_at,
                ended_at=body.ended_at,
                plan_task_id=body.plan_task_id,
                clickup_task_id=body.clickup_task_id,
                note=body.note,
                fields=frozenset(body.model_fields_set),
            ),
            now_utc(),
        )
    except activity_crud.BackwardInterval as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error

    # Границы двинулись — минуты ролей за этот день пересчитываются, иначе
    # правка живёт только на экране активности (`#135`).
    for day in classify.touched_days(stored):
        await classify.classify_day(db, day)
    await db.commit()
    apps = await activity_crud.list_apps(db)
    return _interval_dto(
        stored,
        {app.id: app.bundle_id for app in apps},
        {app.id: app.display_name for app in apps},
    )


@router.post(
    "/activity/manual",
    response_model=ActivityIntervalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_manual_activity(
    body: ManualIntervalIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> ActivityIntervalResponse:
    """
    Записать интервал руками. Приложения у такой записи нет и быть не может.

    Идемпотентность даёт заголовок, а не естественный ключ: у ручной записи
    `app_id IS NULL`, NULL в уникальном ключе Postgres различны, и две честные
    записи с одинаковым началом — это две записи, а не дубль. Ключ отличает
    повтор от второй записи.

    409 — тот же ключ с другими границами: это ошибка вызывающего, и молча
    отдать ему чужую строку значило бы потерять его собственную.
    """
    try:
        stored, created = await activity_crud.create_manual_interval(
            db,
            activity_crud.IntervalDraft(
                bundle_id=None,
                started_at=body.started_at,
                ended_at=body.ended_at,
                local_date=body.local_date,
                utc_offset_minutes=body.utc_offset_minutes,
                source=ACTIVITY_SOURCE_MANUAL,
                note=body.note,
            ),
            idempotency_key=idempotency_key,
        )
    except activity_crud.BackwardInterval as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except activity_crud.KeyBelongsToAnotherRecord as clash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Idempotency-Key {clash} уже занят записью с другими границами. "
                "Возьмите новый ключ."
            ),
        ) from clash

    if created:
        if body.plan_task_id is not None or body.clickup_task_id is not None:
            stored.plan_task_id = body.plan_task_id
            stored.clickup_task_id = body.clickup_task_id
            await db.flush()
        for day in classify.touched_days(stored):
            await classify.classify_day(db, day)
    await db.commit()
    apps = await activity_crud.list_apps(db)
    return _interval_dto(
        stored,
        {app.id: app.bundle_id for app in apps},
        {app.id: app.display_name for app in apps},
    )


@router.get("/day-mode/{on}", response_model=DayModeResponse)
async def get_day_mode(
    on: date_type, db: AsyncSession = Depends(get_db)
) -> DayModeResponse:
    """
    Режим дня: решение человека, если оно есть, иначе строка расписания.

    `source` — часть ответа, а не служебное поле: «выходной по расписанию» и
    «выходной, потому что человек так решил» — один и тот же день и два разных
    факта, и разметка минут читает именно `kind`, а показывает экран оба.
    """
    mode = await activity_crud.day_mode(db, on)
    return DayModeResponse(
        date=on, kind=mode.kind, nocode=mode.nocode, source=mode.source
    )


# --- правила заголовков и рубильник (#158) ---------------------------------
#
# Единственная часть темы, которую человек правит регулярно и в спешке: поставил
# приложение, увидел в интервалах лишнее, закрыл. Править это `psql`-ом в час
# ночи — прямой путь к утечке, ради которой всё и городилось.


async def _rules_response(db: AsyncSession) -> list[TitleRuleResponse]:
    """The policy with the number of intervals each line touched in a week."""
    since = today_local() - timedelta(days=HITS_WINDOW_DAYS)
    hits = await activity_crud.rule_hits(db, since)
    return [
        TitleRuleResponse(
            id=rule.id,
            ord=rule.ord,
            match_kind=rule.match_kind,
            pattern=rule.pattern,
            action=rule.action,
            note=rule.note,
            is_active=rule.is_active,
            hits_7d=hits.get(rule.id, 0),
        )
        for rule in await activity_crud.list_title_rules(db)
    ]


def _bad_pattern(error: activity_crud.BadPattern) -> HTTPException:
    """A pattern `re` cannot compile, refused on write with the reason shown."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Выражение {error.pattern!r} не компилируется: {error.reason}. "
            "Правило не сохранено — битый шаблон на маке молча ничего не "
            "матчит и оставляет заголовок правилу ниже."
        ),
    )


@router.get("/title-rules", response_model=list[TitleRuleResponse])
async def get_title_rules(
    db: AsyncSession = Depends(get_db),
) -> list[TitleRuleResponse]:
    """
    Правила приватности заголовков в порядке применения.

    Порядок — семантика, а не оформление: первое совпавшее правило выигрывает,
    и экран показывает их в том же порядке, в каком их применяет мак.

    Рядом с каждым — сколько интервалов за 7 дней оно затрагивает. Без этого
    правило, ни разу не сработавшее из-за опечатки, выглядит ровно как
    работающее.
    """
    return await _rules_response(db)


@router.post(
    "/title-rules",
    response_model=list[TitleRuleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def post_title_rule(
    body: TitleRuleIn, db: AsyncSession = Depends(get_db)
) -> list[TitleRuleResponse]:
    """
    Завести правило. Без `ord` оно встаёт в конец списка — самым слабым.

    В конец, а не в начало: правило, добавленное в спешке, не должно молча
    перебить запрет, который стоял выше. Поднять его — отдельное действие.
    """
    existing = await activity_crud.list_title_rules(db)
    tail = (existing[-1].ord + activity_crud.ORDER_STEP) if existing else 0
    try:
        await activity_crud.create_title_rule(
            db,
            ord=body.ord if body.ord is not None else tail,
            match_kind=body.match_kind,
            pattern=body.pattern,
            action=body.action,
            note=body.note,
            is_active=body.is_active,
        )
    except activity_crud.BadPattern as error:
        raise _bad_pattern(error) from error
    await db.commit()
    return await _rules_response(db)


@router.patch("/title-rules/{rule_id}", response_model=list[TitleRuleResponse])
async def patch_title_rule(
    rule_id: int, body: TitleRulePatch, db: AsyncSession = Depends(get_db)
) -> list[TitleRuleResponse]:
    """
    Поправить правило: шаблон, действие, заметку или его включённость.

    Выключенное правило остаётся строкой, а не удаляется: «это правило я
    когда-то написал и выключил» — факт, который через месяц объясняет, почему
    заголовки этого приложения снова видно.
    """
    rule = await activity_crud.get_title_rule(db, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="title rule")

    match_kind = body.match_kind if body.match_kind is not None else rule.match_kind
    pattern = body.pattern if body.pattern is not None else rule.pattern
    try:
        activity_crud.validate_pattern(match_kind, pattern)
    except activity_crud.BadPattern as error:
        raise _bad_pattern(error) from error

    rule.match_kind = match_kind
    rule.pattern = pattern
    if body.action is not None:
        rule.action = body.action
    if body.note is not None:
        rule.note = body.note
    if body.is_active is not None:
        rule.is_active = body.is_active
    await db.commit()
    return await _rules_response(db)


@router.delete("/title-rules/{rule_id}", response_model=list[TitleRuleResponse])
async def delete_title_rule(
    rule_id: int, db: AsyncSession = Depends(get_db)
) -> list[TitleRuleResponse]:
    """Убрать правило совсем. Порядок остальных не меняется."""
    rule = await activity_crud.get_title_rule(db, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="title rule")
    await db.delete(rule)
    await db.commit()
    return await _rules_response(db)


@router.put("/title-rules/order", response_model=list[TitleRuleResponse])
async def put_title_rule_order(
    body: TitleRuleOrderIn, db: AsyncSession = Depends(get_db)
) -> list[TitleRuleResponse]:
    """
    Переставить правила: весь порядок одним списком id, сильные впереди.

    Целиком, а не «подвинь это вверх»: порядок решает, какое правило выиграет, и
    построчная перестановка оставила бы политику в промежуточном состоянии — с
    `keep` над `drop` — ровно на время второго запроса.
    """
    try:
        await activity_crud.reorder_title_rules(db, body.order)
    except LookupError as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(missing)
        ) from missing
    await db.commit()
    return await _rules_response(db)


@router.get("/settings", response_model=AgentSettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)) -> AgentSettingsResponse:
    """Рубильники агента: собирать ли заголовки и как часто опрашивать фокус."""
    row = await activity_crud.get_settings(db)
    return AgentSettingsResponse(
        titles_enabled=row.titles_enabled, sampling_seconds=row.sampling_seconds
    )


@router.put("/settings", response_model=AgentSettingsResponse)
async def put_settings(
    body: AgentSettingsIn, db: AsyncSession = Depends(get_db)
) -> AgentSettingsResponse:
    """
    Переключить рубильники. `titles_enabled=false` гасит сбор заголовков целиком.

    Гасит именно заголовки: интервалы и строки приложений продолжают приходить,
    потому что «где прошёл день» и «что было в окне» — разные вопросы, и второй
    можно закрыть, не потеряв первый.

    Уже уехавшие заголовки выключение **не удаляет**. Чистка — руками по ADR;
    экран говорит об этом прямо, потому что рубильник, который выглядит как
    «стереть всё», однажды будет нажат вместо чистки.
    """
    row = await activity_crud.get_settings(db)
    if body.titles_enabled is not None:
        row.titles_enabled = body.titles_enabled
    if body.sampling_seconds is not None:
        row.sampling_seconds = body.sampling_seconds
    await db.commit()
    return AgentSettingsResponse(
        titles_enabled=row.titles_enabled, sampling_seconds=row.sampling_seconds
    )


@router.get("/config", response_model=AgentConfigResponse)
async def get_config(db: AsyncSession = Depends(get_db)) -> AgentConfigResponse:
    """
    Всё, что агент спрашивает у сервера перед тем, как что-то собирать.

    Правила приезжают сюда, поэтому правило, сохранённое в вебе, начинает
    действовать на маке со следующего опроса — без пересборки `.app` и без
    перезапуска агента.
    """
    row = await activity_crud.get_settings(db)
    today = today_local()
    mode = await activity_crud.day_mode(db, today)
    return AgentConfigResponse(
        titles_enabled=row.titles_enabled,
        sampling_seconds=row.sampling_seconds,
        day_mode=DayModeResponse(
            date=today, kind=mode.kind, nocode=mode.nocode, source=mode.source
        ),
        title_rules=await _rules_response(db),
    )
