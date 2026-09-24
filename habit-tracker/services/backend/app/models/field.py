from __future__ import annotations

# [review:need-review] 175, #176
# summary: Field stores optional display units and ordered quick numeric increments

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.entry_value import EntryValue


class FieldType(str, enum.Enum):
    """Field types a user can create."""

    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    SELECT = "select"
    # Elapsed time a user spent (a run, a meditation), stored as whole seconds.
    # Distinct from TIME (a clock time) and DATETIME (a timestamp).
    DURATION = "duration"


class Field(Base):
    """
    Category field model.

    Defines which fields are available for entries of a category.
    For example, a "Sleep" category may have fields:
    - duration (number)
    - quality (select)
    - notes (text)
    """

    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(String(100))
    field_type: Mapped[FieldType] = mapped_column(Enum(FieldType))
    is_required: Mapped[bool] = mapped_column(default=False)
    default_value: Mapped[str | None] = mapped_column(String(255))
    options: Mapped[str | None] = mapped_column(String(500))  # JSON string for select
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quick_steps: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    order: Mapped[int] = mapped_column(default=0)  # Display order

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    category: Mapped[Category] = relationship(
        back_populates="fields", foreign_keys=[category_id]
    )
    entry_values: Mapped[list[EntryValue]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Field(id={self.id}, name='{self.name}', type='{self.field_type}')>"
