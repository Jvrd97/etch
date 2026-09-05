# [review:need-review] 175
# summary: category update maps invalid explicit primary fields to HTTP 422
from typing import cast, get_args

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import category as category_crud
from app.crud import streak as streak_crud
from app.models import Category, Field
from app.crud.category import (
    CHECKLIST_DISPLAY_MODE,
    CHECKLIST_NEEDS_BOOLEAN_DETAIL,
    PRIMARY_FIELD_ON_CREATE_DETAIL,
    CategoryBatchError,
    PrimaryFieldDoesNotBelongError,
)
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    FieldCreate,
    FieldResponse,
    StreakResponse,
)
from app.schemas.category import (
    CategoryBatchRequest,
    CategoryBatchResponse,
    CategoryStreakMode,
)

router = APIRouter(prefix="/categories", tags=["categories"])

# Single source of truth for the allowed modes: the response Literal itself.
STREAK_MODES: frozenset[str] = frozenset(get_args(CategoryStreakMode))


def _ensure_checklist_has_boolean_field(field_types: list[str]) -> None:
    """Raise 422 when a checklist category would end up with no boolean field."""
    if not category_crud.checklist_has_boolean_field(field_types):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=CHECKLIST_NEEDS_BOOLEAN_DETAIL,
        )


@router.get("", response_model=list[CategoryResponse])
async def get_categories(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[Category]:
    """
    Получить список всех категорий.

    - **skip**: количество пропускаемых записей (для пагинации)
    - **limit**: максимальное количество возвращаемых записей
    - **active_only**: показывать только активные категории
    """
    categories = await category_crud.get_categories(
        db, skip=skip, limit=limit, active_only=active_only
    )
    return categories


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
) -> Category:
    """
    Получить категорию по ID.
    """
    category = await category_crud.get_category(db, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with id {category_id} not found",
        )
    return category


@router.get("/{category_id}/streak", response_model=StreakResponse)
async def get_category_streak(
    category_id: int,
    db: AsyncSession = Depends(get_db),
) -> StreakResponse:
    """
    Получить стрик категории, посчитанный по всей её истории.

    Срыв — день с записью, где boolean-поле true или number-поле > 0.
    День без записи считается чистым. Граница суток — UTC.

    ВАЖНО: до тикета #23 числа считаются только в avoid-семантике —
    расчёт одинаков для любой категории и всегда трактует «есть значение»
    как срыв. Поле `streak_mode` в ответе — эхо колонки категории, оно
    НЕ влияет на current_streak/best_streak/last_relapse_date. Для
    `streak_mode='build'` числа поэтому бессмысленны; их интерпретацию
    (и переключение семантики) добавляет #23. UI обязан скрывать блок
    стрика для build-категорий.
    """
    category = await category_crud.get_category(db, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with id {category_id} not found",
        )

    # The DB column is a plain VARCHAR, so a row written outside this API (fixture,
    # manual SQL, older migration) can hold a mode the response Literal forbids.
    # Rejecting loudly beats casting a value we never checked.
    if category.streak_mode not in STREAK_MODES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category {category_id} has an unknown streak_mode",
        )

    stats = await streak_crud.get_category_streak(db, category_id)
    return StreakResponse(
        category_id=category.id,
        streak_mode=cast(CategoryStreakMode, category.streak_mode),
        current_streak=stats.current_streak,
        best_streak=stats.best_streak,
        last_relapse_date=stats.last_relapse_date,
    )


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    category: CategoryCreate,
    db: AsyncSession = Depends(get_db),
) -> Category:
    """
    Создать новую категорию.

    Можно сразу добавить поля через параметр `fields`.

    Пример:
    ```json
    {
        "name": "Сон",
        "description": "Отслеживание качества сна",
        "color": "#3B82F6",
        "fields": [
            {
                "name": "Продолжительность",
                "field_type": "number",
                "is_required": true
            },
            {
                "name": "Качество",
                "field_type": "select",
                "options": "плохо,средне,отлично"
            }
        ]
    }
    ```
    """
    if category.primary_field_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=PRIMARY_FIELD_ON_CREATE_DETAIL,
        )

    if category.display_mode == CHECKLIST_DISPLAY_MODE:
        _ensure_checklist_has_boolean_field(
            [field.field_type for field in category.fields or []]
        )

    # Проверяем, не существует ли уже категория с таким именем
    existing = await category_crud.get_category_by_name(db, category.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category with name '{category.name}' already exists",
        )

    return await category_crud.create_category(db, category)


@router.post(
    "/batch",
    response_model=CategoryBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_category_batch(
    request: CategoryBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> CategoryBatchResponse:
    """
    Применить план категорий одной транзакцией: всё-или-ничего.

    Generic-ручка: принимает список additive-only операций (`create_category`,
    `add_field`) и применяет их в общем коммите. Падение на любой операции не
    оставляет в БД ни одной записи из плана — частично применённого плана не
    бывает. Возвращает созданное: новые категории и добавленные поля.

    Ошибки: дубль имени (в БД или внутри плана) -> 400; `add_field` в
    несуществующую категорию -> 400; checklist без boolean-поля -> 422 (та же
    проверка, что и в обычном POST /categories).
    """
    try:
        return await category_crud.apply_category_batch(db, request)
    except CategoryBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    category_update: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
) -> Category:
    """
    Обновить категорию.

    Можно обновить только нужные поля.
    """
    if category_update.display_mode == CHECKLIST_DISPLAY_MODE:
        existing = await category_crud.get_category(db, category_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category with id {category_id} not found",
            )
        # Валидируем результирующий набор полей: если PATCH сам переопределяет
        # поля, boolean может добавляться тем же запросом, что и checklist.
        effective_fields = (
            category_update.fields
            if category_update.fields is not None
            else existing.fields
        )
        _ensure_checklist_has_boolean_field(
            [field.field_type for field in effective_fields]
        )

    try:
        category = await category_crud.update_category(db, category_id, category_update)
    except PrimaryFieldDoesNotBelongError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with id {category_id} not found",
        )
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Удалить категорию.

    ⚠️ ВНИМАНИЕ: Это каскадно удалит все поля и записи этой категории!
    """
    success = await category_crud.delete_category(db, category_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with id {category_id} not found",
        )


@router.post(
    "/{category_id}/fields",
    response_model=FieldResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_field_to_category(
    category_id: int,
    field: FieldCreate,
    db: AsyncSession = Depends(get_db),
) -> Field:
    """
    Добавить новое поле к существующей категории.

    Пример:
    ```json
    {
        "name": "Заметки",
        "field_type": "text",
        "is_required": false
    }
    ```
    """
    db_field = await category_crud.add_field_to_category(db, category_id, field)
    if not db_field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with id {category_id} not found",
        )
    return db_field
