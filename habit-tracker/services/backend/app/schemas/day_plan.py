# [review:need-review] PHASE-03/148
# summary: the JSON a model is allowed to answer with — sections, lines, windows, kind and rigidity, each line carrying the short code the repair prompt names it by — plus its two conversions: into the draft the eight constraints judge, and into the document the one writing path accepts
"""
План дня, каким его возвращает модель.

**Модель возвращает данные, а не действия.** Ни файлов, ни правок — JSON по
этой схеме. Форму проверяет Pydantic, смысл — восемь ограничений из `#147`,
запись — тот же `replace_plan`, что принимает план человека. Между моделью и
базой нет ни одного пути, которого не было бы у людей.

**У каждой строки есть код.** `W1`, `подъём` — это ручка, которой строку
называют ошибки. Без неё ремонтный промпт вынужден цитировать текст пункта, а
текст пункта — личный: задача бывает названа диагнозом.

**Окно — стенные часы.** `«07:00-08:00»` в поясе канона, ровно та форма, что
уже читается принимающим путём. Модель не считает ни UTC, ни границу суток.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.day.constraints import DraftItem, PlanDraft
from app.models.day import DayRuleSet
from app.models.plan import ITEM_KINDS, RIGIDITY_VALUES, SECTION_KINDS
from app.schemas.plan import PlanDocument, PlanItemIn, PlanSectionIn

# Пространство имён, в котором код строки превращается в устойчивый id.
# Детерминированно на цель: `check_all` называет нарушителей идентификаторами,
# ремонтный промпт переводит их обратно в коды, и случайный uuid разорвал бы
# эту дорогу на каждом заходе.
ITEM_NAMESPACE = uuid.UUID("6b1f0a9c-3d52-4f0e-9c7a-2e8b5d1a4c60")

WINDOW_SEPARATOR = "-"
WINDOW_FORMAT = "%H:%M"


class GeneratedItem(BaseModel):
    """Одна строка плана, как её пишет модель."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Короткая ручка строки: W1, подъём. Ею её называют ошибки",
    )
    kind: str = Field("bullet", description=f"Одно из: {', '.join(ITEM_KINDS)}")
    rigidity: str = Field("soft", description=f"Одно из: {', '.join(RIGIDITY_VALUES)}")
    text: str = Field(..., min_length=1, description="Что человек прочитает в строке")
    window: str | None = Field(
        None,
        description="«ЧЧ:ММ-ЧЧ:ММ» по стенным часам канона; у пункта без времени — null",
    )
    done_criterion: str | None = Field(
        None, description="«Сделано ::». У задачи обязателен"
    )
    unlinked_reason: str | None = Field(
        None, description="Почему задача не привязана к цели квартала"
    )

    @property
    def item_id(self) -> uuid.UUID:
        """Устойчивый идентификатор строки, посчитанный из её кода."""
        return uuid.uuid5(ITEM_NAMESPACE, self.code)


class GeneratedSection(BaseModel):
    """Секция плана: заголовок, вид и её строки."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    kind: str = Field("other", description=f"Одно из: {', '.join(SECTION_KINDS)}")
    items: list[GeneratedItem] = Field(default_factory=list)


class GeneratedDayPlan(BaseModel):
    """Весь ответ модели: план дня целиком."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    sections: list[GeneratedSection] = Field(default_factory=list)

    def codes(self) -> dict[str, str]:
        """`{id строки: её код}` — словарь, которым читается ответ проверок."""
        return {
            str(item.item_id): item.code
            for section in self.sections
            for item in section.items
        }


def _parse_window(
    window: str | None, target: date, rule: DayRuleSet
) -> tuple[datetime | None, datetime | None]:
    """
    Окно строки как два момента, или пара `None`.

    Конец раньше начала — это окно через полночь, и оно разворачивается в
    +24 часа: та же трактовка, что у принимающего пути, а не вторая.
    Неразобранное окно — это отсутствие окна, а не отказ: строку без времени
    ограничения судят по её виду, и падать на форме здесь означало бы отдать
    в скелет план, у которого испорчена одна строка из двадцати.
    """
    if window is None:
        return None, None
    parts = window.split(WINDOW_SEPARATOR)
    if len(parts) != 2:
        return None, None
    try:
        start = time.fromisoformat(parts[0].strip())
        end = time.fromisoformat(parts[1].strip())
    except ValueError:
        return None, None

    zone = ZoneInfo(rule.timezone)
    starts_at = datetime.combine(target, start, tzinfo=zone)
    ends_at = datetime.combine(target, end, tzinfo=zone)
    if ends_at < starts_at:
        ends_at += timedelta(days=1)
    return starts_at, ends_at


def to_draft(plan: GeneratedDayPlan, target: date, rule: DayRuleSet) -> PlanDraft:
    """
    Ответ модели в той форме, которую судят восемь ограничений.

    Ни текста, ни заголовков: `DraftItem` их не носит намеренно, и правило,
    построившее сообщение из текста строки, тем самым вынесло бы личный текст в
    `plan_violation` и в промпт.
    """
    items: list[DraftItem] = []
    for section in plan.sections:
        for item in section.items:
            starts_at, ends_at = _parse_window(item.window, target, rule)
            items.append(
                DraftItem(
                    item_id=item.item_id,
                    kind=item.kind,
                    rigidity=item.rigidity,
                    code=item.code,
                    section_kind=section.kind,
                    day_date=target,
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
            )
    return PlanDraft(target=target, items=tuple(items))


def to_document(plan: GeneratedDayPlan, source: str) -> PlanDocument:
    """
    Ответ модели как документ, который принимает `POST /day/{date}/plan`.

    Один путь записи, а не два: сгенерированный план проходит ту же проверку,
    ту же выдачу идентификаторов и тот же перенос отметок, что и план,
    присланный человеком.
    """
    sections: list[PlanSectionIn] = []
    for section in plan.sections:
        sections.append(
            PlanSectionIn(
                title=section.title,
                kind=section.kind,
                items=[
                    PlanItemIn(
                        kind=item.kind,
                        rigidity=item.rigidity,
                        text_md=item.text,
                        window=item.window,
                        code=item.code,
                        done_criterion=item.done_criterion,
                        unlinked_reason=item.unlinked_reason,
                    )
                    for item in section.items
                ],
            )
        )
    return PlanDocument(title=plan.title, source=source, sections=sections)
