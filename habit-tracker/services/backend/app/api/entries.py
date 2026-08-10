# [review:need-review] PHASE-01/73-dashboard-hero-today-ring
# summary: GET /entries takes `sort` (entry_date_desc default, created_at_desc for "last written"); POST still honours Idempotency-Key
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import category as category_crud
from app.crud import entry as entry_crud
from app.crud.category import CHECKLIST_DISPLAY_MODE
from app.models import Entry
from app.schemas import (
    ChecklistUpsertRequest,
    EntryCreate,
    EntrySort,
    EntryUpdate,
    EntryResponse,
)

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("", response_model=list[EntryResponse])
async def get_entries(
    skip: int = 0,
    limit: int = 100,
    category_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    sort: EntrySort = EntrySort.ENTRY_DATE_DESC,
    db: AsyncSession = Depends(get_db),
) -> list[Entry]:
    """
    Получить список записей с фильтрацией.

    - **skip**: количество пропускаемых записей
    - **limit**: максимальное количество записей
    - **category_id**: фильтр по категории
    - **start_date**: начальная дата (формат: YYYY-MM-DD)
    - **end_date**: конечная дата (формат: YYYY-MM-DD)
    - **sort**: `entry_date_desc` (по умолчанию, дата события) либо
      `created_at_desc` (время сохранения — «что записано последним»)

    Примеры:
    - `/api/v1/entries?category_id=1` - все записи для категории 1
    - `/api/v1/entries?start_date=2024-01-01&end_date=2024-01-31` - записи за январь
    - `/api/v1/entries?sort=created_at_desc&limit=1` - последняя сохранённая запись
    """
    entries = await entry_crud.get_entries(
        db,
        skip=skip,
        limit=limit,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        sort=sort,
    )
    return entries


@router.put("/checklist", response_model=EntryResponse)
async def upsert_checklist_entry(
    payload: ChecklistUpsertRequest,
    db: AsyncSession = Depends(get_db),
) -> Entry:
    """
    Идемпотентный upsert записи checklist-категории.

    Повторный PUT для той же (category_id, entry_date) обновляет
    существующую запись — дубликатов не создаётся.

    - **404** — категория не найдена
    - **422** — категория существует, но её display_mode не "checklist"
    """
    category = await category_crud.get_category(db, payload.category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with id {payload.category_id} not found",
        )
    if category.display_mode != CHECKLIST_DISPLAY_MODE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Category {payload.category_id} is not a checklist category "
                f"(display_mode={category.display_mode})"
            ),
        )
    return await entry_crud.upsert_checklist_entry(
        db, payload.category_id, payload.entry_date, payload.values
    )


@router.get("/{entry_id}", response_model=EntryResponse)
async def get_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
) -> Entry:
    """
    Получить запись по ID.
    """
    entry = await entry_crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entry with id {entry_id} not found",
        )
    return entry


@router.post("", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    entry: EntryCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Entry:
    """
    Создать новую запись.

    Если передан заголовок `Idempotency-Key`, повторный запрос с тем же ключом
    возвращает ранее созданную запись (HTTP 200) вместо создания дубля. Это
    закрывает окно offline-очереди, где ack мог потеряться после успешного
    create на сервере. Первое создание отвечает 201, повтор — 200.

    Семантика ключа — "первый победил": ключ идентифицирует запись, а не payload.
    Повтор с тем же ключом, но иным телом, возвращает ИСХОДНУЮ запись, а новые
    данные молча отбрасываются (сервер не сравнивает и не обновляет payload). Это
    безопасно для outbox-реплеев, где ключ = стабильный `PendingEntry.id`, а тело
    для одного pending-entry неизменно.

    Пример для категории "Сон" с полями "Продолжительность" и "Качество":
    ```json
    {
        "category_id": 1,
        "entry_date": "2024-01-15",
        "notes": "Хорошо выспался",
        "values": [
            {
                "field_id": 1,
                "value": "8"
            },
            {
                "field_id": 2,
                "value": "отлично"
            }
        ]
    }
    ```
    """
    if idempotency_key is not None:
        existing = await entry_crud.get_entry_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return existing
        try:
            return await entry_crud.create_entry(db, entry, idempotency_key)
        except IntegrityError:
            # Concurrent replay won the race between lookup and insert; the
            # unique constraint is the backstop. Re-read and return the winner.
            await db.rollback()
            winner = await entry_crud.get_entry_by_idempotency_key(db, idempotency_key)
            if winner is None:
                raise
            response.status_code = status.HTTP_200_OK
            return winner

    return await entry_crud.create_entry(db, entry)


@router.patch("/{entry_id}", response_model=EntryResponse)
async def update_entry(
    entry_id: int,
    entry_update: EntryUpdate,
    db: AsyncSession = Depends(get_db),
) -> Entry:
    """
    Обновить запись.

    Можно обновить дату, заметки или значения полей.
    """
    entry = await entry_crud.update_entry(db, entry_id, entry_update)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entry with id {entry_id} not found",
        )
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Удалить запись.

    Каскадно удаляет все значения полей.
    """
    success = await entry_crud.delete_entry(db, entry_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entry with id {entry_id} not found",
        )


@router.get("/category/{category_id}/range", response_model=list[EntryResponse])
async def get_entries_by_date_range(
    category_id: int,
    start_date: date = Query(..., description="Начальная дата (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Конечная дата (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> list[Entry]:
    """
    Получить все записи категории за указанный период.

    Полезно для построения графиков и аналитики.

    Пример: `/api/v1/entries/category/1/range?start_date=2024-01-01&end_date=2024-01-31`
    """
    entries = await entry_crud.get_entries_by_date_range(
        db, category_id, start_date, end_date
    )
    return entries
