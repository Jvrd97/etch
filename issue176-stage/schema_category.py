# [review:need-review] 175, #176
# summary: category schemas expose primary fields plus validated field units and quick steps
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Annotated, Literal, Union

CategoryDisplayMode = Literal["form", "checklist"]
CategoryStreakMode = Literal["build", "avoid"]

# Hex colour #RRGGBB — shared by category and onboarding-plan schemas.
COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class FieldBase(BaseModel):
    """Базовая схема для поля"""

    name: str = Field(..., min_length=1, max_length=100)
    field_type: str = Field(
        ...,
        description=(
            "Тип поля: text, number, boolean, date, datetime, time, select, "
            "duration (затраченное время в секундах)"
        ),
    )
    is_required: bool = False
    default_value: str | None = None
    options: str | None = None  # JSON строка для select типа
    order: int = 0
    unit: str | None = Field(None, max_length=50)
    quick_steps: list[float] | None = None

    @field_validator("quick_steps")
    @classmethod
    def validate_quick_steps(cls, value: list[float] | None) -> list[float] | None:
        import math

        if value is not None and any(
            step == 0 or not math.isfinite(step) for step in value
        ):
            raise ValueError("quick_steps must contain only finite non-zero numbers")
        return value


class FieldCreate(FieldBase):
    """Схема для создания поля"""

    pass


class FieldUpsert(FieldBase):
    """
    Поле в пейлоаде обновления категории.

    Существующие поля несут `id` — по нему бэкенд обновляет строку на месте
    (сохраняя историю в entry_values). Поле без `id` всегда создаётся как новое.

    Поля, отсутствующие в списке, удаляются вместе со своей историей.
    """

    id: int | None = None


class FieldUpdate(BaseModel):
    """Схема для обновления поля"""

    name: str | None = Field(None, min_length=1, max_length=100)
    field_type: str | None = None
    is_required: bool | None = None
    default_value: str | None = None
    options: str | None = None
    order: int | None = None
    unit: str | None = Field(None, max_length=50)
    quick_steps: list[float] | None = None


class FieldResponse(FieldBase):
    """Схема ответа для поля"""

    id: int
    category_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CategoryBase(BaseModel):
    """Базовая схема для категории"""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=7, pattern=COLOR_PATTERN)
    display_mode: CategoryDisplayMode = "form"
    streak_mode: CategoryStreakMode = "build"
    group: str | None = Field(None, max_length=100)
    show_in_today: bool | None = Field(
        None,
        description=(
            "Показывать ли категорию на Today. None — решает эвристика "
            "(есть числовое поле, не avoid, не чек-лист); true/false — явный "
            "выбор пользователя, который эвристику перекрывает."
        ),
    )
    primary_field_id: int | None = None


class CategoryCreate(CategoryBase):
    """
    Схема для создания категории.
    Поля создаются отдельно или вместе с категорией.
    """

    fields: list[FieldCreate] | None = []


class CategoryUpdate(BaseModel):
    """Схема для обновления категории"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=7, pattern=COLOR_PATTERN)
    is_active: bool | None = None
    display_mode: CategoryDisplayMode | None = None
    streak_mode: CategoryStreakMode | None = None
    group: str | None = Field(None, max_length=100)
    # Тройственное поле, поэтому здесь важен exclude_unset, а не `is None`:
    # присланный явно `null` возвращает категорию под эвристику, а не значит
    # «не трогай». Ровно это и делает update_category, патчащий по exclude_unset.
    show_in_today: bool | None = None
    primary_field_id: int | None = None
    # None (поле не прислано) — поля не трогаем. Список (в т.ч. пустой) —
    # полный desired-state: синхронизируем существующие/новые/удалённые.
    fields: list[FieldUpsert] | None = None


class CategoryResponse(CategoryBase):
    """Схема ответа для категории"""

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    fields: list[FieldResponse] = []

    class Config:
        from_attributes = True


class BatchCreateCategoryOp(CategoryBase):
    """Создать новую категорию (вместе с полями) в рамках batch-плана."""

    op: Literal["create_category"] = "create_category"
    fields: list[FieldCreate] = Field(default_factory=list)


class BatchAddFieldOp(BaseModel):
    """Добавить поле к существующей категории в рамках batch-плана."""

    op: Literal["add_field"] = "add_field"
    category_id: int
    field: FieldCreate


# Generic список операций: ручка про онбординг ничего не знает, только про
# домен категорий. Дискриминатор `op` разводит два additive-only варианта.
CategoryBatchOperation = Annotated[
    Union[BatchCreateCategoryOp, BatchAddFieldOp], Field(discriminator="op")
]


class CategoryBatchRequest(BaseModel):
    """Список операций, применяемых одной транзакцией (всё-или-ничего)."""

    operations: list[CategoryBatchOperation] = Field(default_factory=list)


class CategoryBatchResponse(BaseModel):
    """Созданное планом: новые категории и добавленные к существующим поля."""

    categories: list[CategoryResponse] = []
    fields: list[FieldResponse] = []
