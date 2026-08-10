# [review:need-review] PHASE-01/73-dashboard-hero-today-ring
# summary: added EntrySort — the ordering vocabulary of GET /entries (event date vs write time)
from enum import Enum

from pydantic import BaseModel
from datetime import datetime, date


class EntrySort(str, Enum):
    """
    Порядок выдачи `GET /entries`.

    Два порядка — это два разных вопроса. `entry_date_desc` отвечает «что
    происходило позже» и остаётся значением по умолчанию, чтобы существующие
    вызовы не поменяли выдачу. `created_at_desc` отвечает «что записано
    последним»: дашборду нужна именно последняя сохранённая запись, а она может
    быть датирована вчера, если день заносят вечером.

    Направление зашито в само значение: сортировка по возрастанию ни одному
    экрану не нужна, а отдельный параметр `order` завёл бы четыре комбинации,
    из которых осмысленны две.
    """

    ENTRY_DATE_DESC = "entry_date_desc"
    CREATED_AT_DESC = "created_at_desc"


class EntryValueCreate(BaseModel):
    """Схема для создания значения поля"""

    field_id: int
    value: str | None = None


class EntryValueResponse(BaseModel):
    """Схема ответа для значения поля"""

    id: int
    entry_id: int
    field_id: int
    value: str | None

    class Config:
        from_attributes = True


class EntryBase(BaseModel):
    """Базовая схема для записи"""

    entry_date: date
    notes: str | None = None


class EntryCreate(EntryBase):
    """
    Схема для создания записи.

    values - словарь {field_id: value} или список объектов EntryValueCreate
    """

    category_id: int
    values: list[EntryValueCreate] = []


class EntryUpdate(BaseModel):
    """Схема для обновления записи"""

    entry_date: date | None = None
    notes: str | None = None
    values: list[EntryValueCreate] | None = None


class ChecklistUpsertRequest(BaseModel):
    """
    Схема идемпотентного upsert для checklist-категории.

    values — словарь {field_id: bool}: какие чек-поля выставить/снять.
    """

    category_id: int
    entry_date: date
    values: dict[int, bool]


class EntryResponse(EntryBase):
    """Схема ответа для записи"""

    id: int
    category_id: int
    created_at: datetime
    updated_at: datetime
    values: list[EntryValueResponse] = []

    class Config:
        from_attributes = True


class EntryWithCategoryResponse(EntryResponse):
    """Расширенная схема ответа с информацией о категории"""

    category_name: str
    category_color: str | None = None
