# [review:need-review] PHASE-01/63-today-card-tap-and-visibility
# summary: + show_in_today (tri-state: NULL = decide by heuristic, true/false = user override)
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text
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
    group: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    fields: Mapped[list[Field]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )
    entries: Mapped[list[Entry]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}')>"
