# [review:need-review] PHASE-01/39-server-idempotency-key-entries, PHASE-03/121, PHASE-03/200
# summary: Entry model + nullable unique idempotency_key (server-side create dedup) + ix_entries_category_date, the index every quick mark reads the day's entry through; #200 adds `plan_item_id`, the plan line a fact was typed into (no foreign key, so the plan can be rewritten without touching history)
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.entry_value import EntryValue


class Entry(Base):
    """
    Category entry model.

    One data record for a category, e.g. one sleep record for a date.
    """

    __tablename__ = "entries"
    # The direct price of the quick-mark path (`#121`): every tap looks up the
    # day's entry of a category, and the separate single-column indexes below
    # make that two scans and a merge instead of one lookup.
    __table_args__ = (
        Index("ix_entries_category_date", "category_id", "entry_date"),
        Index(
            "ix_entries_plan_item_id",
            "plan_item_id",
            postgresql_where=text("plan_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )

    entry_date: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    # Client-supplied stable key (e.g. offline outbox PendingEntry.id) used to
    # dedup replayed creates. Nullable: legacy/keyless creates stay unconstrained.
    # Single-user app, so global uniqueness is sufficient (no user scoping yet).
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True
    )

    # Строка плана, в которой этот факт ввели (`#200`, ADR-0023). Без внешнего
    # ключа намеренно, как `plan_mark_event.item_id`: план заменяется целиком —
    # строки удаляются и вставляются заново под тем же id, — и каскад либо
    # стёр бы историю категории, либо потерял бы связь на каждой правке плана.
    # Запись остаётся записью категории; план её читает, но не владеет ею.
    plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    category: Mapped[Category] = relationship(back_populates="entries")
    values: Mapped[list[EntryValue]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Entry(id={self.id}, category_id={self.category_id}, date={self.entry_date})>"
