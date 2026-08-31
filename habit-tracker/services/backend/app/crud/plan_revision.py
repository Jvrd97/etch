# [review:need-review] PHASE-03/150
# summary: срез ревизии плана и журнал правок — снимок плана целиком в jsonb, нумерация ревизий внутри даты, запись изменения одного поля пункта с ревизией, поверх которой оно сделано, и сборка дифа «что предлагала машина против того, что стоит сейчас»
"""
Ревизии плана и журнал правок человека.

**Снимок, а не ссылки.** Ревизия хранит план целиком в jsonb. Ссылки на строки
`plan_item` дали бы ревизию, которая меняется вместе с планом, — то есть не
ревизию; и удаление пункта стёрло бы память о том, что машина его предлагала.

**Ревизия режется в двух местах и только в них:** при записи плана целиком
(`replace_plan` — это генерация, чья бы она ни была) и при первой отметке дня.
Правка пункта ревизии не режет: она пишет строку журнала.

**Автор правки — только тот, кто её сделал.** Правки, сделанные самой
генерацией, в журнал не идут: `record_change` зовётся из путей правки по одному
пункту, а генерация переписывает документ целиком и режет ревизию.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_time
from app.models.plan import DayPlan, PlanItem
from app.models.plan_revision import (
    AUTHOR_HUMAN,
    PlanItemChange,
    PlanRevision,
)

__all__ = [
    "ChangedItem",
    "PlanDiff",
    "cut_revision",
    "diff_of",
    "latest_revision",
    "list_changes",
    "record_change",
    "revision_zero",
    "snapshot_of",
]


@dataclass(frozen=True)
class ChangedItem:
    """Один пункт, который человек тронул, и что именно он в нём изменил."""

    plan_item_id: uuid.UUID
    text_md: str
    changes: list[PlanItemChange]


@dataclass(frozen=True)
class PlanDiff:
    """Что предлагала машина и что человек с этим сделал."""

    day_date: date
    revision_zero: PlanRevision | None
    latest: PlanRevision | None
    items: list[ChangedItem]

    @property
    def moved_items(self) -> int:
        """Сколько пунктов человек тронул — цифра над планом на экране."""
        return len(self.items)


def _window(value: datetime | None) -> str | None:
    """
    Момент окна как «ЧЧ:ММ» на часах человека.

    Через `local_time`, а не `strftime` по хранимому UTC: окно лежит в таблице
    в UTC, и снимок, напечатавший его сырым, сказал бы про девять утра «07:00».
    """
    return None if value is None else local_time(value).strftime("%H:%M")


def _item_snapshot(item: PlanItem) -> dict[str, Any]:
    """Один пункт в снимке: то, по чему потом читается диф."""
    return {
        "id": str(item.id),
        "parent_id": None if item.parent_id is None else str(item.parent_id),
        "section_id": str(item.section_id),
        "ord": item.ord,
        "kind": item.kind,
        "rigidity": item.rigidity,
        "code": item.code,
        "text_md": item.text_md,
        "window_start": _window(item.starts_at),
        "window_end": _window(item.ends_at),
        "done_criterion": item.done_criterion,
    }


def snapshot_of(plan: DayPlan | None) -> dict[str, Any]:
    """
    План целиком как обычные значения — то, что ложится в `snapshot`.

    План, которого нет, тоже снимок: «на эту дату ничего не предложено» — факт,
    а не отсутствие факта, и ревизия с пустыми секциями читается именно так.
    """
    if plan is None:
        return {"title": None, "sections": []}
    return {
        "title": plan.title,
        "sections": [
            {
                "id": str(section.id),
                "ord": section.ord,
                "kind": section.kind,
                "title": section.title,
                "items": [
                    _item_snapshot(item)
                    for item in sorted(section.items, key=lambda one: one.ord)
                ],
            }
            for section in sorted(plan.sections, key=lambda one: one.ord)
        ],
    }


async def latest_revision(db: AsyncSession, on: date) -> PlanRevision | None:
    """Последняя ревизия плана этой даты, или None, пока ни одной нет."""
    result = await db.execute(
        select(PlanRevision)
        .where(PlanRevision.day_date == on)
        .order_by(PlanRevision.revision.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def revision_zero(db: AsyncSession, on: date) -> PlanRevision | None:
    """Ревизия 0 — то, что было предложено машиной. Не меняется никогда."""
    result = await db.execute(
        select(PlanRevision).where(
            PlanRevision.day_date == on, PlanRevision.revision == 0
        )
    )
    return result.scalar_one_or_none()


async def cut_revision(
    db: AsyncSession,
    on: date,
    plan: DayPlan | None,
    author: str,
    *,
    job_id: uuid.UUID | None = None,
    report_id: uuid.UUID | None = None,
    model: str | None = None,
    prompt_hash: str | None = None,
) -> PlanRevision:
    """
    Записать снимок плана новой ревизией. Прежние ревизии не трогаются.

    Номер — следующий за последним внутри даты; первая ревизия дня получает
    ноль, и это и есть «предложение машины», если срез сделан генерацией.
    """
    last = await latest_revision(db, on)
    revision = PlanRevision(
        day_date=on,
        revision=0 if last is None else last.revision + 1,
        author=author,
        job_id=job_id,
        report_id=report_id,
        model=model,
        prompt_hash=prompt_hash,
        snapshot=snapshot_of(plan),
    )
    db.add(revision)
    await db.flush()
    return revision


async def record_change(
    db: AsyncSession,
    item: PlanItem,
    on: date,
    field: str,
    old_value: str | None,
    new_value: str | None,
    author: str = AUTHOR_HUMAN,
) -> PlanItemChange | None:
    """
    Записать одну правку одного поля — если значение действительно изменилось.

    Правка, не изменившая значения, строки не пишет: журнал, в котором «было
    09:00, стало 09:00», читается как правка, которой не было.
    """
    if old_value == new_value:
        return None
    last = await latest_revision(db, on)
    change = PlanItemChange(
        plan_item_id=item.id,
        day_date=on,
        field=field,
        old_value=old_value,
        new_value=new_value,
        author=author,
        revision_from=None if last is None else last.revision,
    )
    db.add(change)
    await db.flush()
    return change


async def list_changes(db: AsyncSession, on: date) -> list[PlanItemChange]:
    """Все правки этого дня в порядке, в котором они случились."""
    result = await db.execute(
        select(PlanItemChange)
        .where(PlanItemChange.day_date == on)
        .order_by(PlanItemChange.changed_at, PlanItemChange.id)
    )
    return list(result.scalars().all())


async def diff_of(db: AsyncSession, on: date, plan: DayPlan | None) -> PlanDiff:
    """
    Диф дня: по каждому тронутому пункту — поле, старое и новое значение, автор.

    Пункты берутся из плана, каким он стоит сейчас: правка удалённого пункта
    уехала каскадом вместе с ним, а его присутствие в ревизии 0 остаётся.
    """
    changes = await list_changes(db, on)
    by_item: dict[uuid.UUID, list[PlanItemChange]] = {}
    for change in changes:
        by_item.setdefault(change.plan_item_id, []).append(change)

    texts = {
        item.id: item.text_md
        for section in (plan.sections if plan is not None else [])
        for item in section.items
    }
    items = [
        ChangedItem(plan_item_id=item_id, text_md=texts.get(item_id, ""), changes=rows)
        for item_id, rows in by_item.items()
    ]
    items.sort(key=lambda one: one.changes[0].changed_at)
    return PlanDiff(
        day_date=on,
        revision_zero=await revision_zero(db, on),
        latest=await latest_revision(db, on),
        items=items,
    )
