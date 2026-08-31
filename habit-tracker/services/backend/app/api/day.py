# [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/91, PHASE-03/92, PHASE-03/110, PHASE-03/142, PHASE-03/143, PHASE-03/147
# summary: GET /day (today by the day boundary) and GET /day/{date} — the day, the rule in force on it, the map of the day that rule draws (edges, free evening, ceilings, anchors), its plan with schedule and overlaps, its marks, its notebook and the итог with the verdict; POST /day/{date}/plan takes the whole plan as one document, POST /day/{date}/close writes the verdict, PUT .../marks/{item_id} takes one mark and PUT .../notebook the day's text; GET/PUT /day/{date}/anchors mark the anchors of the day by kind and GET/PUT /day/{date}/training write its training and the minimum's own line (#92); #110 adds the per-item editor — PATCH/POST/DELETE of one line and POST .../move for its place, where a human's edit passes everything the database passes and comes back with the document rules it broke as warnings; all three plan writes claim `opened_at` only inside the open window
# summary: GET /day (today by the day boundary) and GET /day/{date} — the day, the rule in force on it, the map of the day that rule draws (edges, free evening, ceilings, anchors), its plan with schedule and overlaps, its marks, its notebook and the итог with the verdict; POST /day/{date}/plan takes the whole plan as one document, POST /day/{date}/close/review is the 15:40 touch and /close/final the evening one that writes the verdict (the bare /close stays as a synonym of `final`), both idempotent by `Idempotency-Key` and both refusing a day whose итог arrived as prose, PUT .../marks/{item_id} takes one mark and PUT .../notebook the day's text; all three writes claim `opened_at` only inside the open window; .../work-intervals is the CRUD of measured work, which the day answers with as intervals plus a sum and never as a window title
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import anchor as anchor_crud
from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import plan_violation as violation_crud
from app.crud import summary as summary_crud
from app.crud import work_interval as work_crud
from app.crud.summary import KeyBelongsToAnotherDay
from app.crud.work_interval import IntervalNotOnDay
from app.day import constraints, report as report_service, skeleton
from app.crud import training as training_crud
from app.day.plan_validate import PlanRejected
from app.day.rules import DayMap, NoRuleForDate, day_map, is_openable
from app.models.anchor import ANCHOR_STATES, AnchorKind, DayAnchor
from app.models.day import Day, DayRuleSet
from app.models.day_report import REPORT_TRIGGERS, TRIGGER_API, TRIGGER_CLOSE, DayReport
from app.models.mark import SOURCE_WEB
from app.schemas.anchor import (
    DayAnchorResponse,
    DayAnchorsIn,
    DayAnchorsResponse,
)
from app.schemas.day_report import DayReportResponse, DayReportSource
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
from app.schemas.plan import (
    PlanDocument,
    PlanEditResponse,
    PlanItemCreate,
    PlanItemMove,
    PlanItemPatch,
    PlanItemResponse,
    PlanRejection,
    PlanResponse,
)
from app.schemas.plan_violation import PlanViolationResponse, SkeletonRejection
from app.schemas.summary import DayCloseIn, DayReviewIn, DaySummaryResponse
from app.schemas.training import TrainingDayIn, TrainingDayResponse
from app.schemas.work_interval import (
    WorkDayResponse,
    WorkIntervalIn,
    WorkIntervalPatch,
    WorkIntervalResponse,
)

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
    training = await training_crud.get_training_day(db, day.day_date)
    return DayDetailResponse(
        day=_day(day),
        rule=DayRuleSetResponse.model_validate(rule),
        day_map=_map(day_map(rule)),
        plan=plan,
        has_plan=plan is not None,
        marks=[mark_crud.to_response(mark.item_id, mark) for mark in marks],
        task_counts=mark_crud.to_counts_response(counts),
        notebook=None if notebook is None else notebook.content,
        anchors=await _anchors(db, day.day_date, rule),
        training=(
            None if training is None else TrainingDayResponse.model_validate(training)
        ),
        summary=await summary_crud.summary_for(db, day.day_date, rule, stored, marks),
        work=await work_crud.day_response(db, day.day_date),
    )


async def _anchors(db: AsyncSession, on: date, rule: DayRuleSet) -> DayAnchorsResponse:
    """
    The anchors of one day: one entry per kind of the catalogue, state included.

    Every kind is listed, not only the ones with a row, because «вечера с
    близкими сегодня не было» has to be different from «про вечер с близкими не
    спрашивали» — and the second reading is what the anchor of the third
    priority spent its whole existence in. `required_today` says which of them
    this day is actually judged by: the canon of July names five kinds, the
    catalogue holds six.
    """
    kinds: list[AnchorKind] = await anchor_crud.list_kinds(db)
    stored: dict[str, DayAnchor] = {
        row.kind: row for row in await anchor_crud.list_day_anchors(db, on)
    }
    required = tuple(rule.anchors or ())
    entries = [
        DayAnchorResponse(
            kind=kind.code,
            title=kind.title,
            ord=kind.ord,
            counts_for_verdict=kind.counts_for_verdict,
            required_in_nonwork_evening=kind.required_in_nonwork_evening,
            state=stored[kind.code].state if kind.code in stored else None,
            note=stored[kind.code].note if kind.code in stored else None,
            item_id=stored[kind.code].item_id if kind.code in stored else None,
            required_today=kind.code in required,
        )
        for kind in kinds
    ]
    counts = anchor_crud.anchor_counts(rule, list(stored.values()))
    return DayAnchorsResponse(
        day_date=on.isoformat(),
        anchors=entries,
        done=0 if counts is None else counts.done + counts.skipped,
        total=len(required),
        missing=anchor_crud.missing_anchor_titles(
            kinds, required, list(stored.values())
        ),
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
    # The asymmetry of `#147`: a person's edit is stored and then annotated, a
    # machine's draft is refused. The write has already happened here, so a
    # broken rule becomes a `warn` row beside the plan rather than a 422 — a
    # system that refuses a person the right to edit their own day gets
    # abandoned in a week.
    await violation_crud.record_violations(
        db,
        day.day_date,
        constraints.check_all(
            plan_crud.draft_of(document, day.day_date),
            rule,
            severity=constraints.SEVERITY_WARN,
        ),
        origin=constraints.ORIGIN_HUMAN,
    )
    # Point each anchor of the day at the line it is written on. Only the link:
    # a plan rewritten at 14:00 must not tick or untick anything.
    await anchor_crud.sync_from_plan(db, day.day_date)
    await day_crud.touch_day(db, day, opened=False)
    await db.commit()
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


# Один заголовок на оба касания, описанный один раз. Ключ необязателен: браузер
# его шлёт, `curl` из скрипта — как правило нет, и касание без ключа обязано
# работать ровно так же, только без защиты от повтора.
IDEMPOTENCY_DESCRIPTION = (
    "Ключ повтора. Тот же ключ второй раз — 200 и та же строка, ничего не "
    "записано. Другой ключ на закрытый день — перезакрытие: вердикт и стрик "
    "считаются заново, вторая строка не появляется"
)

# Оба касания отвечают одинаково, оба умеют упереться в чужой ключ — и оба
# отказывают дню, чей итог пришёл прозой (`#90`): такой день не пересчитывают
# ни первым касанием, ни вторым.
TOUCH_RESPONSES: dict[int | str, dict[str, str]] = {
    409: {
        "description": (
            "Либо Idempotency-Key уже применён к другой дате — не повтор и не "
            "новое касание, ответить чужим днём было бы враньём, — либо вердикт "
            "этого дня пришёл прозой из personal-os"
        )
    },
}


def _spent_elsewhere(error: KeyBelongsToAnotherDay) -> HTTPException:
    """The 409 both touches raise, spelled once."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def _refused_import(error: summary_crud.ImportedDayIsNotClosable) -> HTTPException:
    """
    The 409 both touches raise for a day whose итог arrived as prose.

    Оба касания пишут `source`, поэтому запрет стоит на обоих: пустить ревью
    туда, куда не пускают закрытие, значило бы отдать импортированный день
    пересчёту по отметкам, которых у него нет.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


REPORT_NOT_BUILT = "отчёт этого дня ещё не собирали"
REVISION_NOT_FOUND = "такой ревизии отчёта нет"


async def _report_answer(db: AsyncSession, row: DayReport) -> DayReportResponse:
    """Одна ревизия со списком всех ревизий этой даты рядом."""
    revisions = await report_service.list_revisions(db, row.day_date)
    return DayReportResponse(
        day_date=row.day_date,
        revision=row.revision,
        trigger=row.trigger,
        content_md=row.content_md,
        content_hash=row.content_hash,
        sources={
            key: DayReportSource(**value) for key, value in (row.sources or {}).items()
        },
        built_at=row.built_at,
        revisions=revisions,
    )


@router.get("/{on}/report", response_model=DayReportResponse)
async def get_day_report(
    on: date,
    revision: int | None = Query(
        default=None,
        ge=0,
        description="Номер ревизии; без него — последняя собранная",
    ),
    db: AsyncSession = Depends(get_db),
) -> DayReportResponse:
    """
    Отчёт дня: последняя ревизия или названная номером.

    Отчёта может не быть вовсе — его никто не собирал, — и это 404, а не пустой
    текст: «отчёт пуст» и «отчёта нет» ведут к разным следующим действиям.
    """
    row = (
        await report_service.latest_revision(db, on)
        if revision is None
        else await report_service.read_revision(db, on, revision)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=REPORT_NOT_BUILT if revision is None else REVISION_NOT_FOUND,
        )
    return await _report_answer(db, row)


@router.post(
    "/{on}/report",
    response_model=DayReportResponse,
    status_code=status.HTTP_200_OK,
)
async def post_day_report(
    on: date,
    trigger: str = Query(
        default=TRIGGER_API,
        description=f"Повод сборки: {' | '.join(REPORT_TRIGGERS)}",
    ),
    db: AsyncSession = Depends(get_db),
) -> DayReportResponse:
    """
    Пересобрать отчёт дня и отдать ревизию — новую или ту же.

    Данные не менялись — `content_hash` совпадает с последней ревизией, и
    возвращается она: вторая одинаковая ревизия не заводится, `built_at` не
    сдвигается. Прежние ревизии не переписываются никогда.
    """
    if trigger not in REPORT_TRIGGERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"неизвестный повод сборки: {trigger}",
        )
    day, _ = await _resolve(db, on)
    row = await report_service.build_report(db, day.day_date, trigger)
    return await _report_answer(db, row)


@router.post(
    "/{on}/close/review",
    response_model=DaySummaryResponse,
    responses=TOUCH_RESPONSES,
)
async def post_close_review(
    on: date,
    body: DayReviewIn,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_DESCRIPTION
    ),
) -> DaySummaryResponse:
    """
    Касание около 15:40: записать факт по работе, не вынося вердикта.

    Стадия дня становится `reviewed`, `verdict` остаётся `null` — и это «рано»,
    а не «проиграл»: на экране это разные подписи. Вечернее касание
    (`POST .../close/final`) дописывает якоря и выносит вердикт.

    Отметки пунктов сюда не едут: они уже записаны через
    `PUT /day/{date}/marks/{item_id}`, и второй путь для того же факта означал
    бы два ответа на вопрос «сделана ли задача». `null` в любом поле — «не
    трогать записанное», а не «стереть».

    Ревью, пришедшее после вечернего закрытия, уточняет цифры и не откатывает
    день назад: стадия остаётся `closed`.
    """
    day, _ = await _resolve(db, on)
    try:
        answer = await summary_crud.review_day(
            db, day.day_date, body, idempotency_key=idempotency_key
        )
    except KeyBelongsToAnotherDay as error:
        raise _spent_elsewhere(error) from error
    except summary_crud.ImportedDayIsNotClosable as refused:
        raise _refused_import(refused) from refused
    # Отчёт собирается тем же запросом и в той же транзакции: касание 15:40 —
    # момент, когда факт по дню записан, и отчёт, собранный секундой позже
    # отдельной ручкой, описывал бы уже другой день.
    await report_service.build_report(db, day.day_date, TRIGGER_CLOSE)
    return answer


@router.post(
    "/{on}/close/final",
    response_model=DaySummaryResponse,
    responses=TOUCH_RESPONSES,
)
async def post_close_final(
    on: date,
    body: DayCloseIn,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_DESCRIPTION
    ),
) -> DaySummaryResponse:
    """
    Вечернее касание: закрыть день, посчитать вердикт, пересчитать стрик.

    Первого касания могло не быть — это обычный день, а не ошибка: стадия
    прыгает `open → closed`, и ответ несёт `review_skipped: true`.

    Вердикта в теле нет и быть не может: схема приёма его не знает, лишнее поле
    даёт 422. Считает его чистая функция `evaluate_day` по правилу, под которым
    день прожит, а не по нынешнему — канон менялся 2026-08-17, и день до этой
    даты обязан получить тот же ответ, который получил бы тогда.

    Закрытие вчерашнего дня задним числом пересчитывает стрик всей истории, так
    что цифра сегодняшнего дня меняется сама.
    """
    day, _ = await _resolve(db, on)
    try:
        return await summary_crud.close_day(
            db, day.day_date, body, idempotency_key=idempotency_key
        )
    except KeyBelongsToAnotherDay as error:
        raise _spent_elsewhere(error) from error
    except summary_crud.ImportedDayIsNotClosable as refused:
        raise _refused_import(refused) from refused


@router.post(
    "/{on}/close",
    response_model=DaySummaryResponse,
    deprecated=True,
    responses=TOUCH_RESPONSES,
)
async def post_close(
    on: date,
    body: DayCloseIn,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_DESCRIPTION
    ),
) -> DaySummaryResponse:
    """
    Устаревший синоним `POST /day/{date}/close/final`.

    Закрытие идёт в два касания с `#143`, и эта ручка — вечернее из них. Она
    остаётся, потому что её зовут скрипты и старые вкладки, но новый код должен
    звать `final`: имя без стадии перестало быть однозначным.

    Дальше — то же, что делает `final`.

    Вердикт считается по правилу, под которым день прожит, а не по нынешнему:
    канон менялся 2026-08-17, и день до этой даты обязан получить тот же ответ,
    который получил бы тогда. Причина названа машинным кодом — `tasks`,
    `anchors`, `overtime`, — а не «день не выигран»: читателю нужно знать,
    что именно чинить.

    `work_minutes` в теле — оценка на случай дня без интервалов; измерение
    сильнее её, и день, у которого есть `work_interval`, считается по их сумме.
    `null` при обоих пустых — «не измерено», а не ноль: проверка переработки
    пропускается, а факт уходит в `missing_data`.

    Переопределение вердикта требует записки. 422 без неё — от схемы, и то же
    самое отвергает `CHECK` в базе: валидатор это сообщение, а правило — база.

    Повторный вызов **дописывает названные поля**, а не заменяет итог целиком:
    закрытие — состояние дня, и переопределение вердикта, приходящее сюда же
    двумя полями, не имеет права стереть прозу и минуты работы, записанные при
    закрытии. Не прислали поле — прежнее значение осталось.

    409 — день, чей итог пришёл прозой из `personal-os` (`source='import'`).
    Такой вердикт не пересчитывают: его правят в `summaries/` и импортируют
    заново, иначе день попал бы под пересчёт по отметкам, которых у него нет.
    """
    return await post_close_final(on, body, db, idempotency_key)


@router.get("/{on}/work-intervals", response_model=WorkDayResponse)
async def get_work_intervals(
    on: date, db: AsyncSession = Depends(get_db)
) -> WorkDayResponse:
    """
    Интервалы работы за день и их сумма.

    `work_minutes: null` — интервалов нет вообще, то есть «не измерено», а не
    ноль: правило переработки в такой день не проверяется, а факт уходит в
    `missing_data` итога. День, где записаны только паузы (`mode: off`),
    измерен — и отвечает нулём.

    Заголовков окон в ответе нет и быть не может: под них нет колонки. Граница
    приватности проходит по этой таблице — интервал, режим и, самое большее,
    идентификатор приложения. Скриншотов не существует нигде в системе.
    """
    await _resolve(db, on)
    return await work_crud.day_response(db, on)


@router.post(
    "/{on}/work-intervals",
    response_model=WorkIntervalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_work_interval(
    on: date, body: WorkIntervalIn, db: AsyncSession = Depends(get_db)
) -> WorkIntervalResponse:
    """
    Завести интервал работы или паузы.

    Ручной ввод — основной путь, а не запасной: `source` по умолчанию `manual`,
    и запись руками ничем не хуже посчитанной агентом. Объявить `corrected`
    нельзя — в него переводит правка агентского интервала, и это факт, который
    видел сервер, а не слово, которое может напечатать любой клиент.

    Конец можно не присылать: интервал тогда идёт прямо сейчас и считается до
    текущего момента, но не дальше конца своих суток.

    День интервала считается по его началу — интервал 23:00-01:00 принадлежит
    дню начала целиком и пополам не режется. Начало, принадлежащее другому дню,
    отвергается 422, а не подшивается молча к чужой дате.
    """
    await _resolve(db, on)
    try:
        row = await work_crud.create(db, on, body)
    except IntervalNotOnDay as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return work_crud.to_response(row)


@router.patch("/{on}/work-intervals/{interval_id}", response_model=WorkIntervalResponse)
async def patch_work_interval(
    on: date,
    interval_id: UUID,
    body: WorkIntervalPatch,
    db: AsyncSession = Depends(get_db),
) -> WorkIntervalResponse:
    """
    Поправить интервал.

    Правка агентского интервала не затирает предложение: границы, которые
    посчитал агент, уезжают в `auto_started_at`/`auto_ended_at`, `source`
    становится `corrected`, а `edited_at` помечает вмешательство. Экран потому
    и может показать разом исправленное значение и то, что предлагал агент.

    Двигаются только названные в теле поля. `ended_at: null` открывает интервал
    заново, отсутствие `ended_at` не трогает его вовсе — иначе правка заметки
    молча воскрешала бы закрытый час назад интервал.

    404 — интервала с таким id в этом дне нет. Id из другого дня сюда не
    подходит намеренно: интервал адресуется как «этот интервал этого дня».
    """
    await _resolve(db, on)
    row = await work_crud.get(db, on, interval_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В дне {on.isoformat()} нет интервала {interval_id}.",
        )
    try:
        updated = await work_crud.update(db, on, row, body)
    except IntervalNotOnDay as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return work_crud.to_response(updated)


@router.delete(
    "/{on}/work-intervals/{interval_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_work_interval(
    on: date, interval_id: UUID, db: AsyncSession = Depends(get_db)
) -> None:
    """
    Убрать интервал.

    Сумма дня пересчитывается по тому, что осталось; удаление последнего
    интервала возвращает день в «не измерено», а не в ноль.
    """
    await _resolve(db, on)
    row = await work_crud.get(db, on, interval_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В дне {on.isoformat()} нет интервала {interval_id}.",
        )
    await work_crud.delete(db, row)


@router.get("/{on}/plan/violations", response_model=list[PlanViolationResponse])
async def get_plan_violations(
    on: date, db: AsyncSession = Depends(get_db)
) -> list[PlanViolationResponse]:
    """
    Правила, которые план этого дня нарушил.

    `severity='warn'` — правка человека, которая прошла: свой день человек
    правит свободно, а нарушение записывается строкой рядом. `block` — черновик
    машины, который до базы не доехал; он лежит здесь как объяснение, почему
    плана нет.

    В `detail` только id пунктов и числа. Текста пункта там нет и быть не может:
    строки живут дольше плана, который их породил, а задача бывает названа
    диагнозом.
    """
    await _resolve(db, on)
    rows = await violation_crud.list_violations(db, on)
    return [PlanViolationResponse.model_validate(row) for row in rows]


@router.post(
    "/{on}/plan/skeleton",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": SkeletonRejection}},
)
async def post_plan_skeleton(
    on: date, db: AsyncSession = Depends(get_db)
) -> PlanResponse:
    """
    Собрать план дня из канона, без модели.

    Страховка, отгруженная раньше того, что она страхует: после этой ручки день
    не остаётся без плана ни при каком поведении модели — нет ответа, таймаут,
    сломанный JSON, кончившаяся подписка.

    Скелет проходит восемь ограничений **по построению**, потому что собран из
    той же строки правила, против которой они проверяются: края дня — края
    канона, потолок работы — потолок канона, свободный вечер пуст, потому что в
    него ничего не кладётся, а якорь `relationship` появляется ровно тогда,
    когда `relationship_anchor_required` требует его в нерабочий вечер.

    Соседние даты не трогаются: все строки написаны на `on`, и правило
    `target_day_only` это подтверждает. «Сегодня сорвалось — неделю не трогаем»
    здесь машинная проверка, а не договорённость.

    - **201** — план собран и записан
    - **404** — дата вне всех интервалов канона
    - **422** — скелет сам нарушил правило; в `detail` коды правил и id пунктов
    """
    day, rule = await _resolve(db, on)

    built = skeleton.skeleton_plan(day.day_date, rule)
    blocking = constraints.check_all(built.draft, rule)
    if blocking:
        # The skeleton breaking its own rules is a bug in the generator, not a
        # complaint about the day. It is answered rather than swallowed, and the
        # rows are recorded so the failure survives the response.
        await violation_crud.record_violations(
            db, day.day_date, blocking, origin=constraints.ORIGIN_FALLBACK
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "skeleton_violates_canon",
                "violations": [
                    {
                        "rule_code": violation.rule_code,
                        "severity": violation.severity,
                        "detail": violation.detail,
                        "message": violation.message,
                    }
                    for violation in blocking
                ],
            },
        )

    document = violation_crud.skeleton_document(built, rule)
    try:
        stored = await plan_crud.replace_plan(db, day.day_date, rule, document)
    except PlanRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=rejected.as_detail(),
        ) from rejected
    await violation_crud.clear_violations(
        db, day.day_date, origin=constraints.ORIGIN_FALLBACK
    )
    await violation_crud.clear_violations(
        db, day.day_date, origin=constraints.ORIGIN_HUMAN
    )
    await day_crud.touch_day(db, day, opened=False)
    await db.commit()
    return await plan_crud.to_response(db, stored)


# Правка пункта — операция человека, и отвечает она планом целиком: правка
# одной строки двигает соседей, расписание и пересечения окон, а второй запрос
# за днём ради того, что сервер уже знает, — это лишний круг на каждое слово.
EDIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "Пункта или секции нет в плане этого дня"},
    422: {"model": PlanRejection},
}


async def _edited(
    db: AsyncSession,
    day: Day,
    rule: DayRuleSet,
    item_id: UUID | None,
) -> PlanEditResponse:
    """
    Ответ правки: план целиком, тронутый пункт и предупреждения канона.

    Предупреждения считаются **после** записи и по сохранённому плану, а не по
    намерению: асимметрия строгости из ADR-0015 в том и состоит, что правка
    человека проходит, а канон о ней сообщает. Отказ остаётся только за базой.
    """
    plan = await plan_crud.get_plan(db, day.day_date)
    if plan is None:  # pragma: no cover - правка без плана уже отдала 404
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"На {day.day_date.isoformat()} плана нет.",
        )
    await day_crud.touch_day(db, day, opened=_person_is_here(day.day_date))
    response = await plan_crud.to_response(db, plan)
    item = None
    if item_id is not None:
        item = _find_item(response, item_id)
    return PlanEditResponse(
        plan=response,
        item=item,
        warnings=[
            PlanRejection(**broken.as_detail())
            for broken in await plan_crud.human_warnings(db, plan, rule)
        ],
    )


def _find_item(plan: PlanResponse, item_id: UUID) -> PlanItemResponse | None:
    """Найти пункт в уже собранном ответе, чтобы не пересобирать его вторым разом."""
    stack = [item for section in plan.sections for item in section.items]
    while stack:
        item = stack.pop()
        if item.id == item_id:
            return item
        stack.extend(item.children)
    return None


def _plan_rejection(rejected: PlanRejected) -> HTTPException:
    """Отказ правила как 422 в той же форме, что и отказ документа из #87."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=rejected.as_detail(),
    )


@router.patch(
    "/{on}/plan/items/{item_id}",
    response_model=PlanEditResponse,
    responses=EDIT_RESPONSES,
)
async def patch_plan_item(
    on: date,
    item_id: UUID,
    patch: PlanItemPatch,
    db: AsyncSession = Depends(get_db),
) -> PlanEditResponse:
    """
    Поправить один пункт плана, сохранив его id и отметку.

    Присланные поля меняются, остальные не трогаются: `null` в теле — «убрать
    значение», отсутствие ключа — «не трогать». Замена плана целиком остаётся
    `POST .../plan` и операцией генератора; здесь `plan_item.id` переживает
    правку, иначе отметка #88 теряет якорь на каждое исправление слова.

    422 приходит только оттуда, откуда его не миновать, — от `CHECK` базы:
    задача без окна или без критерия, окно в свободном пункте, задача без цели
    квартала и без причины. Правила документа человека не останавливают и
    возвращаются в `warnings`.
    """
    day, rule = await _resolve(db, on)
    try:
        await plan_crud.edit_item(db, day.day_date, item_id, patch)
    except plan_crud.PlanItemNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет пункта {item_id}.",
        ) from missing
    except PlanRejected as rejected:
        raise _plan_rejection(rejected) from rejected
    return await _edited(db, day, rule, item_id)


@router.post(
    "/{on}/plan/sections/{section_id}/items",
    response_model=PlanEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses=EDIT_RESPONSES,
)
async def post_plan_item(
    on: date,
    section_id: UUID,
    payload: PlanItemCreate,
    db: AsyncSession = Depends(get_db),
) -> PlanEditResponse:
    """
    Добавить пункт в секцию. Он встаёт в конец своего уровня.

    `parent_id` делает пункт ребёнком — шагом задачи или «Минимумом»
    тренировки; уровень определяется парой «секция плюс родитель», поэтому
    родитель из чужой секции — 404, а не тихая перевязка.
    """
    day, rule = await _resolve(db, on)
    try:
        item = await plan_crud.add_item(db, day.day_date, section_id, payload)
    except plan_crud.PlanSectionNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет секции {section_id}.",
        ) from missing
    except plan_crud.PlanItemNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет пункта {payload.parent_id}.",
        ) from missing
    except PlanRejected as rejected:
        raise _plan_rejection(rejected) from rejected
    return await _edited(db, day, rule, item.id)


@router.delete(
    "/{on}/plan/items/{item_id}",
    response_model=PlanEditResponse,
    responses=EDIT_RESPONSES,
)
async def delete_plan_item(
    on: date, item_id: UUID, db: AsyncSession = Depends(get_db)
) -> PlanEditResponse:
    """
    Удалить пункт вместе с его детьми и сомкнуть уровень.

    Дочерний «Минимум» уезжает с родителем: минимум без своей задачи — сирота,
    и 29 августа уже показало, чем это кончается на экране.
    """
    day, rule = await _resolve(db, on)
    try:
        await plan_crud.remove_item(db, day.day_date, item_id)
    except plan_crud.PlanItemNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет пункта {item_id}.",
        ) from missing
    return await _edited(db, day, rule, None)


@router.post(
    "/{on}/plan/items/{item_id}/move",
    response_model=PlanEditResponse,
    responses=EDIT_RESPONSES,
)
async def move_plan_item(
    on: date,
    item_id: UUID,
    move: PlanItemMove,
    db: AsyncSession = Depends(get_db),
) -> PlanEditResponse:
    """
    Переставить пункт: в другое место своей секции или в другую секцию.

    Отдельная операция, а не поле `ord` в патче: перетаскивание меняет порядок
    сразу нескольких строк, и построчная запись `ord` оставила бы уровень с
    дырами и дублями. Оба уровня — исходный и приёмный — перенумеровываются
    одной транзакцией.
    """
    day, rule = await _resolve(db, on)
    try:
        await plan_crud.move_item(db, day.day_date, item_id, move)
    except plan_crud.PlanItemNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет пункта {item_id}.",
        ) from missing
    except plan_crud.PlanSectionNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"В плане на {on.isoformat()} нет секции {move.section_id}.",
        ) from missing
    except PlanRejected as rejected:
        raise _plan_rejection(rejected) from rejected
    return await _edited(db, day, rule, item_id)


@router.get("/{on}/anchors", response_model=DayAnchorsResponse)
async def get_anchors(
    on: date, db: AsyncSession = Depends(get_db)
) -> DayAnchorsResponse:
    """
    Якоря дня — по пункту на каждый вид справочника.

    Вид якоря — строка `anchor_kind`, а не значение enum: состав меняется
    `INSERT`-ом и новой строкой правила, и никакой вид не зашит в код. `relationship`
    («вечер с близкими») стоит в этом списке наравне с якорями здоровья, потому
    что третий приоритет `config.md` до `#92` не был выражен ничем.

    `required_today` говорит, судится ли день этим якорем: канон до 2026-08-17
    называет пять видов, справочник держит шесть.
    """
    day, rule = await _resolve(db, on)
    return await _anchors(db, day.day_date, rule)


@router.put("/{on}/anchors", response_model=DayAnchorsResponse)
async def put_anchors(
    on: date, body: DayAnchorsIn, db: AsyncSession = Depends(get_db)
) -> DayAnchorsResponse:
    """
    Отметить якоря дня: `done`, `failed`, `skipped` или `null` — снять отметку.

    Запрос называет вид якоря, а не позицию в списке: порядок — свойство
    отображения, и запрос, опирающийся на него, ломается от `INSERT`-а в
    справочник. Несколько якорей едут одним запросом, потому что вечер закрывает
    три штуки одним движением.

    Второй якорь того же вида на ту же дату не появляется никогда: `UNIQUE(day_date,
    kind)` в базе, а не проверка в сервисе, — запись ложится на ту строку,
    которая уже есть, кто бы ни писал.

    422 — неизвестный вид якоря или состояние вне списка. 404 остаётся за датой,
    которую не покрывает ни одно правило.
    """
    day, rule = await _resolve(db, on)
    known = await anchor_crud.known_codes(db)
    for entry in body.anchors:
        if entry.kind not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Вида якоря «{entry.kind}» нет в справочнике. Состав якорей "
                    "меняется INSERT-ом в `anchor_kind`, а не запросом отметки."
                ),
            )
        if entry.state is not None and entry.state not in ANCHOR_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Состояние якоря — одно из {list(ANCHOR_STATES)} или null.",
            )
        await anchor_crud.set_anchor(
            db, day.day_date, entry.kind, state=entry.state, note=entry.note
        )
    await day_crud.touch_day(db, day, opened=_person_is_here(day.day_date))
    return await _anchors(db, day.day_date, rule)


@router.get("/{on}/training", response_model=TrainingDayResponse | None)
async def get_training(
    on: date, db: AsyncSession = Depends(get_db)
) -> TrainingDayResponse | None:
    """
    Тренировка дня: что запланировано, что сделано, минимум и его пункт плана.

    `null` — на эту дату ничего не записано. Это не то же самое, что пропуск:
    пропуск — это `skipped: true`, и он двигает счётчик `skipped_days`.
    """
    day, _ = await _resolve(db, on)
    row = await training_crud.get_training_day(db, day.day_date)
    return None if row is None else TrainingDayResponse.model_validate(row)


@router.put("/{on}/training", response_model=TrainingDayResponse)
async def put_training(
    on: date, body: TrainingDayIn, db: AsyncSession = Depends(get_db)
) -> TrainingDayResponse:
    """
    Записать тренировку дня. Не названное поле не трогается.

    Утро пишет план, вечер пишет факт, и замена строки целиком дала бы второму
    возможность стереть первое умолчанием.

    `minimum_item_id` — пункт плана, на котором минимум отмечается **своей**
    галкой. 29 августа показало, чего стоит минимум без неё: он был сформулирован
    правильно, стоял в нужном дне и не был выполнен, потому что закрывать его
    было нечем.
    """
    day, _ = await _resolve(db, on)
    row = await training_crud.upsert_training_day(
        db,
        day.day_date,
        patterns=body.patterns,
        heavy_patterns=body.heavy_patterns,
        planned_md=body.planned_md,
        done_md=body.done_md,
        skipped=body.skipped,
        outdoor_done=body.outdoor_done,
        near_failure=body.near_failure,
        note_md=body.note_md,
        minimum_md=body.minimum_md,
        minimum_item_id=body.minimum_item_id,
        sets=body.sets,
    )
    await day_crud.touch_day(db, day, opened=False)
    return TrainingDayResponse.model_validate(row)
