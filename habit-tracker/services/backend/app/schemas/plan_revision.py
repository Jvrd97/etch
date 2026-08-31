# [review:need-review] PHASE-03/150
# summary: проводные типы дифа плана — по каждому тронутому пункту поле, старое и новое значение и автор, плюс сводка «человек переставил N пунктов» и номера ревизий, между которыми диф читается
"""
Проводные типы дифа «что предлагала машина против того, что стоит сейчас».

**Старое значение — это то, что было до правки, а не выдумка экрана.** Оно
приезжает строкой журнала, потому что снимок ревизии 0 отвечает на другой вопрос
(«что предлагалось целиком»), а подпись под пунктом — на этот («что тут стояло
до меня»).

**Сводка едет числом, а не считается на экране.** «Человек переставил три
пункта» — свойство журнала, и два места, где его считают, разошлись бы на первом
же удалённом пункте.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.plan_revision import CHANGE_FIELDS, REVISION_AUTHORS


class PlanFieldChange(BaseModel):
    """Одна правка одного поля."""

    field: str = Field(..., description=f"Поле: {' | '.join(CHANGE_FIELDS)}")
    old_value: str | None = Field(
        None, description="Что стояло до правки; null — поле было пустым"
    )
    new_value: str | None = Field(
        None, description="Что стоит после; null — значение сняли"
    )
    author: str = Field(..., description=f"Кто правил: {' | '.join(REVISION_AUTHORS)}")
    revision_from: int | None = Field(
        None, description="Ревизия, поверх которой правка сделана"
    )
    changed_at: datetime


class PlanItemDiff(BaseModel):
    """Один пункт, который человек тронул, со всеми правками по нему."""

    plan_item_id: UUID
    text_md: str = Field(
        "", description="Текст пункта сейчас; пусто — пункт уже удалён"
    )
    changes: list[PlanFieldChange] = Field(default_factory=list)


class PlanDiffResponse(BaseModel):
    """Диф плана дня: что предлагала машина и что человек с этим сделал."""

    day_date: date
    revision_zero: int | None = Field(
        None,
        description=(
            "Номер ревизии-предложения; null — плана на эту дату никто не "
            "генерировал и сравнивать не с чем"
        ),
    )
    revision_zero_author: str | None = Field(
        None, description="Автор предложения: ai — модель, fallback — скелет"
    )
    latest_revision: int | None = Field(
        None, description="Номер последней ревизии этой даты"
    )
    moved_items: int = Field(
        0, description="Сколько пунктов тронул человек — сводка над планом"
    )
    items: list[PlanItemDiff] = Field(default_factory=list)
