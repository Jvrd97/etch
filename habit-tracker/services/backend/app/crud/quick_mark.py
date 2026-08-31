# [review:need-review] PHASE-03/121, PHASE-03/125, PHASE-03/130
# summary: the quick mark from button to database — the validation the directory owes (`field_id` belongs to the category, `kind` fits the field type), the tap that accumulates into the day's entry through `entry_crud.checklist_entry_id` instead of adding a row, the relapse that deliberately does add one, and the journal row beside every write
"""
What a quick mark means and where its value lands.

Three decisions live here and nowhere else.

**The day is asked, never computed.** `record_event` takes the moment of the tap
and calls `app.core.daytime.local_date()` on it. There is no timezone setting in
this module, no clock read inside the write path and no second arithmetic of
days: a tap at 00:30 lands in the same day a work interval at 00:30 lands in,
because both ask the same function.

**An increment accumulates, it does not append.** `kind='increment'` finds the
canonical entry of `(category_id, entry_date)` with the existing
`entry_crud.checklist_entry_id` and adds its step to the value already there,
rendering the result with `values.format_number`. Five taps are one row of
`entries` and one row of `entry_values`, which is ADR-0007's invariant reaching
the quick path. `kind='relapse'` is the exception on purpose: a relapse is an
event with its own time, and two of them collapsed into a counter would lose the
only thing worth keeping about them.

**The directory validates what `POST /entries` never has.** A button pointing at
a field of somebody else's category, a tick on a number, a relapse on a
`build` category — all three are refused at creation with a reason naming ids,
never values. The shape of the answer is `validate_metric_ops` in
`crud/daily_summary.py`: every reason at once, so one repair pass sees them all.

PII: every message and every log line here is built from ids. `label`, the
stored value and the note are never formatted into either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

import uuid

from app.core.daytime import local_date
from app.crud import entry as entry_crud
from app.crud import mark as mark_crud
from app.crud.values import format_number, parse_number
from app.models import Category, Entry, EntryValue, FieldType
from app.models.mark import MARK_DONE
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.models.quick_mark import (
    KIND_CHECK,
    KIND_INCREMENT,
    KIND_RELAPSE,
    NUMERIC_KINDS,
    QuickMark,
    QuickMarkEvent,
)
from app.schemas.quick_mark import (
    SURFACE_AGENT,
    QuickMarkCreate,
    QuickMarkUpdate,
)

__all__ = [
    "DayState",
    "RecordedEvent",
    "create_quick_mark",
    "day_state",
    "event_by_idempotency_key",
    "get_quick_mark",
    "list_quick_marks",
    "record_event",
    "replayed_event",
    "validate_quick_mark",
]

# The category mode a relapse button is allowed on. A `build` category counts
# days it happened; "сорвался" has no meaning there.
AVOID_STREAK_MODE = "avoid"

# Field types that can hold a number one tap moves.
NUMERIC_FIELD_TYPES: tuple[FieldType, ...] = (FieldType.NUMBER, FieldType.DURATION)

# What one tap is worth when the button has no step and the caller named no
# value — a cigarette, a glass, one of whatever is being counted.
IMPLICIT_AMOUNT = 1.0

# Чем помечается отметка плана, поставленная не рукой в плане, а тапом по
# кнопке. `web` соврал бы: страницу дня никто не открывал.
SOURCE_PLAN_PROPAGATION = "agent"


@dataclass(frozen=True)
class DayState:
    """What a button's day looks like after (or before) a tap."""

    today_total: float | None
    done: bool


@dataclass(frozen=True)
class RecordedEvent:
    """
    A tap as it was written, carried as values rather than as ORM rows.

    The API answers from this without touching the session again, which is what
    keeps "one call per tap" true on the wire and in the code.
    """

    event_id: int
    quick_mark_id: int
    entry_id: int | None
    entry_date: date
    occurred_at: datetime
    state: DayState


async def get_quick_mark(db: AsyncSession, quick_mark_id: int) -> QuickMark | None:
    """One button by id, or None."""
    result = await db.execute(select(QuickMark).where(QuickMark.id == quick_mark_id))
    return result.scalar_one_or_none()


def _ordered() -> Select[tuple[QuickMark]]:
    """
    The directory in the order the buttons are drawn in.

    `id` is the tie-break: buttons entered in one sitting share an `order`, and
    without it the row order of the table would decide which hotkey is `1`.
    """
    return select(QuickMark).order_by(QuickMark.order, QuickMark.id)


async def planned_marks(db: AsyncSession, on: date) -> dict[int, uuid.UUID]:
    """
    Кнопки, названные планом на `on`: id кнопки → id пункта, который её назвал.

    Одним запросом по дню, а не обходом дерева плана: пункт, назвавший кнопку,
    может лежать на любой глубине любой секции, и `quick_mark_id` — это то, по
    чему его находят, а не то, что вычисляют из текста.

    Одна кнопка в двух пунктах одного дня — состояние возможное и не запрещённое
    (утренняя вода и вечерняя). Побеждает первый по `(секция, позиция)`: закрыть
    оба пункта одной отметкой значило бы сказать про вечер то, чего не было.
    """
    result = await db.execute(
        select(PlanItem.quick_mark_id, PlanItem.id)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanItem.quick_mark_id.is_not(None))
        .order_by(PlanSection.ord, PlanItem.ord)
    )
    planned: dict[int, uuid.UUID] = {}
    for quick_mark_id, item_id in result.all():
        if quick_mark_id is not None and quick_mark_id not in planned:
            planned[quick_mark_id] = item_id
    return planned


@dataclass
class ListedMark:
    """
    Кнопка в выдаче: она сама, состояние дня и её место в плане на этот день.

    Не кортеж из трёх, потому что третье поле приехало позже двух первых и
    следующее приедет так же: `#125` добавит поверхность, `#129` — челлендж.
    """

    mark: QuickMark
    state: DayState
    planned_item_id: uuid.UUID | None

    @property
    def planned(self) -> bool:
        """Названа ли эта кнопка планом на запрошенный день."""
        return self.planned_item_id is not None


async def list_quick_marks(
    db: AsyncSession,
    *,
    on: date,
    active_only: bool = True,
    surface: str | None = None,
) -> list[ListedMark]:
    """
    The directory with the state of the day `on` attached to every button.

    One query per button for the state is deliberate: the directory is nine to
    twenty rows by design (`hotkey` is one character), and a hand-written join
    over the EAV would be a second implementation of "what does today say" next
    to `day_state`.

    Плановые кнопки идут первыми (#130). Порядок считает сервер, а не экран:
    выдача одна на веб, окно агента и iOS, и порядок, посчитанный в браузере,
    был бы порядком, которого нет у двух остальных. Внутри каждой половины
    сохраняется порядок справочника — «плановая» поднимает кнопку, а не
    перетасовывает её с соседками.

    День без плана — пустой словарь и порядок справочника: ни пустого блока, ни
    сообщения «плана нет» посреди кнопок.

    `surface='agent'` оставляет только кнопки с `show_in_agent` (#125). Порядок
    и `planned` при этом те же самые — в окне помещается пять-шесть кнопок, но
    это те же пять-шесть, что стоят первыми на Today.
    """
    query = _ordered()
    if active_only:
        query = query.where(QuickMark.is_active.is_(True))
    if surface == SURFACE_AGENT:
        # Фильтр здесь, внутри общей выборки, а не отдельной функцией (#125):
        # вторая выборка — это второй порядок и второй `planned`, то есть окно
        # агента, показывающее не то, что веб.
        query = query.where(QuickMark.show_in_agent.is_(True))
    result = await db.execute(query)
    marks = list(result.scalars().all())
    planned = await planned_marks(db, on)
    listed = [
        ListedMark(
            mark=mark,
            state=await day_state(db, mark, on),
            planned_item_id=planned.get(mark.id),
        )
        for mark in marks
    ]
    # Устойчивая сортировка: внутри «плановых» и «остальных» порядок остаётся
    # тем, который задал справочник.
    return sorted(listed, key=lambda one: not one.planned)


async def _day_total(db: AsyncSession, mark: QuickMark, on: date) -> float | None:
    """
    Everything the day holds for this button's field, summed.

    Sums across every entry of `(category_id, on)` rather than reading the
    canonical one: an increment keeps its number in that single entry, but a
    relapse writes a row per event, and both have to report the same way or the
    two kinds of button would count differently on the same screen.
    """
    result = await db.execute(
        select(EntryValue.value, EntryValue.entry_id)
        .join(Entry, Entry.id == EntryValue.entry_id)
        .where(
            Entry.category_id == mark.category_id,
            Entry.entry_date == on,
            EntryValue.field_id == mark.field_id,
        )
    )
    rows = result.all()
    if not rows:
        return None
    numbers = [
        parse_number(value, field_id=mark.field_id, entry_id=entry_id)
        for value, entry_id in rows
    ]
    return float(sum(number for number in numbers if number is not None))


async def day_state(db: AsyncSession, mark: QuickMark, on: date) -> DayState:
    """
    What the day says about this button right now.

    A tick answers with `today_total=None`: a box is not a quantity, and a 1
    there would be read as "one litre" by whatever draws the number. Everything
    else answers with the sum, and `done` is that sum having moved off zero.
    """
    if mark.kind == KIND_CHECK:
        ticks = await entry_crud.get_checklist_state(db, mark.category_id, on)
        return DayState(today_total=None, done=ticks.get(mark.field_id, False))

    total = await _day_total(db, mark, on)
    return DayState(today_total=total, done=total is not None and total > 0)


def validate_quick_mark(data: QuickMarkCreate, category: Category | None) -> list[str]:
    """
    Every reason the button cannot be created, so one repair pass sees them all.

    Semantic, not formal: Pydantic already knows the shape. Checked here is that
    the ids point somewhere real and agree with each other — the category
    exists, the field is that category's own, the kind fits what the field can
    hold, and a button that writes a number knows how much one tap is worth.
    """
    if category is None:
        return [f"unknown category_id {data.category_id}"]

    errors: list[str] = []
    field = next((f for f in category.fields if f.id == data.field_id), None)
    if field is None:
        errors.append(
            f"field_id {data.field_id} does not belong to "
            f"category_id {data.category_id}"
        )
    elif data.kind in NUMERIC_KINDS and field.field_type not in NUMERIC_FIELD_TYPES:
        errors.append(
            f"kind {data.kind!r} needs a number field, but field_id "
            f"{data.field_id} has field_type {field.field_type.value!r}"
        )
    elif data.kind == KIND_CHECK and field.field_type is not FieldType.BOOLEAN:
        errors.append(
            f"kind {KIND_CHECK!r} needs a checkbox, but field_id "
            f"{data.field_id} has field_type {field.field_type.value!r}"
        )

    if data.kind == KIND_RELAPSE and category.streak_mode != AVOID_STREAK_MODE:
        errors.append(
            f"kind {KIND_RELAPSE!r} needs an avoid category, but category_id "
            f"{data.category_id} has streak_mode {category.streak_mode!r}"
        )

    if data.kind in NUMERIC_KINDS and data.step is None:
        errors.append(
            f"kind {data.kind!r} needs a step: one tap has to be worth something"
        )

    return errors


async def create_quick_mark(db: AsyncSession, data: QuickMarkCreate) -> QuickMark:
    """
    Store a validated button.

    Validation is the caller's, not this function's: the API answers a list of
    reasons with 422, and doing it here would make the reasons an exception the
    endpoint has to translate back into the same list.
    """
    mark = QuickMark(
        label=data.label,
        category_id=data.category_id,
        field_id=data.field_id,
        kind=data.kind,
        step=None if data.step is None else Decimal(str(data.step)),
        unit_label=data.unit_label,
        icon=data.icon,
        color=data.color,
        hotkey=data.hotkey,
        order=data.order,
        show_in_agent=data.show_in_agent,
        is_active=data.is_active,
    )
    db.add(mark)
    await db.commit()
    await db.refresh(mark)
    return mark


async def event_by_idempotency_key(
    db: AsyncSession, idempotency_key: str
) -> QuickMarkEvent | None:
    """The tap already recorded under this key, or None."""
    result = await db.execute(
        select(QuickMarkEvent).where(QuickMarkEvent.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


def _amount(mark: QuickMark, value: float | None) -> float:
    """
    How much this tap writes.

    The caller's value wins over the button's step — that is how "250" typed by
    hand goes through the same path as the button — and a button with neither is
    worth one of whatever it counts.
    """
    if value is not None:
        return value
    if mark.step is not None:
        return float(mark.step)
    return IMPLICIT_AMOUNT


async def _entry_value(
    db: AsyncSession, entry_id: int, field_id: int
) -> EntryValue | None:
    result = await db.execute(
        select(EntryValue).where(
            EntryValue.entry_id == entry_id, EntryValue.field_id == field_id
        )
    )
    return result.scalar_one_or_none()


async def _write_number(
    db: AsyncSession, mark: QuickMark, on: date, amount: float, *, accumulate: bool
) -> tuple[int, float]:
    """
    Put `amount` into the day's entry, adding to what is there or replacing it.

    Returns the entry it landed in and how far the stored value moved, which is
    what the journal records. The entry is chosen by
    `entry_crud.checklist_entry_id` — the one rule for "which row is the day" —
    so a quick mark, a tick and the day-summary apply all deepen the same row
    instead of racing to create three.
    """
    entry_id = await entry_crud.checklist_entry_id(db, mark.category_id, on)
    if entry_id is None:
        entry = Entry(category_id=mark.category_id, entry_date=on)
        db.add(entry)
        await db.flush()
        entry_id = entry.id

    existing = await _entry_value(db, entry_id, mark.field_id)
    previous = 0.0
    if existing is not None:
        parsed = parse_number(existing.value, field_id=mark.field_id, entry_id=entry_id)
        previous = 0.0 if parsed is None else parsed

    updated = previous + amount if accumulate else amount
    rendered = format_number(updated)
    if existing is None:
        db.add(EntryValue(entry_id=entry_id, field_id=mark.field_id, value=rendered))
    else:
        existing.value = rendered

    await db.flush()
    return entry_id, updated - previous


async def _write_relapse(
    db: AsyncSession, mark: QuickMark, on: date, amount: float
) -> int:
    """
    Append one relapse: a new entry, with its own `created_at` and its own row.

    The only writer here that does not converge on the day's entry, and the
    reason is in ADR-0018: the history has to show every relapse with its time,
    not a counter that says three.
    """
    entry = Entry(category_id=mark.category_id, entry_date=on)
    db.add(entry)
    await db.flush()
    db.add(
        EntryValue(
            entry_id=entry.id, field_id=mark.field_id, value=format_number(amount)
        )
    )
    await db.flush()
    return entry.id


async def record_event(
    db: AsyncSession,
    mark: QuickMark,
    *,
    at: datetime,
    value: float | None = None,
    utc_offset_minutes: int = 0,
    source: str,
    idempotency_key: str | None = None,
) -> RecordedEvent:
    """
    Apply one tap of `mark` made at the moment `at`, and journal it.

    `at` is a required, timezone-aware moment rather than a default of "now":
    the day it belongs to is `local_date(at)`, and a test that wants to know
    where 00:30 lands has to be able to say which 00:30 it means. `local_date`
    refuses a naive datetime, so a caller that forgets the timezone fails loudly
    instead of shifting the day by the local offset.
    """
    on = local_date(at)
    entry_id: int | None
    delta: float | None = None
    bool_value: bool | None = None

    if mark.kind == KIND_CHECK:
        # Zero means "снять галку" — the one value a tick reads as false, and
        # the only way a button can untick without a second endpoint.
        bool_value = value is None or value != 0
        entry = await entry_crud.upsert_checklist_values(
            db, mark.category_id, on, {mark.field_id: bool_value}
        )
        entry_id = entry.id
    elif mark.kind == KIND_RELAPSE:
        amount = _amount(mark, value)
        entry_id = await _write_relapse(db, mark, on, amount)
        delta = amount
    else:
        amount = _amount(mark, value)
        entry_id, delta = await _write_number(
            db, mark, on, amount, accumulate=mark.kind == KIND_INCREMENT
        )

    event = QuickMarkEvent(
        quick_mark_id=mark.id,
        entry_id=entry_id,
        entry_date=on,
        occurred_at=at,
        utc_offset_minutes=utc_offset_minutes,
        delta=None if delta is None else Decimal(str(delta)),
        bool_value=bool_value,
        source=source,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    await db.flush()

    state = await day_state(db, mark, on)
    await _close_planned_item(db, mark, on, state)
    recorded = RecordedEvent(
        event_id=event.id,
        quick_mark_id=mark.id,
        entry_id=entry_id,
        entry_date=on,
        occurred_at=event.occurred_at,
        state=state,
    )
    await db.commit()
    return recorded


async def _close_planned_item(
    db: AsyncSession, mark: QuickMark, on: date, state: DayState
) -> None:
    """
    Закрыть пункт плана, который назвал эту кнопку, когда цель дня достигнута.

    Иначе человек отмечает дважды — на Today и в плане, — а это ровно тот дубль,
    от которого система уходит.

    Закрывается только вперёд: снятая галка и обнулённый счётчик пункт не
    открывают обратно. Отметка пункта — суждение человека о дне, и стирать его
    потому, что счётчик вернулся к нулю, значит спорить с автором дня.
    """
    if not state.done:
        return
    planned = await planned_marks(db, on)
    item_id = planned.get(mark.id)
    if item_id is None:
        return
    existing = await mark_crud.get_mark(db, item_id)
    if existing is not None and existing.state == MARK_DONE:
        return
    await mark_crud.set_mark(
        db,
        on,
        item_id,
        state=MARK_DONE,
        note=existing.note if existing is not None else None,
        source=SOURCE_PLAN_PROPAGATION,
    )


async def replayed_event(
    db: AsyncSession, mark: QuickMark, event: QuickMarkEvent
) -> RecordedEvent:
    """
    The answer to a tap that was already recorded under this idempotency key.

    Reads the day again rather than replaying anything: the caller is entitled
    to the current state, and the point of the key is that the second request
    changed nothing.
    """
    return RecordedEvent(
        event_id=event.id,
        quick_mark_id=event.quick_mark_id,
        entry_id=event.entry_id,
        entry_date=event.entry_date,
        occurred_at=event.occurred_at,
        state=await day_state(db, mark, event.entry_date),
    )


# --- Управление справочником (#125) ---------------------------------------
#
# Справочник, который нельзя завести из интерфейса, заводится SQL-ом, а человек
# не станет писать INSERT, чтобы поменять шаг воды с 250 на 300.


async def hotkey_owner(
    db: AsyncSession, hotkey: str, *, exclude_id: int | None = None
) -> QuickMark | None:
    """
    Кнопка, которая уже держит эту клавишу, либо None.

    Уникальность гарантирует частичный индекс, а это — ответ. `IntegrityError`
    называет имя ограничения, а человеку нужно «эта клавиша занята кнопкой
    «Отжимания»» и возможность поправить, не потеряв заполненную форму.
    """
    query = select(QuickMark).where(QuickMark.hotkey == hotkey)
    if exclude_id is not None:
        query = query.where(QuickMark.id != exclude_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


def merged_for_validation(mark: QuickMark, data: QuickMarkUpdate) -> QuickMarkCreate:
    """
    Кнопка после правки — в том виде, в каком её судит `validate_quick_mark`.

    Правка проверяется целиком, а не по присланным полям: `kind`, `field_id` и
    `step` образуют одно утверждение, и патч, меняющий только `kind`, способен
    сделать невозможной пару, которую он не трогал.
    """
    fields = data.model_dump(exclude_unset=True)
    return QuickMarkCreate(
        label=fields.get("label", mark.label),
        category_id=fields.get("category_id", mark.category_id),
        field_id=fields.get("field_id", mark.field_id),
        kind=fields.get("kind", mark.kind),
        step=fields.get("step", None if mark.step is None else float(mark.step)),
        unit_label=fields.get("unit_label", mark.unit_label),
        icon=fields.get("icon", mark.icon),
        color=fields.get("color", mark.color),
        hotkey=fields.get("hotkey", mark.hotkey),
        order=fields.get("order", mark.order),
        show_in_agent=fields.get("show_in_agent", mark.show_in_agent),
        is_active=fields.get("is_active", mark.is_active),
    )


async def update_quick_mark(
    db: AsyncSession, mark: QuickMark, data: QuickMarkUpdate
) -> QuickMark:
    """
    Записать правку кнопки. Валидация — забота вызывающего, как и при создании.

    `step` кладётся строкой в `Decimal`: путь через `float` теряет 0.1 так же
    надёжно, как и везде, а шаг кнопки — то число, которое человек напечатал.
    """
    fields = data.model_dump(exclude_unset=True)
    for name, value in fields.items():
        if name == "step":
            mark.step = None if value is None else Decimal(str(value))
        else:
            setattr(mark, name, value)
    await db.flush()
    return mark


async def delete_quick_mark(db: AsyncSession, mark: QuickMark) -> None:
    """
    Убрать кнопку из справочника.

    Ни `entries`, ни `entry_values` не трогаются: выпитая вода остаётся
    выпитой, и удаление кнопки — это про экран, а не про прожитый день.
    Журнал тапов уезжает каскадом внешнего ключа — он и есть журнал этой
    кнопки, и без неё отвечать ему не на что.
    """
    await db.delete(mark)
    await db.flush()


async def reorder_quick_marks(db: AsyncSession, ids: list[int]) -> list[QuickMark]:
    """
    Перенумеровать справочник по присланному списку сверху вниз.

    Кнопки, которых в списке нет, уезжают под него в прежнем порядке: экран мог
    прислать порядок, собранный до того, как соседняя вкладка завела новую
    кнопку, и терять её из-за этого не за что.

    Возвращается весь справочник в новом порядке — тем же чтением, которым его
    рисует экран, чтобы ответ не пришлось сверять со вторым запросом.
    """
    result = await db.execute(_ordered())
    marks = list(result.scalars().all())
    by_id = {mark.id: mark for mark in marks}
    ordered = [by_id[one] for one in ids if one in by_id]
    named = {one.id for one in ordered}
    ordered.extend(mark for mark in marks if mark.id not in named)
    for position, mark in enumerate(ordered):
        mark.order = position
    await db.flush()
    return ordered
