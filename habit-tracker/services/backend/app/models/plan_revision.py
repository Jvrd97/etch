# [review:need-review] PHASE-03/150
# summary: `plan_revision` — снимок плана целиком с автором и происхождением (ревизия 0 = предложение машины), и `plan_item_change` — журнал правок человека по одному полю за строку, с ревизией, поверх которой правка сделана
"""
Что предложила машина и что человек переставил.

**Связка теряется сегодня целиком.** `/day-open` пишет `.md`, человек правит тот
же `.md`, и предложение исчезает под правкой в тот же день. Вопрос «чем плох
генератор» после этого отвечать нечем: сравнивать не с чем.

**Ревизия 0 — предложение, а не первая версия человека.** Снимок пишется той же
транзакцией, что и план, при каждой генерации — и моделью, и скелетом. Автор
`fallback` на скелете нужен ровно для того, чтобы диф работал и без модели.

**Ревизия режется на двух событиях и только на них:** новая генерация и первая
отметка дня. Второе — момент, когда день начался и план перестал быть
предложением. Ревизия на каждое нажатие клавиши делает историю нечитаемой и
отвергнута ADR-0015.

**Правки идут журналом, а не ревизиями.** Десять правок подряд — десять строк
`plan_item_change` и ноль новых ревизий. `revision_from` называет ревизию,
поверх которой правка сделана, — иначе «переставил до начала дня» и «переставил
в обед» неотличимы.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.checks import in_list

# Кто автор этой версии плана. `ai` — модель, `fallback` — скелет, собранный без
# модели, `human` — человек, `skill` — внешний скилл через API. Четыре слова, а
# не флаг «машина/человек»: «скелет» и «модель» отличаются именно тем, насколько
# плану можно верить, и это первое, что спросят у накопленных дифов.
AUTHOR_AI = "ai"
AUTHOR_FALLBACK = "fallback"
AUTHOR_HUMAN = "human"
AUTHOR_SKILL = "skill"
REVISION_AUTHORS: tuple[str, ...] = (
    AUTHOR_AI,
    AUTHOR_FALLBACK,
    AUTHOR_HUMAN,
    AUTHOR_SKILL,
)

# Поля, изменение которых журналируется. Ровно те, по которым видно, что человек
# переставил: время, текст, место в плане и появление пункта. Всё остальное —
# критерий готовности, ссылка на цель — правится редко и в дифе не спрашивается.
FIELD_WINDOW_START = "window_start"
FIELD_WINDOW_END = "window_end"
FIELD_TEXT = "text"
FIELD_ORD = "ord"
FIELD_SECTION_ID = "section_id"
FIELD_STATUS = "status"
CHANGE_FIELDS: tuple[str, ...] = (
    FIELD_WINDOW_START,
    FIELD_WINDOW_END,
    FIELD_TEXT,
    FIELD_ORD,
    FIELD_SECTION_ID,
    FIELD_STATUS,
)

AUTHOR_LENGTH = 8
FIELD_LENGTH = 16
# `claude-opus-4-6` и подобное. Пусто, пока плана от модели не бывает.
MODEL_LENGTH = 64
HASH_LENGTH = 64


class PlanRevision(Base):
    """Снимок плана одного дня целиком, каким он был на момент среза."""

    __tablename__ = "plan_revision"
    __table_args__ = (
        CheckConstraint(
            in_list("author", REVISION_AUTHORS), name="ck_plan_revision_author"
        ),
        UniqueConstraint("day_date", "revision", name="uq_plan_revision_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Без внешнего ключа на `day`, по той же причине, что и `plan_violation`:
    # генератор режет ревизию на дату, у которой строки дня может ещё не быть.
    day_date: Mapped[date_type] = mapped_column(Date, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    author: Mapped[str] = mapped_column(String(AUTHOR_LENGTH))

    # Задача, породившая эту ревизию. Без внешнего ключа: таблицы задач
    # (`day_job`, `#95`/`#149`) в этой ветке ещё нет, а колонка нужна сейчас —
    # так же, как `plan_violation.job_id` был заведён вперёд своей таблицы.
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Отчёт дня, из которого вырос план. Внешний ключ настоящий: `day_report`
    # приехал в `#145` и лежит в этой же базе.
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("day_report.id", ondelete="SET NULL"),
        nullable=True,
    )
    model: Mapped[str | None] = mapped_column(String(MODEL_LENGTH), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(HASH_LENGTH), nullable=True)

    # План целиком: секции, пункты, окна, коды. Снимок, а не ссылки на строки, —
    # ровно затем, чтобы удаление пункта не стирало память о том, что он был
    # предложен.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PlanRevision(day_date={self.day_date}, revision={self.revision})>"


class PlanItemChange(Base):
    """Одна правка одного поля одного пункта, сделанная человеком."""

    __tablename__ = "plan_item_change"
    __table_args__ = (
        CheckConstraint(
            in_list("field", CHANGE_FIELDS), name="ck_plan_item_change_field"
        ),
        CheckConstraint(
            in_list("author", REVISION_AUTHORS), name="ck_plan_item_change_author"
        ),
        Index("ix_plan_item_change_day", "day_date", "changed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Каскад намеренный: запись об изменении пункта, которого больше нет ни в
    # одном плане, — не факт ни о чём. Память о том, что пункт предлагался,
    # держит снимок ревизии, и он переживает удаление.
    plan_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_item.id", ondelete="CASCADE"), index=True
    )
    day_date: Mapped[date_type] = mapped_column(Date)

    field: Mapped[str] = mapped_column(String(FIELD_LENGTH))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str] = mapped_column(String(AUTHOR_LENGTH))
    # Ревизия, поверх которой правка сделана. NULL — плана без единой ревизии
    # не бывает, но правка может прийти на день, импортированный до `#150`.
    revision_from: Mapped[int | None] = mapped_column(Integer, nullable=True)

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PlanItemChange(field='{self.field}', day_date={self.day_date})>"
