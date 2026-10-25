# [review:need-review] PHASE-03/200
# summary: the one rule of what a plan line may be linked to — an active form category and one of its number, duration or boolean fields, with a target only on a number — answered as a state code the editor, the generator and the reader all share, plus the catalogue of linkable categories the generation prompt is built from
"""
What a line of the plan may be linked to, decided in one place (ADR-0023).

The same question is asked three times and must get the same answer:

* a person links a line in the editor or sends a whole document — a wrong link
  is a 422 naming the line;
* the model proposes a link while building the day — a wrong one is dropped and
  the line stays an ordinary line with «Связать с категорией»;
* the plan is read after the category was archived or its field removed — the
  link is shown with a state, and the fact is refused rather than written into
  whatever field happens to be there.

So the rule is a function from (category, field, target) to a **state code**,
and each of the three callers decides what the code means for it. No session,
no ORM: the callers hand in a catalogue they have already read.

PII: the codes and messages here are built from ids. Category and field names
travel only into the generation prompt, which already carries them for chat.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.models.field import FieldType

# The field types a fact can be typed into from the plan: a count or an amount,
# a span of time, a box. Text and select stay in the category's own form — the
# plan card has no honest input for them.
LINKABLE_FIELD_TYPES: tuple[FieldType, ...] = (
    FieldType.NUMBER,
    FieldType.DURATION,
    FieldType.BOOLEAN,
)

# The field types a target can sit on. «Сходить в зал» has no number to reach.
TARGET_FIELD_TYPES: tuple[FieldType, ...] = (FieldType.NUMBER, FieldType.DURATION)

# A checklist keeps one entry per day (ADR-0007), and a fact typed in the plan is
# an entry of its own: the two would be two answers to "what does this day say".
CHECKLIST_DISPLAY_MODE = "checklist"

LinkState = Literal[
    "ok",
    "category_missing",
    "category_archived",
    "checklist_category",
    "field_missing",
    "field_not_in_category",
    "field_unsupported",
    "target_needs_number",
]
LINK_OK: LinkState = "ok"


@dataclass(frozen=True)
class CatalogField:
    """One field of a category, as much of it as a link needs."""

    id: int
    name: str
    field_type: FieldType
    unit: str | None


@dataclass(frozen=True)
class CatalogCategory:
    """One category with its fields, read once by whoever asks."""

    id: int
    name: str
    is_active: bool
    display_mode: str
    fields: tuple[CatalogField, ...]

    def field(self, field_id: int | None) -> CatalogField | None:
        """The field `field_id` if it is this category's own."""
        return next((one for one in self.fields if one.id == field_id), None)

    @property
    def linkable_fields(self) -> tuple[CatalogField, ...]:
        """The fields a fact can be typed into from the plan."""
        return tuple(
            one for one in self.fields if one.field_type in LINKABLE_FIELD_TYPES
        )


def link_state(
    category: CatalogCategory | None,
    field_id: int | None,
    target_value: float | None,
) -> LinkState:
    """
    Whether a line linked to `category`/`field_id` with `target_value` can take a fact.

    `category` is None when the id named no category at all. The order of the
    checks is the order a person would fix them in: the category first, then
    its field, then the target on that field.
    """
    if category is None:
        return "category_missing"
    if not category.is_active:
        return "category_archived"
    if category.display_mode == CHECKLIST_DISPLAY_MODE:
        return "checklist_category"
    if field_id is None:
        return "field_missing"
    field = category.field(field_id)
    if field is None:
        return "field_not_in_category"
    if field.field_type not in LINKABLE_FIELD_TYPES:
        return "field_unsupported"
    if target_value is not None and field.field_type not in TARGET_FIELD_TYPES:
        return "target_needs_number"
    return LINK_OK


def link_problem(
    category_id: int,
    field_id: int | None,
    state: LinkState,
) -> str:
    """The reason a link in `state` is refused, built from ids alone."""
    reasons: dict[LinkState, str] = {
        "ok": "",
        "category_missing": f"категории {category_id} нет",
        "category_archived": f"категория {category_id} в архиве",
        "checklist_category": (
            f"категория {category_id} — чек-лист: у него одна запись на день, "
            "и факт из плана стал бы второй"
        ),
        "field_missing": f"у пункта с категорией {category_id} не выбрано поле",
        "field_not_in_category": (
            f"поле {field_id} не принадлежит категории {category_id}"
        ),
        "field_unsupported": (
            f"в поле {field_id} из плана не записать: нужно число, "
            "длительность или галочка"
        ),
        "target_needs_number": (
            f"цель ставится только на число или длительность, а поле {field_id} — галочка"
        ),
    }
    return reasons[state]


def catalog_by_id(categories: Iterable[CatalogCategory]) -> dict[int, CatalogCategory]:
    """`{id: category}` — the shape every caller looks links up in."""
    return {category.id: category for category in categories}


def proposable(catalog: Mapping[int, CatalogCategory]) -> list[CatalogCategory]:
    """
    The categories a model may propose: active, not a checklist, with a field.

    Archived and checklist categories are left out of the prompt rather than
    refused after the answer: a model shown only what it may pick has nothing
    to get wrong there.
    """
    return [
        category
        for category in sorted(catalog.values(), key=lambda one: one.id)
        if category.is_active
        and category.display_mode != CHECKLIST_DISPLAY_MODE
        and category.linkable_fields
    ]


def prompt_lines(catalog: Mapping[int, CatalogCategory]) -> str:
    """
    The linkable categories as lines of the generation prompt.

    Ids first, because ids are what the answer has to carry back; names and
    units so that the model can tell «Отжимания» from «Прогулка» at all.
    """
    lines: list[str] = []
    for category in proposable(catalog):
        fields = "; ".join(
            f"field {field.id} «{field.name}» {field.field_type.value}"
            + (f" in {field.unit}" if field.unit else "")
            for field in category.linkable_fields
        )
        lines.append(f"- category {category.id} «{category.name}»: {fields}")
    return "\n".join(lines) if lines else "- none"
