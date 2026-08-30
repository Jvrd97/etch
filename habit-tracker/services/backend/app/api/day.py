# [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/91, PHASE-03/143
# summary: GET /day (today by the day boundary) and GET /day/{date} — the day, the rule in force on it, its plan with schedule and overlaps, its marks, its notebook and the итог with the verdict; POST /day/{date}/plan takes the whole plan as one document, POST /day/{date}/close/review is the 15:40 touch and /close/final the evening one that writes the verdict (the bare /close stays as a synonym of `final`), both idempotent by `Idempotency-Key`, PUT .../marks/{item_id} takes one mark and PUT .../notebook the day's text; all three writes claim `opened_at` only inside the open window; .../work-intervals is the CRUD of measured work, which the day answers with as intervals plus a sum and never as a window title
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import summary as summary_crud
from app.crud import work_interval as work_crud
from app.crud.summary import KeyBelongsToAnotherDay
from app.crud.work_interval import IntervalNotOnDay
from app.day.plan_validate import PlanRejected
from app.day.rules import NoRuleForDate, is_openable
from app.models.day import Day, DayRuleSet
from app.models.mark import SOURCE_WEB
from app.schemas.day import DayDetailResponse, DayResponse, DayRuleSetResponse
from app.schemas.mark import (
    MarkIn,
    MarkResponse,
    NotebookIn,
    NotebookResponse,
)
from app.schemas.plan import PlanDocument, PlanRejection, PlanResponse
from app.schemas.summary import DayCloseIn, DayReviewIn, DaySummaryResponse
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
        plan=plan,
        has_plan=plan is not None,
        marks=[mark_crud.to_response(mark.item_id, mark) for mark in marks],
        task_counts=mark_crud.to_counts_response(counts),
        notebook=None if notebook is None else notebook.content,
        summary=await summary_crud.summary_for(db, day.day_date, rule, stored, marks),
        work=await work_crud.day_response(db, day.day_date),
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

    Отдаёт сам день, правило, по которому он считается, план — секциями,
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


# Один заголовок на оба касания, описанный один раз. Ключ необязателен: браузер
# его шлёт, `curl` из скрипта — как правило нет, и касание без ключа обязано
# работать ровно так же, только без защиты от повтора.
IDEMPOTENCY_DESCRIPTION = (
    "Ключ повтора. Тот же ключ второй раз — 200 и та же строка, ничего не "
    "записано. Другой ключ на закрытый день — перезакрытие: вердикт и стрик "
    "считаются заново, вторая строка не появляется"
)

# Оба касания отвечают одинаково, и оба умеют упереться в чужой ключ.
TOUCH_RESPONSES: dict[int | str, dict[str, str]] = {
    409: {
        "description": (
            "Idempotency-Key уже применён к другой дате. Не повтор и не новое "
            "касание: ответить чужим днём было бы враньём"
        )
    },
}


def _spent_elsewhere(error: KeyBelongsToAnotherDay) -> HTTPException:
    """The 409 both touches raise, spelled once."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


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
        return await summary_crud.review_day(
            db, day.day_date, body, idempotency_key=idempotency_key
        )
    except KeyBelongsToAnotherDay as error:
        raise _spent_elsewhere(error) from error


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

    Повторный вызов заменяет итог, а не добавляет второй: закрытие — состояние
    дня, а не запись в журнале.
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
