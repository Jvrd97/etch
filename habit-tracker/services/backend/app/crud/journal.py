# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: journal CRUD + the day's single entry (get_day_journal_entry) and the non-committing append/create/replace write, taking plain fields so the journal layer knows nothing of the daily-summary DTOs
from datetime import date
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.models import JournalEntry
from app.schemas import JournalEntryCreate, JournalEntryUpdate

# What separates the text already in the day from the text appended to it. A
# horizontal rule renders as one in Markdown and reads as one in plain text, so
# the seam stays visible wherever the entry is shown.
DAY_JOURNAL_SEPARATOR = "\n\n---\n\n"


async def get_journal_entry(db: AsyncSession, entry_id: int) -> JournalEntry | None:
    """Получить дневниковую запись по ID"""
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
    return result.scalar_one_or_none()


async def get_journal_entries(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    start_date: date | None = None,
    end_date: date | None = None,
    mood: str | None = None,
    search: str | None = None,
) -> tuple[list[JournalEntry], int]:
    """
    Получить список дневниковых записей с фильтрацией.

    Returns:
        Tuple of (entries, total_count)
    """
    # Базовый запрос
    query = select(JournalEntry)
    count_query = select(func.count()).select_from(JournalEntry)

    # Применяем фильтры
    filters = []
    if start_date:
        filters.append(JournalEntry.entry_date >= start_date)
    if end_date:
        filters.append(JournalEntry.entry_date <= end_date)
    if mood:
        filters.append(JournalEntry.mood == mood)
    if search:
        search_pattern = f"%{search}%"
        filters.append(
            or_(
                JournalEntry.title.ilike(search_pattern),
                JournalEntry.content.ilike(search_pattern),
                JournalEntry.tags.ilike(search_pattern),
            )
        )

    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    # Получаем общее количество
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Получаем записи с пагинацией
    query = query.offset(skip).limit(limit).order_by(JournalEntry.entry_date.desc())
    result = await db.execute(query)

    return list(result.scalars().all()), total


async def create_journal_entry(
    db: AsyncSession, entry: JournalEntryCreate
) -> JournalEntry:
    """Создать новую дневниковую запись"""
    db_entry = JournalEntry(
        title=entry.title,
        content=entry.content,
        entry_date=entry.entry_date,
        mood=entry.mood,
        tags=entry.tags,
    )
    db.add(db_entry)
    await db.commit()
    await db.refresh(db_entry)
    return db_entry


async def update_journal_entry(
    db: AsyncSession, entry_id: int, entry_update: JournalEntryUpdate
) -> JournalEntry | None:
    """Обновить дневниковую запись"""
    db_entry = await get_journal_entry(db, entry_id)
    if not db_entry:
        return None

    update_data = entry_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_entry, field, value)

    await db.commit()
    await db.refresh(db_entry)
    return db_entry


async def delete_journal_entry(db: AsyncSession, entry_id: int) -> bool:
    """Удалить дневниковую запись"""
    db_entry = await get_journal_entry(db, entry_id)
    if not db_entry:
        return False

    await db.delete(db_entry)
    await db.commit()
    return True


async def get_journal_entries_by_date(
    db: AsyncSession, entry_date: date
) -> list[JournalEntry]:
    """Получить все дневниковые записи за конкретную дату"""
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.entry_date == entry_date)
        .order_by(JournalEntry.created_at.desc())
    )
    return list(result.scalars().all())


async def get_day_journal_entry(
    db: AsyncSession, entry_date: date
) -> JournalEntry | None:
    """
    «Запись дня» — та, к которой дописывается пересказ.

    Таблица позволяет несколько записей за дату (исторически), поэтому «запись
    дня» приходится выбирать: берём самую раннюю. Это утренние заметки, к
    которым вечерний текст логично дописать; выбор последней означал бы, что
    дописывание зависит от того, чем закончился день.
    """
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.entry_date == entry_date)
        .order_by(JournalEntry.created_at.asc(), JournalEntry.id.asc())
        .limit(1)
    )
    return result.scalars().first()


def _appended(existing: str, addition: str) -> str:
    return f"{existing}{DAY_JOURNAL_SEPARATOR}{addition}"


async def write_day_journal(
    db: AsyncSession,
    entry_date: date,
    *,
    mode: Literal["append", "create", "replace"],
    title: str | None,
    content: str,
    mood: str | None = None,
    tags: str | None = None,
) -> JournalEntry:
    """
    Записать текст дня, не коммитя: транзакцией владеет вызывающий.

    Принимает поля, а не DTO вызывающей фичи: журнал — нижний слой, и знать про
    план разбора дня ему незачем. Выбор режима (в частности, что делать с
    `create`, когда запись за дату уже есть) остаётся у вызывающего.

    Запись дня резолвится здесь и сейчас, а не берётся из аргумента: между
    предпросмотром и кнопкой день мог обрасти текстом или лишиться его.

    - записи за дату нет -> создаём при любом режиме (иначе текст дня потерялся
      бы из-за того, что заметку успели удалить);
    - запись есть и режим `replace` -> текст заменяется целиком; единственный
      путь, теряющий написанное, и выбирается он только явным действием
      пользователя;
    - запись есть в любом другом режиме -> дописываем.

    Дописывание не трогает заголовок: он про запись целиком, а не про её конец.
    Настроение и теги заполняются только если их не было — перезаписать их
    значило бы молча стереть то, что пользователь проставил руками.
    """
    existing = await get_day_journal_entry(db, entry_date)

    if existing is None:
        created = JournalEntry(
            title=title,
            content=content,
            entry_date=entry_date,
            mood=mood,
            tags=tags,
        )
        db.add(created)
        await db.flush()
        return created

    if mode == "replace":
        existing.content = content
        existing.title = title or existing.title
    else:
        existing.content = _appended(existing.content, content)

    existing.mood = existing.mood or mood
    existing.tags = existing.tags or tags
    await db.flush()
    return existing
