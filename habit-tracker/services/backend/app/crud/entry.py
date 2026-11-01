# [review:need-review] PHASE-01/73-dashboard-hero-today-ring
# summary: get_entries takes the EntrySort ordering (created_at desc tie-broken by id); the rest is the existing entry CRUD — idempotency-key lookup, plus the checklist trio: checklist_entry_id (the one rule for "the day's entry"), get_checklist_state reading that entry's ticks and the transaction-free upsert_checklist_values the day-summary apply reuses
# [review:need-review] 309
# summary: #309 — the canonical entry and the ticks of the day are read for many categories at once (`checklist_entry_ids`, `get_checklist_states`), the one-category readers ask the batch; create_entry reads the written row back once, without a refresh before the select
# [review:need-review] 312
# summary: #312 — `lock_day` serialises the writers of one category's day (`pg_advisory_xact_lock`), `lock_days` takes several in one fixed order, and `upsert_checklist_values` takes the day before it looks for the day's row, so two ticks at once cannot both create one
from collections.abc import Collection, Iterable
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, and_, text
from sqlalchemy.orm import selectinload

from app.core.locks import lock_key
from app.crud.values import is_true_value
from app.models import Entry, EntryValue, Field, FieldType
from app.schemas import EntryCreate, EntrySort, EntryUpdate

# How this module *writes* a box into `entry_values.value`, which is text for
# every field type. Reading is not the mirror of it: `POST /entries` stores the
# string it is handed, so a box may already say "1" or "yes". What counts as
# ticked is `app.crud.values.is_true_value`, the one rule streaks and the table
# have always used — comparing against CHECKED_VALUE here would make those
# spellings read as empty and let a merge write "false" over a real tick.
CHECKED_VALUE = "true"
UNCHECKED_VALUE = "false"


async def get_entry(db: AsyncSession, entry_id: int) -> Entry | None:
    """Получить запись по ID с значениями"""
    result = await db.execute(
        select(Entry).options(selectinload(Entry.values)).where(Entry.id == entry_id)
    )
    return result.scalar_one_or_none()


async def get_entries(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    category_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    sort: EntrySort = EntrySort.ENTRY_DATE_DESC,
) -> list[Entry]:
    """
    Получить список записей с фильтрацией.

    Args:
        category_id: Фильтр по категории
        start_date: Начальная дата
        end_date: Конечная дата
        sort: Порядок выдачи (см. `EntrySort`); по умолчанию — прежний,
            по дате события

    При сортировке по времени записи добавляется вторичный ключ `id desc`:
    `created_at` ставится сервером с точностью базы, и две записи, сохранённые
    в одну секунду, иначе возвращались бы в произвольном порядке — «последняя
    запись» на дашборде прыгала бы между ними от запроса к запросу.
    """
    query = select(Entry).options(selectinload(Entry.values))

    # Применяем фильтры
    filters = []
    if category_id:
        filters.append(Entry.category_id == category_id)
    if start_date:
        filters.append(Entry.entry_date >= start_date)
    if end_date:
        filters.append(Entry.entry_date <= end_date)

    if filters:
        query = query.where(and_(*filters))

    if sort is EntrySort.CREATED_AT_DESC:
        query = query.order_by(Entry.created_at.desc(), Entry.id.desc())
    else:
        query = query.order_by(Entry.entry_date.desc())

    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_entry_by_idempotency_key(
    db: AsyncSession, idempotency_key: str
) -> Entry | None:
    """Найти запись по client-supplied idempotency key (для дедупа повторов)."""
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.values))
        .where(Entry.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def create_entry(
    db: AsyncSession, entry: EntryCreate, idempotency_key: str | None = None
) -> Entry:
    """
    Создать новую запись с значениями полей.

    Если передан idempotency_key, он сохраняется на записи; повторный create
    с тем же ключом отсекается на уровне API (unique-констрейнт как backstop).
    """
    # Создаём запись
    db_entry = Entry(
        category_id=entry.category_id,
        entry_date=entry.entry_date,
        notes=entry.notes,
        idempotency_key=idempotency_key,
    )
    db.add(db_entry)
    await db.flush()  # Получаем ID записи

    # Создаём значения полей
    if entry.values:
        for value_data in entry.values:
            db_value = EntryValue(
                entry_id=db_entry.id,
                field_id=value_data.field_id,
                value=value_data.value,
            )
            db.add(db_value)

    await db.commit()

    # Одно чтение записанного: строка со значениями по умолчанию из базы
    # (`created_at`) и её значения. `populate_existing` — объект уже лежит в
    # identity map после flush, а отдельный `refresh` перед этим select читал
    # ту же строку второй раз (#309).
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.values))
        .where(Entry.id == db_entry.id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def update_entry(
    db: AsyncSession, entry_id: int, entry_update: EntryUpdate
) -> Entry | None:
    """
    Обновить запись.

    Если переданы новые значения (values), старые удаляются.
    """
    db_entry = await get_entry(db, entry_id)
    if not db_entry:
        return None

    # Обновляем базовые поля
    update_data = entry_update.model_dump(exclude_unset=True, exclude={"values"})
    for field, value in update_data.items():
        setattr(db_entry, field, value)

    # Обновляем значения полей, если переданы
    if entry_update.values is not None:
        # Удаляем старые значения
        for old_value in db_entry.values:
            await db.delete(old_value)
        await db.flush()

        # Создаём новые
        for value_data in entry_update.values:
            db_value = EntryValue(
                entry_id=db_entry.id,
                field_id=value_data.field_id,
                value=value_data.value,
            )
            db.add(db_value)

    await db.commit()
    await db.refresh(db_entry)

    # Загружаем значения
    result = await db.execute(
        select(Entry).options(selectinload(Entry.values)).where(Entry.id == db_entry.id)
    )
    return result.scalar_one()


async def delete_entry(db: AsyncSession, entry_id: int) -> bool:
    """Удалить запись (каскадно удаляет значения)"""
    db_entry = await get_entry(db, entry_id)
    if not db_entry:
        return False

    await db.delete(db_entry)
    await db.commit()
    return True


async def lock_day(db: AsyncSession, category_id: int, entry_date: date) -> None:
    """
    Hold one category's day until the transaction ends; the next writer of it waits.

    A writer of the day reads the day's row and its value, then writes over it.
    Two of them at once — two presses of `+250`, a double tap on a box — read the
    same "before": a step is lost, and on an empty day each creates its own row.
    `entries` has no unique `(category_id, entry_date)` and cannot have one (a
    relapse appends a row per press on purpose), and `FOR UPDATE` has nothing to
    lock while the day has no row yet. So the day is held by an advisory lock
    keyed on category and date.

    The lock is transactional: commit or rollback releases it, so it cannot be
    left behind. Taking it again in the same transaction does not wait, so every
    writer can take it without knowing whether its caller already has. Read the
    day after this call: under READ COMMITTED the next statement sees what the
    previous holder committed.

    A transaction that needs the days of several categories takes them through
    `lock_days`, never one by one in its own order.
    """
    key = lock_key(f"entries.day:{category_id}:{entry_date.isoformat()}")
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def lock_days(
    db: AsyncSession, category_ids: Iterable[int], entry_date: date
) -> None:
    """
    Hold the day of several categories, always in ascending `category_id`.

    One order for every transaction is what keeps two of them from waiting for
    each other: taken in the order of the request, an apply naming `[A, B]` and
    one naming `[B, A]` would each hold one day and queue for the other. A
    single-category writer takes one lock and cannot close such a cycle.
    """
    for category_id in sorted(set(category_ids)):
        await lock_day(db, category_id, entry_date)


async def checklist_entry_ids(
    db: AsyncSession, category_ids: Collection[int], entry_date: date
) -> dict[int, int]:
    """
    id канонической записи `(category_id, entry_date)` для каждой категории, у которой она есть.

    Одна запись на категорию за дату — это инвариант, а не ограничение БД:
    строки за ту же дату могли появиться до его введения или из формы. Правило
    «какая из них и есть день» живёт здесь одно на всех — читатель галок,
    писатель галок и запись метрик в checklist-категорию обязаны выбирать одну
    и ту же строку, иначе галка, поставленная в одну, читалась бы из другой.
    Наименьший id не оптимизация: без него выбор был бы произвольным и два
    вызова подряд могли бы разойтись.

    Пачкой, а не по категории: справочник кнопок спрашивает день всех своих
    галок одним запросом (#309).
    """
    result = await db.execute(
        select(Entry.category_id, func.min(Entry.id))
        .where(
            and_(Entry.category_id.in_(category_ids), Entry.entry_date == entry_date)
        )
        .group_by(Entry.category_id)
    )
    return {category_id: entry_id for category_id, entry_id in result.all()}


async def checklist_entry_id(
    db: AsyncSession, category_id: int, entry_date: date
) -> int | None:
    """id канонической записи `(category_id, entry_date)` или None, если её нет."""
    return (await checklist_entry_ids(db, [category_id], entry_date)).get(category_id)


async def get_checklist_states(
    db: AsyncSession, category_ids: Collection[int], entry_date: date
) -> dict[int, dict[int, bool]]:
    """
    Состояние галок каждой категории за дату: `{category_id: {field_id: checked}}`.

    Категории без записи за дату в ответе нет.

    Читается ровно та запись, в которую пишет `upsert_checklist_values`
    (`checklist_entry_ids`), а не все записи за дату. Посторонняя строка за ту
    же дату — из формы или доставшаяся от времён без инварианта — содержит своё
    значение того же поля, и объединение по дате давало результат, зависящий от
    порядка строк в выдаче: галка, стоящая в записи дня, могла прочитаться как
    снятая.

    Возвращаются только boolean-поля, даже если у категории есть и другие.
    Карта из этого чтения уходит обратно в `upsert_checklist_values`, который
    пишет каждое значение как "true"/"false"; попади сюда числовое поле, разбор
    дня переписал бы 30 отжиманий в "false".
    """
    entry_ids = await checklist_entry_ids(db, category_ids, entry_date)
    if not entry_ids:
        return {}

    category_of = {entry_id: category_id for category_id, entry_id in entry_ids.items()}
    result = await db.execute(
        select(EntryValue.entry_id, EntryValue.field_id, EntryValue.value)
        .join(Field, EntryValue.field_id == Field.id)
        .where(
            and_(
                EntryValue.entry_id.in_(list(category_of)),
                Field.field_type == FieldType.BOOLEAN,
            )
        )
    )
    states: dict[int, dict[int, bool]] = {category_id: {} for category_id in entry_ids}
    for entry_id, field_id, value in result.all():
        states[category_of[entry_id]][field_id] = is_true_value(value)
    return states


async def get_checklist_state(
    db: AsyncSession, category_id: int, entry_date: date
) -> dict[int, bool]:
    """Состояние галок категории за дату: `{field_id: checked}`, пустое — если записи нет."""
    states = await get_checklist_states(db, [category_id], entry_date)
    return states.get(category_id, {})


async def upsert_checklist_values(
    db: AsyncSession, category_id: int, entry_date: date, values: dict[int, bool]
) -> Entry:
    """
    Записать карту галок за дату, не закрывая транзакцию.

    Гарантирует одну запись на (category_id, entry_date): существующая
    запись (`checklist_entry_id` — тот же выбор, что делает чтение)
    переиспользуется, boolean-значения обновляются на месте (без дублей
    EntryValue при повторных вызовах).

    Коммита здесь нет намеренно: разбор дня применяет галки в одной транзакции
    с метриками и текстом дня, и промежуточный коммит сделал бы частично
    применённый день достижимым состоянием. Транзакцией владеет вызывающий —
    `upsert_checklist_entry` для ручки `PUT /entries/checklist`, apply разбора
    дня для всего остального.

    The day is taken (`lock_day`) before the row is looked for: two calls at
    once on an empty day would otherwise create a row each.
    """
    await lock_day(db, category_id, entry_date)
    entry_id = await checklist_entry_id(db, category_id, entry_date)

    if entry_id is None:
        db_entry = Entry(category_id=category_id, entry_date=entry_date)
        db.add(db_entry)
        await db.flush()
        existing_values: dict[int, EntryValue] = {}
    else:
        result = await db.execute(
            select(Entry)
            .options(selectinload(Entry.values))
            .where(Entry.id == entry_id)
        )
        db_entry = result.scalars().one()
        existing_values = {v.field_id: v for v in db_entry.values}

    for field_id, checked in values.items():
        str_value = CHECKED_VALUE if checked else UNCHECKED_VALUE
        existing = existing_values.get(field_id)
        if existing is not None:
            existing.value = str_value
        else:
            db.add(EntryValue(entry_id=db_entry.id, field_id=field_id, value=str_value))

    await db.flush()
    return db_entry


async def upsert_checklist_entry(
    db: AsyncSession, category_id: int, entry_date: date, values: dict[int, bool]
) -> Entry:
    """Идемпотентный upsert записи checklist-категории с коммитом."""
    db_entry = await upsert_checklist_values(db, category_id, entry_date, values)
    await db.commit()

    result = await db.execute(
        select(Entry).options(selectinload(Entry.values)).where(Entry.id == db_entry.id)
    )
    return result.scalar_one()


async def get_entries_by_date_range(
    db: AsyncSession, category_id: int, start_date: date, end_date: date
) -> list[Entry]:
    """Получить записи за период для конкретной категории"""
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.values))
        .where(
            and_(
                Entry.category_id == category_id,
                Entry.entry_date >= start_date,
                Entry.entry_date <= end_date,
            )
        )
        .order_by(Entry.entry_date.asc())
    )
    return list(result.scalars().all())
