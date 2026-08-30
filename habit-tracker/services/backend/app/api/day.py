# [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/142
# summary: GET /day (today by the day boundary) and GET /day/{date} — the day, the rule in force on it, the map of the day that rule draws (edges, free evening, ceilings, anchors), its plan with schedule and overlaps, its marks, its notebook and the итог with the verdict; POST /day/{date}/plan takes the whole plan as one document, POST /day/{date}/close writes the verdict, PUT .../marks/{item_id} takes one mark and PUT .../notebook the day's text; all three writes claim `opened_at` only inside the open window
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import summary as summary_crud
from app.day.plan_validate import PlanRejected
from app.day.rules import DayMap, NoRuleForDate, day_map, is_openable
from app.models.day import Day, DayRuleSet
from app.models.mark import SOURCE_WEB
from app.schemas.day import (
    DayDetailResponse,
    DayEdgeResponse,
    DayMapResponse,
    DayResponse,
    DayRuleSetResponse,
    IntervalResponse,
)
from app.schemas.mark import (
    MarkIn,
    MarkResponse,
    NotebookIn,
    NotebookResponse,
)
from app.schemas.plan import PlanDocument, PlanRejection, PlanResponse
from app.schemas.summary import DayCloseIn, DaySummaryResponse

router = APIRouter(prefix="/day", tags=["day"])

# `GET` with this set is the browser saying "a person is looking at this day".
# Off by default: an agent, an import and a cron job all read days, and if
# reading counted as opening then `opened_at IS NULL` — the difference between
# "не открывал" and "открыл и ничего не сделал" — would stop meaning anything.
OPENED_DESCRIPTION = (
    "Проставить `opened_at`, если он ещё пуст: страницу дня открыл человек. "
    "Агент, импорт и cron читают день без этого флага. Работает только на "
    "сегодня и вчера — пролистанный август остаётся «не открывали»"
)


def _person_is_here(on: date) -> bool:
    """
    Whether a write on `on` may claim that a person opened the day.

    One predicate for all three writers — `?opened=`, `PUT .../marks` and
    `PUT .../notebook` — and it lives on the server rather than in the browser:
    a page has its own midnight and does not know the boundary hour of 04:00.
    Wave A set `opened_at` on any date a browser rendered, so пролистать август
    из любопытства was enough to erase the difference `verdict = null` stands on.
    """
    return is_openable(on, today_local())


def _map(canon: DayMap) -> DayMapResponse:
    """
    The map of the day as the wire carries it.

    Built from `app.day.rules.day_map` rather than from the row field by field:
    the map is one answer, and a DTO assembled here out of fifteen reads would
    be the second place «где стоят края дня» could be got wrong.
    """
    return DayMapResponse(
        rule_set_id=canon.rule_set_id,
        edges=[
            DayEdgeResponse(kind=edge.kind, label=edge.label, at=edge.at)
            for edge in canon.edges
        ],
        free_evening=IntervalResponse(
            start=canon.free_evening.start, end=canon.free_evening.end
        ),
        relationship_evening=IntervalResponse(
            start=canon.relationship_evening.start,
            end=canon.relationship_evening.end,
        ),
        relationship_anchor_required=canon.relationship_anchor_required,
        work_cap_min=canon.work_cap_min,
        work_hard_cap_min=canon.work_hard_cap_min,
        overtime_lost_min=canon.overtime_lost_min,
        work_stop_at=canon.work_stop_at,
        max_work_tasks=canon.max_work_tasks,
        max_study_items=canon.max_study_items,
        anchors=list(canon.anchors),
        hard_edge_kinds=list(canon.hard_edge_kinds),
        workdays=list(canon.workdays),
        days_off=list(canon.days_off),
        nocode_days=list(canon.nocode_days),
        verdict_reasons=list(canon.verdict_reasons),
    )


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
    """
    The whole answer for one date: the day, the rule, the plan, the marks.

    Marks travel with the plan rather than behind a second request: the screen
    is unreadable without them — a line with no tick is a different thing from a
    line the person never got to — and two requests would render the day once
    without its marks and then again with them.
    """
    stored = await plan_crud.get_plan(db, day.day_date)
    plan = None if stored is None else await plan_crud.to_response(db, stored)
    marks = await mark_crud.list_marks(db, day.day_date)
    counts = mark_crud.task_counts(stored, marks)
    notebook = await day_crud.get_notebook(db, day.day_date)
    return DayDetailResponse(
        day=_day(day),
        rule=DayRuleSetResponse.model_validate(rule),
        day_map=_map(day_map(rule)),
        plan=plan,
        has_plan=plan is not None,
        marks=[mark_crud.to_response(mark.item_id, mark) for mark in marks],
        task_counts=mark_crud.to_counts_response(counts),
        notebook=None if notebook is None else notebook.content,
        summary=await summary_crud.summary_for(db, day.day_date, rule, stored, marks),
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
async def get_today(
    db: AsyncSession = Depends(get_db),
    opened: bool = Query(False, description=OPENED_DESCRIPTION),
) -> DayDetailResponse:
    """
    Сегодняшний день.

    «Сегодня» считает `local_date()` по границе суток из действующего правила,
    а не календарь браузера: в 00:30 это ещё вчерашний день, и страница обязана
    открыть тот же день, что и все остальные потребители.
    """
    day, rule = await _resolve(db, today_local())
    if opened:
        await day_crud.touch_day(db, day, opened=True)
    return await _detail(db, day, rule)


@router.get("/{on}", response_model=DayDetailResponse)
async def get_day(
    on: date,
    db: AsyncSession = Depends(get_db),
    opened: bool = Query(False, description=OPENED_DESCRIPTION),
) -> DayDetailResponse:
    """
    День по дате `YYYY-MM-DD`.

    Отдаёт сам день, правило, по которому он считается, карту дня из той же
    строки правила — жёсткие точки, свободный вечер, потолки, состав якорей, —
    план — секциями,
    пунктами, расписанием и наложениями, — отметки пунктов, счётчик задач и
    блокнот. Плана нет — `plan: null` и `has_plan: false`, а не 404: пустой день
    это ответ, а не ошибка.

    `?opened=true` проставляет `opened_at`, если тот ещё пуст, — и только на
    сегодня и вчера. Флаг ставит страница дня; чтение днём агентом, импортом или
    cron его не ставит, иначе «не открывал» перестало бы быть отличимым от
    «открыл и ничего не отметил». Пролистанный из любопытства август остаётся
    неоткрытым, потому что на этом различии стоит `verdict = null`.

    404 остаётся за датой, которую не покрывает ни одно записанное правило.
    """
    day, rule = await _resolve(db, on)
    if opened and _person_is_here(day.day_date):
        await day_crud.touch_day(db, day, opened=True)
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
    await day_crud.touch_day(db, day, opened=False)
    return await plan_crud.to_response(db, stored)


@router.put("/{on}/marks/{item_id}", response_model=MarkResponse)
async def put_mark(
    on: date,
    item_id: UUID,
    body: MarkIn,
    db: AsyncSession = Depends(get_db),
) -> MarkResponse:
    """
    Отметить пункт плана: `done`, `failed`, `skipped` или `null` — снять отметку.

    Запрос называет состояние, а не шаг цикла. Две открытые вкладки тогда не
    воскрешают старое значение: обе пишут то, что видели у себя, побеждает
    последняя, и `updated_at` показывает, какая именно. «Следующее состояние»
    в теле сделало бы результат зависимым от порядка прихода запросов.

    Каждая смена состояния пишет строку в `plan_mark_event` в той же
    транзакции, включая снятие отметки. Правка одной только заметки состояние
    не меняет и события не пишет.

    404 — пункт, которого нет в плане этого дня. Id из другого дня сюда не
    подходит намеренно: отметка адресуется как «эта строка этого дня».
    """
    day, _ = await _resolve(db, on)
    item = await mark_crud.day_item(db, day.day_date, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет пункта {item_id}.",
        )

    mark = await mark_crud.set_mark(
        db,
        day.day_date,
        item_id,
        state=body.state,
        note=body.note,
        source=body.source,
    )
    # A mark written from the browser is a person on the page; one written by
    # the agent or an import is not, and only the first may claim the day was
    # opened — and only while the day is still inside the open window.
    await day_crud.touch_day(
        db, day, opened=body.source == SOURCE_WEB and _person_is_here(day.day_date)
    )
    return mark_crud.to_response(item_id, mark)


@router.put("/{on}/notebook", response_model=NotebookResponse)
async def put_notebook(
    on: date, body: NotebookIn, db: AsyncSession = Depends(get_db)
) -> NotebookResponse:
    """
    Записать блокнот дня — свободный текст рядом с планом.

    Текст едет целиком и заменяет прежний: блокнот правят на месте, и
    дописывание удваивало бы написанное на каждом сохранении. Живёт он в
    `journal_entries` одной записью на дату — у дня уже есть место для прозы,
    и второе означало бы два ответа на вопрос «что я писал 30-го».

    Источник проверяется наравне с отметкой: блокнот пишет и локальный агент,
    и день, в который писал агент, — не день, в который приходил человек.
    """
    day, _ = await _resolve(db, on)
    entry = await day_crud.set_notebook(db, day.day_date, body.content)
    await day_crud.touch_day(
        db, day, opened=body.source == SOURCE_WEB and _person_is_here(day.day_date)
    )
    return NotebookResponse(
        day_date=day.day_date,
        content=entry.content,
        updated_at=entry.updated_at,
    )


@router.post("/{on}/close", response_model=DaySummaryResponse)
async def post_close(
    on: date, body: DayCloseIn, db: AsyncSession = Depends(get_db)
) -> DaySummaryResponse:
    """
    Закрыть день: посчитать вердикт, записать итог, пересчитать стрик.

    Вердикт считается по правилу, под которым день прожит, а не по нынешнему:
    канон менялся 2026-08-17, и день до этой даты обязан получить тот же ответ,
    который получил бы тогда. Причина названа машинным кодом — `tasks`,
    `anchors`, `overtime`, — а не «день не выигран»: читателю нужно знать,
    что именно чинить.

    `work_minutes` допускает `null` — «не измерено», а не ноль: интервалы работы
    приезжают с `#91`, и до тех пор проверка переработки пропускается, а факт
    уходит в `missing_data`.

    Переопределение вердикта требует записки. 422 без неё — от схемы, и то же
    самое отвергает `CHECK` в базе: валидатор это сообщение, а правило — база.

    Повторный вызов заменяет итог, а не добавляет второй: закрытие — состояние
    дня, а не запись в журнале.
    """
    day, _ = await _resolve(db, on)
    return await summary_crud.close_day(db, day.day_date, body)
