# [review:need-review] PHASE-01/57-drop-field-identity-fallback
# summary: _sync_category_fields matches fields by id only (identity fallback dropped)
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Category, Field
from app.models.field import FieldType
from app.schemas import CategoryCreate, CategoryUpdate, FieldCreate
from app.schemas.category import (
    BatchAddFieldOp,
    BatchCreateCategoryOp,
    CategoryBatchRequest,
    CategoryBatchResponse,
    CategoryResponse,
    FieldResponse,
    FieldUpsert,
)

logger = logging.getLogger(__name__)

BOOLEAN_FIELD_TYPE = "boolean"

CHECKLIST_DISPLAY_MODE = "checklist"


class CategoryBatchError(Exception):
    """Плановая операция отвергнута; несёт HTTP-статус и текст для API-слоя.

    Транзакционность батча — причина существования этого исключения: любой
    отказ откатывает уже накопленные во flush изменения, поэтому частично
    применённого плана не бывает.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def checklist_has_boolean_field(field_types: list[str]) -> bool:
    """A checklist category needs at least one boolean field to tick off."""
    return BOOLEAN_FIELD_TYPE in field_types


def _apply_field(current: Field, item: FieldUpsert) -> None:
    """Обновить существующее поле на месте (id сохраняется → история цела)."""
    current.name = item.name
    current.field_type = FieldType(item.field_type)
    current.is_required = item.is_required
    current.default_value = item.default_value
    current.options = item.options
    current.order = item.order


async def _sync_category_fields(
    db: AsyncSession, db_category: Category, fields: list[FieldUpsert]
) -> None:
    """
    Привести поля категории к желаемому состоянию `fields`.

    Сопоставление входного элемента с существующим полем — исключительно по
    `id`: совпал — поле обновляется на месте (история в entry_values цела).
    Элемент без `id` (или с `id`, которого нет в категории) всегда создаётся
    как новое поле.

    Существующее поле, которого нет в желаемом состоянии, удаляется каскадно
    вместе со своей историей — это единственный сценарий потери значений, и он
    явный (поле убрали из списка). Каждое такое удаление пишется в лог `warning`
    по id (имена полей — пользовательские данные).
    """
    existing_by_id = {f.id: f for f in db_category.fields}
    seen_ids: set[int] = set()

    for item in fields:
        current = existing_by_id.get(item.id) if item.id is not None else None
        if current is None:
            db.add(
                Field(
                    category_id=db_category.id,
                    name=item.name,
                    field_type=item.field_type,
                    is_required=item.is_required,
                    default_value=item.default_value,
                    options=item.options,
                    order=item.order,
                )
            )
            continue
        _apply_field(current, item)
        seen_ids.add(current.id)

    for field_id, field in existing_by_id.items():
        if field_id not in seen_ids:
            # Cascades the field's entry_values away. Field names are user data,
            # so only ids go to the log.
            logger.warning(
                "dropping field not present in the desired state, "
                "its entry_values cascade away: category_id=%s field_id=%s",
                db_category.id,
                field_id,
            )
            await db.delete(field)


async def get_category(db: AsyncSession, category_id: int) -> Category | None:
    """Получить категорию по ID с полями"""
    result = await db.execute(
        select(Category)
        .options(selectinload(Category.fields))
        .where(Category.id == category_id)
    )
    return result.scalar_one_or_none()


async def get_category_by_name(db: AsyncSession, name: str) -> Category | None:
    """Получить категорию по имени"""
    result = await db.execute(
        select(Category)
        .options(selectinload(Category.fields))
        .where(Category.name == name)
    )
    return result.scalar_one_or_none()


async def get_categories(
    db: AsyncSession, skip: int = 0, limit: int | None = 100, active_only: bool = True
) -> list[Category]:
    """Получить список категорий; limit=None отключает пагинацию"""
    query = select(Category).options(selectinload(Category.fields))

    if active_only:
        query = query.where(Category.is_active.is_(True))

    query = query.offset(skip).order_by(Category.name)
    if limit is not None:
        query = query.limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_category(db: AsyncSession, category: CategoryCreate) -> Category:
    """
    Создать новую категорию с полями.

    Если переданы поля (fields), они создаются вместе с категорией.
    """
    # Создаём категорию
    db_category = Category(
        name=category.name,
        description=category.description,
        icon=category.icon,
        color=category.color,
        display_mode=category.display_mode,
        streak_mode=category.streak_mode,
        group=category.group,
    )
    db.add(db_category)
    await db.flush()  # Получаем ID категории

    # Создаём поля, если они переданы
    if category.fields:
        for field_data in category.fields:
            db_field = Field(
                category_id=db_category.id,
                name=field_data.name,
                field_type=field_data.field_type,
                is_required=field_data.is_required,
                default_value=field_data.default_value,
                options=field_data.options,
                order=field_data.order,
            )
            db.add(db_field)

    await db.commit()
    await db.refresh(db_category)

    # Загружаем поля
    result = await db.execute(
        select(Category)
        .options(selectinload(Category.fields))
        .where(Category.id == db_category.id)
    )
    return result.scalar_one()


async def update_category(
    db: AsyncSession, category_id: int, category_update: CategoryUpdate
) -> Category | None:
    """
    Обновить категорию.

    Скалярные поля патчатся по exclude_unset. Если прислан `fields`, он
    трактуется как желаемое состояние набора полей и синхронизируется по id:
    существующие обновляются на месте (история сохраняется), новые создаются,
    отсутствующие удаляются. Если `fields` не прислан — поля не трогаем.
    """
    db_category = await get_category(db, category_id)
    if not db_category:
        return None

    # fields патчим отдельно: setattr на relationship списком dict сломал бы ORM.
    scalar_data = category_update.model_dump(exclude_unset=True, exclude={"fields"})
    for field, value in scalar_data.items():
        setattr(db_category, field, value)

    if category_update.fields is not None:
        await _sync_category_fields(db, db_category, category_update.fields)

    await db.commit()
    await db.refresh(db_category)

    # Загружаем поля
    result = await db.execute(
        select(Category)
        .options(selectinload(Category.fields))
        .where(Category.id == db_category.id)
    )
    return result.scalar_one()


async def delete_category(db: AsyncSession, category_id: int) -> bool:
    """Удалить категорию (каскадно удаляет поля и записи)"""
    db_category = await get_category(db, category_id)
    if not db_category:
        return False

    await db.delete(db_category)
    await db.commit()
    return True


CHECKLIST_NEEDS_BOOLEAN_DETAIL = (
    "display_mode='checklist' requires at least one field with "
    "field_type='boolean'; add a boolean field or keep display_mode='form'"
)


def _build_field(category_id: int, field: FieldCreate) -> Field:
    return Field(
        category_id=category_id,
        name=field.name,
        field_type=field.field_type,
        is_required=field.is_required,
        default_value=field.default_value,
        options=field.options,
        order=field.order,
    )


async def _apply_create_category(
    db: AsyncSession, op: BatchCreateCategoryOp, seen_names: set[str]
) -> int:
    """Создать категорию с полями внутри батч-транзакции; вернуть её id.

    Валидации те же, что у одиночного POST /categories: checklist без boolean
    отвергается 422, дубль имени (в БД или внутри самого плана) — 400. Ничего
    не коммитит: только flush, чтобы получить id.
    """
    if op.display_mode == CHECKLIST_DISPLAY_MODE and not checklist_has_boolean_field(
        [field.field_type for field in op.fields]
    ):
        raise CategoryBatchError(422, CHECKLIST_NEEDS_BOOLEAN_DETAIL)

    if op.name in seen_names or await get_category_by_name(db, op.name) is not None:
        raise CategoryBatchError(400, f"Category with name '{op.name}' already exists")
    seen_names.add(op.name)

    db_category = Category(
        name=op.name,
        description=op.description,
        icon=op.icon,
        color=op.color,
        display_mode=op.display_mode,
        streak_mode=op.streak_mode,
        group=op.group,
    )
    db.add(db_category)
    await db.flush()

    for field in op.fields:
        db.add(_build_field(db_category.id, field))
    await db.flush()
    return db_category.id


async def _apply_add_field(db: AsyncSession, op: BatchAddFieldOp) -> int:
    """Добавить поле к существующей категории; вернуть id нового поля."""
    category = await get_category(db, op.category_id)
    if category is None:
        raise CategoryBatchError(400, f"Category with id {op.category_id} not found")
    db_field = _build_field(op.category_id, op.field)
    db.add(db_field)
    await db.flush()
    return db_field.id


async def apply_category_batch(
    db: AsyncSession, request: CategoryBatchRequest
) -> CategoryBatchResponse:
    """Применить план категорий одной транзакцией: всё-или-ничего.

    Пять отдельных POST /categories дают ровно ту проблему, от которой уходим:
    падение на любой операции здесь откатывает весь план, частичного результата
    не остаётся. На успехе коммитит и возвращает созданное.
    """
    created_category_ids: list[int] = []
    created_field_ids: list[int] = []
    seen_names: set[str] = set()

    try:
        for op in request.operations:
            if isinstance(op, BatchCreateCategoryOp):
                created_category_ids.append(
                    await _apply_create_category(db, op, seen_names)
                )
            else:
                created_field_ids.append(await _apply_add_field(db, op))
        await db.commit()
    except CategoryBatchError:
        # Откат обязателен: flush уже записал строки в транзакцию, а session,
        # прокинутая из override_get_db в тестах, сама по себе не откатывается.
        await db.rollback()
        raise

    categories: list[CategoryResponse] = []
    for category_id in created_category_ids:
        db_category = await get_category(db, category_id)
        if db_category is not None:
            categories.append(CategoryResponse.model_validate(db_category))

    fields: list[FieldResponse] = []
    if created_field_ids:
        result = await db.execute(select(Field).where(Field.id.in_(created_field_ids)))
        fields = [
            FieldResponse.model_validate(field) for field in result.scalars().all()
        ]

    return CategoryBatchResponse(categories=categories, fields=fields)


async def add_field_to_category(
    db: AsyncSession, category_id: int, field: FieldCreate
) -> Field | None:
    """Добавить поле к категории"""
    db_category = await get_category(db, category_id)
    if not db_category:
        return None

    db_field = Field(
        category_id=category_id,
        name=field.name,
        field_type=field.field_type,
        is_required=field.is_required,
        default_value=field.default_value,
        options=field.options,
        order=field.order,
    )
    db.add(db_field)
    await db.commit()
    await db.refresh(db_field)
    return db_field
