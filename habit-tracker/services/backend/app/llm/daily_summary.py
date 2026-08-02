# [review:need-review] PHASE-01/84-voice-day-input
# summary: day-text orchestration — id-bearing catalogues for metrics and checklist boxes, prompt (metrics + ticks + the day's Markdown journal + estimated nutrition from a described meal), semantic validation; JSON parse and the repair pass come from app.llm.plan_flow
from __future__ import annotations

from datetime import date

from app.crud.category import CHECKLIST_DISPLAY_MODE
from app.crud.daily_summary import (
    NUMERIC_FIELD_TYPES,
    validate_check_ops,
    validate_metric_ops,
)
from app.llm.client import LLMClient
from app.llm.plan_flow import PlanError, generate_with_repair, parse_json_plan
from app.models.category import Category
from app.models.field import FieldType
from app.schemas.daily_summary import DailySummaryPlan

DAILY_SUMMARY_SYSTEM_PROMPT = """\
You turn a free-text retelling of one day into numeric tracker records.

You emit ONLY a JSON object, no prose, no markdown fences, of the shape:
{
  "metrics": [
    {
      "op": "log_metric",
      "category_id": <id from the catalogue>,
      "field_id": <id of a field of THAT category>,
      "value": <number>,
      "source_text": "<the words this number was read from>",
      "uncertain": false,
      "implausible": false,
      "estimated": false
    }
  ],
  "checklist": [
    {
      "op": "check",
      "category_id": <id from the checklist catalogue>,
      "field_id": <id of a box of THAT category>,
      "source_text": "<the words this tick was read from>",
      "uncertain": false
    }
  ],
  "unresolved": [
    { "text": "<the words>", "reason": "<why it fits no category>" }
  ],
  "journal": {
    "title": "<short title for the day, or null>",
    "content": "<the day written out as Markdown>",
    "mood": null,
    "tags": null
  }
}

Rules:
- Resolve by id only. Names in the catalogue are there so you can understand it;
  they are never part of your answer.
- `field_id` must belong to the `category_id` you paired it with, and its type
  must be numeric — only those fields appear in the catalogue.
- A `duration` field is stored in WHOLE SECONDS, and nothing converts the number
  after you: "40 минут" is `2400`, "1 час 30 минут" is `5400`, "два часа" is
  `7200`. Never send 40 for forty minutes.
- Record only what was actually said. Do not infer a number nobody stated:
  "побегал" is not five kilometres, because an unspecified run has no knowable
  length. Nutrition, spelled out below, is the single exception to this rule.
- NUTRITION IS THAT EXCEPTION. When the retelling names food that was eaten and
  the catalogue offers fields measuring nutrition — calories, protein, fat,
  carbohydrates — estimate those numbers from typical portion sizes and emit
  them as ordinary metrics with `"estimated": true`. "Съел борщ и котлету"
  states nothing numeric and must still produce a calorie count: a meal is
  fully describable without numbers, which is exactly why it gets spoken
  instead of typed. A portion of borscht has a knowable calorie count; an
  unspecified run does not have a knowable length. That is the whole difference.
- Estimate the meal as a whole, one metric per nutrition field, every one of
  them carrying the same `source_text` — the food as it was said. Do not give
  each dish a row of its own: what gets read back later is the day's total.
- Estimate a normal portion when none was stated, and follow the stated one when
  it was ("две тарелки", "полпорции", "200 грамм"). Never round a portion up to
  a number that sounds better than what was described.
- Set `estimated` to true ONLY on a number you derived rather than heard. A
  number the user stated outright — "съел 600 калорий" — is not an estimate,
  however casually it was phrased, and a push-up count is never an estimate at
  all: outside nutrition fields, `estimated` is always false.
- The whole retelling belongs to the date given below, however the user phrased
  it. "вчера", "утром", "в среду" describe when inside that day something
  happened — they never move a metric to another date, and there is no way to
  express one.
- Set `uncertain` to true when you are not confident the metric belongs to that
  category or field. Set `implausible` to true when the number itself looks
  wrong for what it measures.
- Anything numeric that fits no category goes to `unresolved` with the original
  wording. Never invent a category or a field for it — you cannot create either.
- A `checklist` entry ticks one box for the day. Use it only for boxes from the
  checklist catalogue below, and only when the retelling says the thing was
  done. A box is ticked, never unticked: there is no field for `false` and no
  other way to say it, because the user may have ticked a box by hand this
  morning and simply not mentioned it. Not saying something is not saying no.
- Set `uncertain` to true on a tick you are not confident the retelling meant.
- Only recording values exists. There is no way to delete, rename or retype
  anything, so do not try.
- `journal` is the same day written out as Markdown prose for the user to read
  later: short headings and plain sentences, no tables, no JSON inside it. Set
  the whole `journal` to null when the retelling holds nothing worth reading
  back — a bare "отжался 30 раз" is already fully captured by the metric.
- The journal retells; it does not embellish. Every fact in it must be traceable
  to a sentence of the retelling. Do not add a mood, a reason, a conclusion or a
  number that was not said. Something said but implausible is written down as it
  was said and marked as doubtful in the text, not corrected and not dropped.
- Output must be valid JSON and nothing else."""


class DailySummaryPlanError(PlanError):
    """The model output could not be parsed or failed semantic validation."""


def build_catalog(categories: list[Category]) -> str:
    """
    The categories the model may write into, each with the ids it must answer with.

    Only numeric fields are listed: a metric can be written nowhere else, so
    offering the rest would only invite an answer that validation then rejects.
    A category without a numeric field is left out entirely.
    """
    lines: list[str] = []
    for category in categories:
        numeric = [f for f in category.fields if f.field_type in NUMERIC_FIELD_TYPES]
        if not numeric:
            continue
        fields = ", ".join(
            f"field_id={f.id} name={f.name!r} type={f.field_type.value}"
            for f in numeric
        )
        lines.append(
            f"- category_id={category.id} name={category.name!r} fields=[{fields}]"
        )
    return "\n".join(lines) if lines else "(no categories with numeric fields yet)"


def build_checklist_catalog(categories: list[Category]) -> str:
    """
    The boxes the model may tick, each with the ids it must answer with.

    Kept apart from `build_catalog` rather than merged into it, because the two
    are different offers: a numeric field asks "how much", a box asks "did you".
    Only boolean fields of `display_mode='checklist'` categories appear — the
    same pair the apply validates, so anything listed here can actually be
    written and anything writable is listed.
    """
    lines: list[str] = []
    for category in categories:
        if category.display_mode != CHECKLIST_DISPLAY_MODE:
            continue
        boxes = [f for f in category.fields if f.field_type is FieldType.BOOLEAN]
        if not boxes:
            continue
        fields = ", ".join(f"field_id={f.id} name={f.name!r}" for f in boxes)
        lines.append(
            f"- category_id={category.id} name={category.name!r} boxes=[{fields}]"
        )
    return "\n".join(lines) if lines else "(no checklist categories yet)"


def build_prompt(transcript: str, categories: list[Category], entry_date: date) -> str:
    """
    Assemble the day-parsing prompt from the transcript, the catalogue and the date.

    The date is in the prompt for one reason: a retelling says "вчера" and
    "утром" freely, and a model that does not know which day it is reading may
    try to date a metric itself. Stating the day makes those words what they
    actually are — a time of day inside it, not a different date.
    """
    return (
        f"{DAILY_SUMMARY_SYSTEM_PROMPT}\n\n"
        f"## Categories you may write into\n{build_catalog(categories)}\n\n"
        f"## Checklist boxes you may tick\n{build_checklist_catalog(categories)}\n\n"
        f"## The date this day is filed under\n{entry_date.isoformat()}\n\n"
        f"## The day\n{transcript}"
    )


def parse_plan(text: str) -> DailySummaryPlan:
    """Parse the raw model text into a DailySummaryPlan (form validation only)."""
    return parse_json_plan(text, DailySummaryPlan, DailySummaryPlanError)


def validate_plan(plan: DailySummaryPlan, categories: list[Category]) -> None:
    """Semantic check on top of the Pydantic form check; raises with every problem."""
    errors = validate_metric_ops(plan.metrics, categories) + validate_check_ops(
        plan.checklist, categories
    )
    if errors:
        raise DailySummaryPlanError("; ".join(errors))


async def generate_daily_summary_plan(
    llm: LLMClient,
    categories: list[Category],
    transcript: str,
    entry_date: date,
) -> DailySummaryPlan:
    """
    Turn a day's retelling into a validated write-only plan.

    One repair pass, shared with onboarding: a first answer that fails to parse
    or validate is sent back with the reason attached, and a second failure
    raises DailySummaryPlanError, which the endpoint maps to 502.

    The transcript and the raw model output never leave this call chain. Neither
    is logged, and neither is the validation-error text — it is built from ids
    alone precisely so the repair prompt can carry it without carrying the day.
    """

    def parse_and_validate(text: str) -> DailySummaryPlan:
        plan = parse_plan(text)
        validate_plan(plan, categories)
        return plan

    return await generate_with_repair(
        llm, build_prompt(transcript, categories, entry_date), parse_and_validate
    )
