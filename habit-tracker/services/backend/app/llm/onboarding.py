# [review:need-review] PHASE-01/52-text-to-category-plan
# summary: onboarding orchestration — prompt (with existing categories), semantic validation, conflict flags; JSON parse and the repair pass come from app.llm.plan_flow
from __future__ import annotations

from app.crud.category import CHECKLIST_DISPLAY_MODE, checklist_has_boolean_field
from app.llm.client import LLMClient
from app.llm.plan_flow import PlanError, generate_with_repair, parse_json_plan
from app.models.category import Category
from app.models.field import FieldType
from app.schemas.onboarding import (
    AddFieldOp,
    CreateCategoryOp,
    OnboardingPlan,
    PlanField,
)

# Valid field-type strings, straight from the domain enum.
VALID_FIELD_TYPES: frozenset[str] = frozenset(ft.value for ft in FieldType)

ONBOARDING_SYSTEM_PROMPT = """\
You design a habit-tracker structure from a free-text description.

You emit ONLY a JSON object, no prose, no markdown fences, of the shape:
{
  "operations": [
    {
      "op": "create_category",
      "name": "<short name>",
      "description": "<optional>",
      "icon": "<optional short label>",
      "color": "#RRGGBB (optional)",
      "display_mode": "form" | "checklist",
      "streak_mode": "build" | "avoid",
      "group": "<optional group name>",
      "fields": [
        {
          "name": "<field name>",
          "field_type": "text|number|boolean|date|datetime|time|select|duration",
          "is_required": false,
          "options": "<comma-separated, only for select>",
          "order": 0
        }
      ]
    },
    {
      "op": "add_field",
      "category_id": <id of an existing category>,
      "field": { ...same shape as a field above... }
    }
  ]
}

Rules:
- Only these two operations exist. You cannot delete, rename, retype or
  deactivate anything — do not try.
- Extend the existing system: if the user's intent fits an existing category,
  emit `add_field` for that category's id instead of a second create_category.
- A `checklist` category MUST include at least one `boolean` field.
- Reuse the naming conventions and groups you see in the existing categories.
- Output must be valid JSON and nothing else."""


class OnboardingPlanError(PlanError):
    """The model output could not be parsed or failed semantic validation."""


def _describe_categories(categories: list[Category]) -> str:
    """Compact, log-safe rendering of existing categories for the prompt."""
    if not categories:
        return "(none yet)"
    lines: list[str] = []
    for category in categories:
        field_desc = ", ".join(
            f"{f.name}:{f.field_type.value}" for f in category.fields
        )
        lines.append(
            f"- id={category.id} name={category.name!r} "
            f"group={category.group!r} display_mode={category.display_mode} "
            f"streak_mode={category.streak_mode} fields=[{field_desc}]"
        )
    return "\n".join(lines)


def build_prompt(transcript: str, categories: list[Category]) -> str:
    """Assemble the full onboarding prompt from the transcript and context."""
    return (
        f"{ONBOARDING_SYSTEM_PROMPT}\n\n"
        f"## Existing categories\n{_describe_categories(categories)}\n\n"
        f"## User description\n{transcript}"
    )


def parse_plan(text: str) -> OnboardingPlan:
    """Parse the raw model text into an OnboardingPlan (form validation only)."""
    return parse_json_plan(text, OnboardingPlan, OnboardingPlanError)


def _validate_field(field: PlanField, errors: list[str]) -> None:
    if field.field_type not in VALID_FIELD_TYPES:
        errors.append(
            f"unknown field_type {field.field_type!r} for field {field.name!r}"
        )


def validate_plan(plan: OnboardingPlan, categories: list[Category]) -> None:
    """
    Semantic validation on top of the Pydantic form check.

    Raises OnboardingPlanError describing every problem found, so a single
    repair pass can address them all at once.
    """
    existing_ids = {c.id for c in categories}
    existing_field_names: dict[int, set[str]] = {
        c.id: {f.name.strip().casefold() for f in c.fields} for c in categories
    }
    errors: list[str] = []

    for op in plan.operations:
        if isinstance(op, CreateCategoryOp):
            for field in op.fields:
                _validate_field(field, errors)
            if op.display_mode == CHECKLIST_DISPLAY_MODE:
                if not checklist_has_boolean_field([f.field_type for f in op.fields]):
                    errors.append(
                        f"checklist category {op.name!r} needs a boolean field"
                    )
        elif isinstance(op, AddFieldOp):
            _validate_field(op.field, errors)
            if op.category_id not in existing_ids:
                errors.append(f"add_field targets unknown category_id {op.category_id}")
            else:
                name_key = op.field.name.strip().casefold()
                if name_key in existing_field_names[op.category_id]:
                    errors.append(
                        f"field {op.field.name!r} already exists in "
                        f"category_id {op.category_id}"
                    )

    if errors:
        raise OnboardingPlanError("; ".join(errors))


def annotate_conflicts(plan: OnboardingPlan, categories: list[Category]) -> None:
    """Flag every create_category whose name collides with an existing one."""
    existing_names = {c.name.strip().casefold() for c in categories}
    for op in plan.operations:
        if isinstance(op, CreateCategoryOp):
            op.name_conflict = op.name.strip().casefold() in existing_names


async def generate_onboarding_plan(
    llm: LLMClient, categories: list[Category], transcript: str
) -> OnboardingPlan:
    """
    Turn a transcript into a validated additive-only plan.

    One repair pass, shared with the day summary: if the first answer fails to
    parse or validate, the model is asked once more with the failure reason
    attached. A second failure raises OnboardingPlanError (the endpoint maps
    that to 502).

    The transcript and the raw model output never leave this call chain — they
    are never logged, and neither is the validation-error text (it can echo
    transcript content back).
    """

    def parse_and_validate(text: str) -> OnboardingPlan:
        plan = parse_plan(text)
        validate_plan(plan, categories)
        return plan

    plan = await generate_with_repair(
        llm, build_prompt(transcript, categories), parse_and_validate
    )
    annotate_conflicts(plan, categories)
    return plan
