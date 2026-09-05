# [review:need-review] 175
# summary: Category stores an optional explicit field for its table column
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry
    from app.models.field import Field


class Category(Base):
    """
    Category model (e.g. Vitamins, Sleep, Meditation).

    Each category has its own user-defined fields.
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(50))
    color: Mapped[str | None] = mapped_column(String(7))  # HEX color, e.g. #FF5733
    is_active: Mapped[bool] = mapped_column(default=True)
    display_mode: Mapped[str] = mapped_column(
        String(20), default="form", server_default="form"
    )
    streak_mode: Mapped[str] = mapped_column(
        String(20), default="build", server_default="build"
    )
    # Явное решение пользователя, показывать ли категорию на Today.
    # NULL — «решай эвристикой» (нет числового поля -> не показываем и т.д.),
    # и это дефолт: иначе каждую новую категорию пришлось бы включать руками,
    # а все заведённые до этой миграции разом исчезли бы с экрана.
    show_in_today: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    primary_field_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "fields.id",
            name="fk_categories_primary_field_id_fields",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    group: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    # order_by — часть контракта, а не украшение: `order` задаёт порядок полей
    # в UI, а без сортировки список приходит в порядке строк таблицы.
    # Перестановка полей меняет только `order` (id сохраняются), поэтому без
    # order_by ответ выглядел бы так, будто ничего не двигали.
    # `Field.id` — тай-брейк: у полей, созданных одним батчем, `order` совпадает.
    fields: Mapped[list[Field]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        foreign_keys="Field.category_id",
        order_by="(Field.order, Field.id)",
    )
    entries: Mapped[list[Entry]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}')>"
