"""
Tests for the estimated half of the day plan: food described, numbers derived.

Every other metric in this feature is read off the retelling — "отжался 30 раз"
carries its own 30. A meal does not. "Съел борщ и котлету" is a complete
statement about the day that contains no number at all, and the whole reason
this slice exists is that typing four numbers per meal is the thing that stops
a food diary from being kept.

So this is the one place where the plan is allowed to produce a number nobody
said, and these tests pin the fence around it: the estimate is marked as an
estimate on the wire, the prompt still forbids inventing numbers everywhere
else, and an estimated metric is written exactly like any other once the user
has approved it — the flag describes where the number came from, not a
different kind of record.
"""

# [review:need-review] PHASE-01/84-voice-day-input
# summary: unit tests for the `estimated` flag on a metric op (default false, parsed, forbidden as an extra key nowhere else), the nutrition prompt rules and the boundary they keep, plus API tests that the flag survives the draft and changes nothing about the apply
import json
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.crud import category as category_crud
from app.llm.daily_summary import DAILY_SUMMARY_SYSTEM_PROMPT, parse_plan
from app.main import app
from app.models import Entry
from app.schemas.daily_summary import LogMetricOp

from tests.test_daily_summary import QueuedLLMClient

ENTRY_DATE = "2026-07-30"
ENTRY_DAY = date(2026, 7, 30)

MEAL = "съел борщ и котлету"


async def _make_nutrition_category(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[int, dict[str, int]]:
    """Create the four-field nutrition category; return (id, field ids by name)."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Питание",
            "description": "Дневной рацион и калории",
            "fields": [
                {"name": "Калории", "field_type": "number", "order": 1},
                {"name": "Белки (г)", "field_type": "number", "order": 2},
                {"name": "Углеводы (г)", "field_type": "number", "order": 3},
                {"name": "Жиры (г)", "field_type": "number", "order": 4},
            ],
        },
    )
    assert response.status_code == 201
    category = await category_crud.get_category(db_session, response.json()["id"])
    assert category is not None
    return category.id, {f.name: f.id for f in category.fields}


def _meal_plan_json(category_id: int, fields: dict[str, int]) -> str:
    """A plan of the shape a described meal produces: four numbers, none said."""
    return json.dumps(
        {
            "metrics": [
                {
                    "op": "log_metric",
                    "category_id": category_id,
                    "field_id": fields["Калории"],
                    "value": 780,
                    "source_text": MEAL,
                    "estimated": True,
                },
                {
                    "op": "log_metric",
                    "category_id": category_id,
                    "field_id": fields["Белки (г)"],
                    "value": 38,
                    "source_text": MEAL,
                    "estimated": True,
                },
            ],
            "unresolved": [],
        }
    )


class TestEstimatedFlagSchema:
    def test_a_metric_is_not_an_estimate_unless_it_says_so(self) -> None:
        """The default has to be "the user said this number".

        Every metric written before this slice existed omits the key, and a
        default of true would relabel all of them as guesses.
        """
        op = LogMetricOp(
            category_id=1, field_id=2, value=30, source_text="отжался 30 раз"
        )
        assert op.estimated is False

    def test_an_estimate_survives_parsing(self) -> None:
        plan = parse_plan(_meal_plan_json(4, {"Калории": 9, "Белки (г)": 10}))
        assert [m.estimated for m in plan.metrics] == [True, True]
        assert plan.metrics[0].value == 780

    def test_the_wording_an_estimate_came_from_is_the_food_itself(self) -> None:
        """There is no number to quote, so `source_text` quotes the meal.

        This is what makes the preview reviewable: four rows all reading "съел
        борщ и котлету" is precisely the honest label for four numbers derived
        from that sentence.
        """
        plan = parse_plan(_meal_plan_json(4, {"Калории": 9, "Белки (г)": 10}))
        assert all(m.source_text == MEAL for m in plan.metrics)


class TestNutritionPromptRules:
    def test_the_prompt_permits_estimating_a_described_meal(self) -> None:
        assert "estimated" in DAILY_SUMMARY_SYSTEM_PROMPT
        assert "portion" in DAILY_SUMMARY_SYSTEM_PROMPT.lower()

    def test_the_estimate_is_confined_to_nutrition_fields(self) -> None:
        """The exception is for food, not a general licence to invent numbers.

        A retelling that says "побегал" must still produce no distance: the
        difference is that a portion of borscht has a knowable calorie count
        and an unspecified run has no knowable length.
        """
        assert "nutrition" in DAILY_SUMMARY_SYSTEM_PROMPT.lower()

    def test_the_no_inventing_rule_still_stands_for_everything_else(self) -> None:
        """The old rule is narrowed by name, not deleted.

        `tests/test_daily_summary.py` asserts this same sentence is present;
        it is repeated here because this slice is the one that could plausibly
        remove it, and removing it is the failure mode worth a test of its own.
        """
        assert "Record only what was actually said" in DAILY_SUMMARY_SYSTEM_PROMPT

    def test_an_estimate_must_be_marked_as_one(self) -> None:
        """A guess that arrives looking like a quote is the thing to prevent."""
        assert "estimated" in DAILY_SUMMARY_SYSTEM_PROMPT
        assert "true" in DAILY_SUMMARY_SYSTEM_PROMPT


@pytest.mark.asyncio
class TestEstimatedMetricsThroughTheAPI:
    async def test_the_draft_hands_the_flag_to_the_client(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The preview cannot label an estimate it was never told about."""
        category_id, fields = await _make_nutrition_category(client, db_session)
        fake = QueuedLLMClient([_meal_plan_json(category_id, fields)])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": MEAL, "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        metrics = response.json()["metrics"]
        assert len(metrics) == 2
        assert all(m["estimated"] is True for m in metrics)

    async def test_an_approved_estimate_is_written_like_any_other_number(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Past the checkbox the flag stops mattering: 780 kcal is 780 kcal.

        Storing the doubt alongside the value was considered and dropped — the
        user already answered the question by ticking the box, and a diary that
        remembers which of its numbers were guesses cannot sum them.
        """
        category_id, fields = await _make_nutrition_category(client, db_session)
        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": category_id,
                        "field_id": fields["Калории"],
                        "value": 780,
                        "source_text": MEAL,
                        "estimated": True,
                    }
                ],
            },
        )

        assert response.status_code == 201
        entry_ids = response.json()["entry_ids"]
        assert len(entry_ids) == 1

        entry = (
            await db_session.execute(select(Entry).where(Entry.id == entry_ids[0]))
        ).scalar_one()
        assert entry.entry_date == ENTRY_DAY
        values = {v.field_id: v.value for v in entry.values}
        assert values[fields["Калории"]] == "780"
