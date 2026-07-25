# [review:need-review] PHASE-01/35-category-fields-update-web-ux
# summary: CategoryUpdate.fields (FieldUpsert with optional id) for field diff-sync
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

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


class FieldCreate(FieldBase):
    """Схема для создания поля"""

    pass


class FieldUpsert(FieldBase):
    """
    Поле в пейлоаде обновления категории.

    Существующие поля несут `id` — по нему бэкенд обновляет строку на месте
    (сохраняя историю в entry_values).

    Поле без `id` сначала пробуют сопоставить с ещё не занятым существующим
    полем по паре (имя без регистра/пробелов, тип); совпало — строка тоже
    обновляется на месте и история цела. Новое поле создаётся только когда
    сопоставить не с чем. Это сопоставление — временный compat-shim для
    клиентов, которые id не присылают (старая сборка фронта на VPS); после
    раскатки нового фронта оно снимается, см. PHASE-01/57.

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
