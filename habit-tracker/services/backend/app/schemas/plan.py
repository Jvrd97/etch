# [review:need-review] PHASE-03/87, PHASE-03/110, PHASE-03/130
# summary: wire types of the plan — the incoming document (nested, order implied by position, windows as "ЧЧ:ММ-ЧЧ:ММ") and the outgoing plan with a schedule and the overlaps found by the database; #110 adds the per-item edit — a patch that tells "not sent" from "set to null", a new line for one section, a move to a place, and the answer that carries the whole plan back with the warnings a human's edit earned
"""
Wire types of the plan.

Three decisions in this file are worth reading before adding a field.

**Order is position, not a number.** Neither a section nor an item carries `ord`
on the way in. The acceptance case is "the order matches the one sent", and a
client-supplied index is one edit away from two sections claiming the same
place — the database would then refuse a plan that looked fine in the editor.
The server numbers what it receives.

**A window arrives as `"23:30-00:30"`, not as two timestamps.** The plan is
written by a human and by `/day-open`, both of whom think in wall clock; a
timestamp would force each of them to know the day boundary and the timezone,
which is exactly the knowledge this system spent `#107` centralising.

**A minimum is a child item, not a field.** `Минимум ::` used to live inside the
text of a training block, and 29 August showed that a minimum without its own
tick does not get done. It comes in as a nested item of `kind='minimum'` and has
a mark of its own since `#88`.

**An item may name the id it already has.** That is how a re-sent plan says "the
same line, different wording" instead of "delete that line and make a new one" —
and it is the only way to say it, because the marks of `#88` hang off the id.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.plan import (
    ITEM_KINDS,
    PLAN_SOURCES,
    PLAN_STATUSES,
    RIGIDITY_VALUES,
    SECTION_KINDS,
)

# Mirrors `plan_item.code`; a longer handle is a 422 on the field rather than a
# truncation nobody notices until the error message points at the wrong line.
MAX_CODE_LENGTH = 64


class PlanItemIn(BaseModel):
    """One line of an incoming plan, with its children."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = Field(
        None,
        description=(
            "Id пункта, если это тот же самый пункт, что уже есть в плане дня. "
            "Тогда пункт сохраняет свои отметки; без id заводится новый пункт. "
            "Id из другого дня или незнакомый — игнорируется, id дважды в одном "
            "документе — отказ"
        ),
    )

    kind: str = Field("bullet", description=f"Одно из: {', '.join(ITEM_KINDS)}")
    rigidity: str = Field(
        "soft",
        description=(
            f"Одно из: {', '.join(RIGIDITY_VALUES)}. `free` — пункт свободного "
            "блока, окна у него быть не может"
        ),
    )

    text_md: str = Field(..., min_length=1)

    window: str | None = Field(
        None,
        description=(
            "Окно как «ЧЧ:ММ-ЧЧ:ММ» по местным часам дня. Конец раньше начала — "
            "окно через полночь, оно разворачивается в +24 ч"
        ),
    )
    window_comment: str | None = Field(
        None, description="Хвост окна, который не время: «пока ногти»"
    )

    code: str | None = Field(
        None,
        max_length=MAX_CODE_LENGTH,
        description="Короткая ручка пункта — `W1`, `подъём`; ею его называют ошибки",
    )
    done_criterion: str | None = Field(
        None, description="Подпись «Сделано ::». У задачи обязательна"
    )
    why_md: str | None = Field(None, description="Подпись «Почему ::»")
    plan_md: str | None = Field(None, description="Подпись «Ход ::»")

    external_ref: dict[str, Any] | None = Field(
        None, description="Подпись «ClickUp ::» и прочие внешние ссылки"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Всё остальное вида «Подпись :: значение» — «Формат», «Вход», "
            "«Материал». Доезжает целиком и читается обратно"
        ),
    )

    quarter_goal_id: int | None = None
    unlinked_reason: str | None = Field(
        None,
        description=(
            "Почему задача не привязана к кварталу. Без неё и без "
            "quarter_goal_id задача не сохраняется"
        ),
    )
    quick_mark_id: int | None = Field(
        None,
        description=(
            "Кнопка справочника, которой этот пункт отмечается. Кнопка встаёт "
            "на Today первой и помечается плановой; её отметка закрывает пункт"
        ),
    )

    carried_from_item_id: UUID | None = None
    carry_count: int = 0
    legacy_key: str | None = None

    children: list[PlanItemIn] = Field(
        default_factory=list,
        description="Вложенные пункты — шаги, «Минимум» отдельной галкой",
    )


class PlanSectionIn(BaseModel):
    """One section of an incoming plan; `ord` is its position in the list."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    kind: str = Field("other", description=f"Одно из: {', '.join(SECTION_KINDS)}")
    items: list[PlanItemIn] = Field(default_factory=list)


class PlanDocument(BaseModel):
    """
    A whole plan, as `/day-open` sends it.

    Whole rather than incremental: a second `POST` on the same date replaces
    everything, which is what keeps "the plan" a single object a human can read
    top to bottom instead of a pile of edits whose order nobody recorded.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    title_marker: str | None = Field(
        None, description="Слово, которым помечен заголовок: «без работы»"
    )
    lede: str | None = None
    purpose_md: str | None = Field(None, description="«Ради чего» этого дня")
    quarter_goal_id: int | None = None
    counters: list[Any] = Field(
        default_factory=list, description="Счётчики шапки: «0 = рабочих задач»"
    )
    condition_tomorrow: str | None = None
    status: str = Field("active", description=f"Одно из: {', '.join(PLAN_STATUSES)}")
    source: str = Field("day-open", description=f"Одно из: {', '.join(PLAN_SOURCES)}")
    raw_md: str | None = Field(
        None, description="Исходный markdown, если план приехал из файла"
    )
    sections: list[PlanSectionIn] = Field(default_factory=list)


class PlanItemResponse(BaseModel):
    """One line of a stored plan, with its children nested under it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    ord: int
    kind: str
    rigidity: str
    text_md: str
    text_plain: str
    starts_at: datetime | None
    ends_at: datetime | None
    window_comment: str | None
    code: str | None
    done_criterion: str | None
    why_md: str | None
    plan_md: str | None
    external_ref: dict[str, Any] | None
    extra: dict[str, Any]
    quarter_goal_id: int | None
    unlinked_reason: str | None
    quick_mark_id: int | None
    carried_from_item_id: UUID | None
    carry_count: int
    children: list[PlanItemResponse] = Field(default_factory=list)


class PlanSectionResponse(BaseModel):
    """One section of a stored plan."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ord: int
    title: str | None
    kind: str
    items: list[PlanItemResponse] = Field(default_factory=list)


class ScheduleEntry(BaseModel):
    """
    One line of the day's schedule: an item that claimed a piece of the clock.

    Duration comes from the server rather than from a subtraction in the
    browser. `23:30-00:30` is sixty minutes only if whoever subtracts knows the
    day boundary, and the browser does not.
    """

    item_id: UUID
    section_id: UUID
    code: str | None
    text_plain: str
    kind: str
    rigidity: str
    starts_at: datetime
    ends_at: datetime
    minutes: int
    window_comment: str | None


class ScheduleOverlap(BaseModel):
    """
    Two items whose windows intersect, as the database found them.

    Found by a self-join on `&&` over the GiST index on the generated `window`
    column, not by comparing every pair on render: an overlap is a fact about
    the stored plan, and the screen that shows it must not be the only place
    that knows about it.
    """

    left_item_id: UUID
    right_item_id: UUID
    overlap_minutes: int


class PlanResponse(BaseModel):
    """A stored plan: its head, its sections, its schedule and its collisions."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    day_date: date
    title: str | None
    title_marker: str | None
    lede: str | None
    purpose_md: str | None
    quarter_goal_id: int | None
    counters: list[Any]
    condition_tomorrow: str | None
    status: str
    source: str
    needs_review: bool = Field(
        False,
        description=(
            "План собран ночным прогоном-страховкой и человеком не смотрен. "
            "Снимается первой правкой пункта или первой отметкой дня"
        ),
    )
    fallback_reason: str | None = Field(
        None,
        description=(
            "Почему план собран скелетом: llm_timeout, llm_error, "
            "llm_not_configured, llm_plan_invalid. null у всего остального"
        ),
    )
    created_at: datetime
    updated_at: datetime
    sections: list[PlanSectionResponse] = Field(default_factory=list)
    schedule: list[ScheduleEntry] = Field(default_factory=list)
    overlaps: list[ScheduleOverlap] = Field(default_factory=list)


class PlanRejection(BaseModel):
    """
    The body of a 422 — the rule that was broken and the line that broke it.

    Declared as a schema rather than left to FastAPI's default so that
    `/day-open` can act on it: `item_code` is what the agent deletes, and a
    generic "validation error" would send it back to re-read a document it just
    wrote.
    """

    error: str = Field(..., description="Машинный код нарушения: too_many_tasks")
    message: str = Field(..., description="Человеческая формулировка правила")
    item_code: str | None = Field(None, description="Код пункта, который нарушил")
    item_text: str | None = Field(None, description="Его текст, если кода нет")


class PlanItemPatch(BaseModel):
    """
    Правка одного пункта: только присланные поля, остальные не трогаются.

    Разница между «поле не прислали» и «поле обнулили» здесь несущая, и держится
    она на `model_fields_set` pydantic, а не на сторожевом значении: `null` в
    теле — это «убрать критерий», отсутствие ключа — «не трогать критерий», и
    склеить их значило бы стирать половину пункта на каждой правке слова.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str | None = Field(None, description=f"Одно из: {', '.join(ITEM_KINDS)}")
    rigidity: str | None = Field(
        None, description=f"Одно из: {', '.join(RIGIDITY_VALUES)}"
    )
    text_md: str | None = Field(None, min_length=1)
    window: str | None = Field(
        None, description="Окно как «ЧЧ:ММ-ЧЧ:ММ»; `null` — снять окно"
    )
    window_comment: str | None = None
    code: str | None = Field(None, max_length=MAX_CODE_LENGTH)
    done_criterion: str | None = None
    why_md: str | None = None
    plan_md: str | None = None
    external_ref: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None
    quarter_goal_id: int | None = None
    unlinked_reason: str | None = None
    quick_mark_id: int | None = None


class PlanItemCreate(BaseModel):
    """
    Новый пункт в секцию. Позиция не приходит: пункт встаёт в конец уровня.

    Позиция в теле создания была бы третьим местом, где решается порядок, — есть
    приём плана документом и есть перенос; вставка в середину делается созданием
    и переносом, и это две понятные операции вместо одной с сюрпризом.
    """

    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = Field(
        None, description="Родительский пункт: шаг задачи, «Минимум» тренировки"
    )
    kind: str = Field("bullet", description=f"Одно из: {', '.join(ITEM_KINDS)}")
    rigidity: str = Field("soft", description=f"Одно из: {', '.join(RIGIDITY_VALUES)}")
    text_md: str = Field(..., min_length=1)
    window: str | None = None
    window_comment: str | None = None
    code: str | None = Field(None, max_length=MAX_CODE_LENGTH)
    done_criterion: str | None = None
    why_md: str | None = None
    plan_md: str | None = None
    external_ref: dict[str, Any] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    quarter_goal_id: int | None = None
    unlinked_reason: str | None = None
    quick_mark_id: int | None = None


class PlanItemMove(BaseModel):
    """
    Перенос пункта: куда и на какое место.

    Отдельная операция, а не поле `ord` в патче: перетаскивание меняет порядок
    сразу нескольких строк, и построчная запись `ord` на середине оставила бы
    план с дырами и дублями.
    """

    model_config = ConfigDict(extra="forbid")

    section_id: UUID = Field(
        ..., description="Секция назначения; та же — перенос внутри"
    )
    parent_id: UUID | None = Field(
        None, description="Родитель назначения; `null` — верхний уровень секции"
    )
    position: int = Field(
        ..., ge=0, description="Место среди братьев; больше длины — в конец"
    )


class PlanEditResponse(BaseModel):
    """
    Ответ любой правки пункта: план целиком, тронутый пункт и предупреждения.

    План целиком, потому что правка одного пункта меняет порядок соседей,
    расписание и пересечения окон; отдать один пункт значило бы заставить экран
    перечитывать день вторым запросом ради того, что сервер уже знает.

    `warnings` — правила, которые машине запретили бы запись, а человеку не
    запрещают. Пустой список — правка ничего не нарушила.
    """

    plan: PlanResponse
    item: PlanItemResponse | None = Field(
        None, description="Тронутый пункт; `null` после удаления"
    )
    warnings: list[PlanRejection] = Field(default_factory=list)


PlanItemIn.model_rebuild()
PlanItemResponse.model_rebuild()
