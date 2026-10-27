# [review:need-review] PHASE-03/223
# summary: the tables of supplements — the directory (name, dose, unit, planned time, archived_at), the intake mark unique per supplement per logical day, and the Idempotency-Keys that point at a mark
"""
Supplements the owner takes (`#223`).

**Личные данные — в PostgreSQL, не в RAG.** Название добавки — данные о здоровье;
они лежат в этих двух таблицах и уходят модели только числами и названиями в
промпте на время одного запроса, текст совета не хранится.

**Архив, а не удаление.** `archived_at` вместо `is_active`: по моменту видно,
с какого дня добавка перестала быть в плане. `is_active` — производное свойство.
Ограничение: истории периодов нет. Возврат из архива обнуляет `archived_at`, и
дни перерыва в сводке соблюдения становятся пропусками. Хочешь честный перерыв —
заведи добавку заново.

**Один приём — одна строка на добавку в сутки.** `(supplement_id, intake_date)`
уникален: второе нажатие в тот же логический день ничего не создаёт. День
отметки решает `app.core.daytime`, а не клиент.

**Ключ повтора — алиас отметки.** Каждый `Idempotency-Key`, приходивший с
отметкой, лежит строкой `SupplementIntakeKey` и ведёт на отметку дня, даже если
отметку создал другой ключ: повтор любого из них через сутки вернёт ту же
отметку, а не заведёт новую.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

NAME_MAX_LENGTH = 100
UNIT_MAX_LENGTH = 20
IDEMPOTENCY_KEY_MAX_LENGTH = 255


class Supplement(Base):
    """One thing the owner takes: «магний, 200 мг, вечером»."""

    __tablename__ = "supplements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    dose: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(UNIT_MAX_LENGTH))
    # Планируемое время на часах пользователя; null — «в любое время дня».
    intake_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_active(self) -> bool:
        return self.archived_at is None

    def __repr__(self) -> str:
        return f"<Supplement(id={self.id})>"


class SupplementIntake(Base):
    """The tick «принял» for one supplement on one logical day."""

    __tablename__ = "supplement_intakes"
    __table_args__ = (
        UniqueConstraint(
            "supplement_id", "intake_date", name="uq_supplement_intake_day"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    supplement_id: Mapped[int] = mapped_column(
        ForeignKey("supplements.id", ondelete="CASCADE")
    )
    intake_date: Mapped[date] = mapped_column(Date, index=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<SupplementIntake(id={self.id}, date={self.intake_date})>"


class SupplementIntakeKey(Base):
    """An `Idempotency-Key` that was sent with a mark, and the mark it stands for."""

    __tablename__ = "supplement_intake_keys"

    key: Mapped[str] = mapped_column(
        String(IDEMPOTENCY_KEY_MAX_LENGTH), primary_key=True
    )
    intake_id: Mapped[int] = mapped_column(
        ForeignKey("supplement_intakes.id", ondelete="CASCADE"), index=True
    )
