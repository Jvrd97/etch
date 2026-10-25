"""
Generation proposes links to existing categories and nothing else (`#200`).

The model is shown the categories a line may be linked to — ids, names, fields,
units — and may answer a line with `category_id`/`field_id`/`target_value`.
What comes back is checked against the same catalogue: a link to a category
that does not exist, to a field of another category, to an archived or a
checklist category, or a target on a box is dropped, and the line stays an
ordinary line the person can link by hand. Generation writes no entry and does
not change a single category.
"""

# [review:need-review] PHASE-03/200
# summary: the generator and category links — the catalogue in the prompt (active form categories only), every proposed id checked and a wrong one dropped rather than refused, and a generated plan that links lines while writing no entry and changing no category
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.crud import day as day_crud
from app.day import skeleton
from app.day.plan_links import CatalogCategory, CatalogField, catalog_by_id
from app.llm import day_plan as day_plan_llm
from app.main import app
from app.models import Entry, FieldType
from app.schemas.day_plan import GeneratedDayPlan, GeneratedItem, GeneratedSection
from app.schemas.day_plan import to_document
from tests.test_day_constraints import WORKDAY, rule
from tests.test_day_plan_generation import QueuedLLMClient, _skeleton_as_model_answer
from tests.test_plan_facts import field_id, make_category

DAY_URL = "/api/v1/day"

PUSHUPS = CatalogCategory(
    id=1,
    name="Отжимания",
    is_active=True,
    display_mode="form",
    fields=(
        CatalogField(id=11, name="Повторения", field_type=FieldType.NUMBER, unit="раз"),
    ),
)
GYM = CatalogCategory(
    id=2,
    name="Спортзал",
    is_active=True,
    display_mode="form",
    fields=(
        CatalogField(id=21, name="Посетил", field_type=FieldType.BOOLEAN, unit=None),
    ),
)
ARCHIVED = CatalogCategory(
    id=3,
    name="Старое",
    is_active=False,
    display_mode="form",
    fields=(CatalogField(id=31, name="Раз", field_type=FieldType.NUMBER, unit=None),),
)
CHECKLIST = CatalogCategory(
    id=4,
    name="Витамины",
    is_active=True,
    display_mode="checklist",
    fields=(CatalogField(id=41, name="D3", field_type=FieldType.BOOLEAN, unit=None),),
)
CATALOG = catalog_by_id([PUSHUPS, GYM, ARCHIVED, CHECKLIST])


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The canon row the generated day is judged by."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


def one_line_plan(**link: Any) -> GeneratedDayPlan:
    """A model answer of one line carrying `link`."""
    return GeneratedDayPlan(
        title="день",
        sections=[
            GeneratedSection(
                title="Вечер",
                kind="evening",
                items=[GeneratedItem(code="P1", text="Отжимания", **link)],
            )
        ],
    )


def stored_link(plan: GeneratedDayPlan) -> tuple[int | None, int | None, float | None]:
    """The link the document would store for the only line."""
    item = to_document(plan, "llm", catalog=CATALOG).sections[0].items[0]
    return item.category_id, item.field_id, item.target_value


class TestThePrompt:
    def test_the_prompt_lists_linkable_categories_by_id(self) -> None:
        prompt = day_plan_llm.build_prompt(
            WORKDAY, rule(), skeleton.Signals(), catalog=CATALOG
        )
        assert "category 1 «Отжимания»" in prompt
        assert "field 11 «Повторения» number in раз" in prompt
        assert "category 2 «Спортзал»" in prompt
        # Shown only what may be picked: nothing archived, no checklist.
        assert "category 3" not in prompt
        assert "category 4" not in prompt

    def test_without_a_catalogue_the_prompt_says_none(self) -> None:
        prompt = day_plan_llm.build_prompt(WORKDAY, rule(), skeleton.Signals())
        assert "category 1" not in prompt


class TestProposedIdsAreChecked:
    def test_a_valid_link_and_target_are_kept(self) -> None:
        assert stored_link(
            one_line_plan(category_id=1, field_id=11, target_value=300)
        ) == (1, 11, 300)

    @pytest.mark.parametrize(
        "link",
        [
            {"category_id": 99, "field_id": 11},
            {"category_id": 1, "field_id": 21},
            {"category_id": 1, "field_id": None},
            {"category_id": 2, "field_id": 21, "target_value": 1},
            {"category_id": 3, "field_id": 31},
            {"category_id": 4, "field_id": 41},
            {"category_id": None, "field_id": 11},
        ],
        ids=[
            "unknown category",
            "field of another category",
            "no field",
            "target on a box",
            "archived category",
            "checklist category",
            "field without category",
        ],
    )
    def test_a_wrong_link_leaves_an_ordinary_line(self, link: dict[str, Any]) -> None:
        assert stored_link(one_line_plan(**link)) == (None, None, None)

    def test_no_catalogue_means_no_link(self) -> None:
        plan = one_line_plan(category_id=1, field_id=11)
        item = to_document(plan, "llm").sections[0].items[0]
        assert item.category_id is None


async def test_a_generated_plan_links_lines_and_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    pushups = await make_category(
        client,
        "Отжимания",
        [{"name": "Повторения", "field_type": "number", "order": 1, "unit": "раз"}],
    )
    before = (await client.get(f"/api/v1/categories/{pushups['id']}")).json()
    answer = json.loads(
        _skeleton_as_model_answer(skeleton.skeleton_plan(WORKDAY, rule()))
    )
    lines = [item for section in answer["sections"] for item in section["items"]]
    lines[0].update(
        category_id=pushups["id"], field_id=field_id(pushups), target_value=300
    )
    lines[1].update(category_id=pushups["id"], field_id=999_999)

    app.dependency_overrides[get_llm_client] = lambda: QueuedLLMClient(
        [json.dumps(answer)]
    )
    try:
        response = await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan/generate")
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 201, response.text
    assert response.json()["source"] == "llm"
    stored = [
        item for section in response.json()["sections"] for item in section["items"]
    ]
    by_code = {item["code"]: item for item in stored}
    first, second = by_code[lines[0]["code"]], by_code[lines[1]["code"]]
    assert (first["category_id"], first["field_id"], first["target_value"]) == (
        pushups["id"],
        field_id(pushups),
        300,
    )
    assert (second["category_id"], second["field_id"]) == (None, None)
    entries = await db_session.scalar(select(func.count()).select_from(Entry))
    assert entries == 0
    after = (await client.get(f"/api/v1/categories/{pushups['id']}")).json()
    assert after["fields"] == before["fields"]
