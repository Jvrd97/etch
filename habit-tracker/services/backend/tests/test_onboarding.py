"""
Tests for the text -> additive-only category plan (POST /api/v1/onboarding/draft)
and its parsing/validation service.
"""

# [review:need-review] PHASE-01/52-text-to-category-plan
# summary: unit tests for parse/validate/conflict + API tests (503/200/repair/502/conflict/no-transcript-in-logs), mocked at get_llm_client
import json
import logging

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.onboarding import get_llm_client
from app.core.config import settings
from app.crud import category as category_crud
from app.llm.client import LLMClient, LLMError
from app.llm.onboarding import (
    OnboardingPlanError,
    annotate_conflicts,
    generate_onboarding_plan,
    parse_plan,
    validate_plan,
)
from app.main import app
from app.schemas.onboarding import AddFieldOp, CreateCategoryOp, OnboardingPlan


class QueuedLLMClient(LLMClient):
    """Fake LLM: returns queued responses in order, recording every prompt."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("QueuedLLMClient ran out of responses")
        return self._responses.pop(0)


def _create_category_json(name: str = "Сон", field_type: str = "number") -> str:
    return json.dumps(
        {
            "operations": [
                {
                    "op": "create_category",
                    "name": name,
                    "fields": [{"name": "Часы", "field_type": field_type, "order": 1}],
                }
            ]
        }
    )


# --------------------------------------------------------------------------- #
# Pure parsing / validation units
# --------------------------------------------------------------------------- #


class TestParsePlan:
    def test_parses_bare_json_object(self) -> None:
        plan = parse_plan(_create_category_json())
        assert len(plan.operations) == 1
        op = plan.operations[0]
        assert isinstance(op, CreateCategoryOp)
        assert op.name == "Сон"

    def test_extracts_json_from_markdown_fence_and_prose(self) -> None:
        wrapped = (
            "Here is the plan you asked for:\n```json\n"
            + _create_category_json()
            + "\n```\nHope it helps!"
        )
        plan = parse_plan(wrapped)
        assert isinstance(plan.operations[0], CreateCategoryOp)

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(OnboardingPlanError):
            parse_plan("this is not json at all")

    def test_broken_json_object_raises(self) -> None:
        with pytest.raises(OnboardingPlanError):
            parse_plan('{"operations": [ {"op": "create_category" ')


class TestValidatePlan:
    def test_unknown_field_type_raises(self) -> None:
        plan = parse_plan(_create_category_json(field_type="rainbow"))
        with pytest.raises(OnboardingPlanError, match="unknown field_type"):
            validate_plan(plan, [])

    def test_checklist_without_boolean_raises(self) -> None:
        payload = json.dumps(
            {
                "operations": [
                    {
                        "op": "create_category",
                        "name": "Утро",
                        "display_mode": "checklist",
                        "fields": [
                            {"name": "Заметка", "field_type": "text", "order": 1}
                        ],
                    }
                ]
            }
        )
        plan = parse_plan(payload)
        with pytest.raises(OnboardingPlanError, match="boolean"):
            validate_plan(plan, [])

    def test_add_field_unknown_category_raises(self) -> None:
        payload = json.dumps(
            {
                "operations": [
                    {
                        "op": "add_field",
                        "category_id": 999,
                        "field": {"name": "Пульс", "field_type": "number"},
                    }
                ]
            }
        )
        plan = parse_plan(payload)
        with pytest.raises(OnboardingPlanError, match="unknown category_id"):
            validate_plan(plan, [])

    def test_valid_plan_passes(self) -> None:
        plan = parse_plan(_create_category_json())
        validate_plan(plan, [])  # no raise


class TestAnnotateConflicts:
    def test_flags_only_names_that_exist(self) -> None:
        plan = OnboardingPlan(
            operations=[
                CreateCategoryOp(name="Спорт"),
                CreateCategoryOp(name="Медитация"),
            ]
        )

        class _Cat:
            def __init__(self, name: str) -> None:
                self.id = 1
                self.name = name
                self.group = None
                self.display_mode = "form"
                self.streak_mode = "build"
                self.fields: list[object] = []

        # _Cat is a structural stand-in for Category (only the attrs
        # annotate_conflicts reads); the ORM model needs a DB session to build.
        annotate_conflicts(plan, [_Cat("Спорт")])  # type: ignore[list-item]
        first, second = plan.operations
        assert isinstance(first, CreateCategoryOp) and first.name_conflict is True
        assert isinstance(second, CreateCategoryOp) and second.name_conflict is False


# --------------------------------------------------------------------------- #
# Service orchestration + existing-category context (needs a DB)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
class TestExistingCategoryContext:
    async def test_prompt_lists_existing_categories_and_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Existing categories (names + fields) are fed into the prompt."""
        await client.post(
            "/api/v1/categories",
            json={
                "name": "Спорт",
                "fields": [{"name": "Пульс", "field_type": "number", "order": 1}],
            },
        )
        categories = await category_crud.get_categories(db_session, limit=None)

        add_field = categories[0].id
        fake = QueuedLLMClient(
            [
                json.dumps(
                    {
                        "operations": [
                            {
                                "op": "add_field",
                                "category_id": add_field,
                                "field": {"name": "Дистанция", "field_type": "number"},
                            }
                        ]
                    }
                )
            ]
        )

        plan = await generate_onboarding_plan(
            fake, categories, "в спорт добавь дистанцию"
        )

        assert "Спорт" in fake.prompts[0]
        assert "Пульс" in fake.prompts[0]
        assert isinstance(plan.operations[0], AddFieldOp)
        assert plan.operations[0].category_id == add_field


# --------------------------------------------------------------------------- #
# API endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
class TestOnboardingDraftEndpoint:
    async def test_returns_503_without_backend(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api backend forced, empty key -> feature off -> 503."""
        monkeypatch.setattr(settings, "LLM_BACKEND", "api")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
        response = await client.post(
            "/api/v1/onboarding/draft", json={"transcript": "хочу трекать сон"}
        )
        assert response.status_code == 503

    async def test_happy_path_returns_plan(self, client: AsyncClient) -> None:
        """Valid model JSON -> 200 with the parsed plan."""
        fake = QueuedLLMClient([_create_category_json()])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/onboarding/draft",
                json={"transcript": "хочу трекать часы сна"},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        data = response.json()
        assert data["operations"][0]["op"] == "create_category"
        assert data["operations"][0]["name"] == "Сон"

    async def test_invalid_then_valid_repair_succeeds(
        self, client: AsyncClient
    ) -> None:
        """Garbage first answer -> one repair pass -> success (2 LLM calls)."""
        fake = QueuedLLMClient(["not json", _create_category_json()])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/onboarding/draft", json={"transcript": "трекать сон"}
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        assert len(fake.prompts) == 2

    async def test_double_failure_returns_502(self, client: AsyncClient) -> None:
        """Two bad answers -> 502."""
        fake = QueuedLLMClient(["nope", "still nope"])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/onboarding/draft", json={"transcript": "трекать сон"}
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 502

    async def test_backend_failure_returns_502(self, client: AsyncClient) -> None:
        """A runtime backend error (timeout, API/CLI failure) -> 502, not 500."""

        class FailingLLMClient(LLMClient):
            async def generate(self, prompt: str) -> str:
                raise LLMError("backend timed out")

        app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
        try:
            response = await client.post(
                "/api/v1/onboarding/draft", json={"transcript": "трекать сон"}
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 502

    async def test_conflicting_name_is_flagged(self, client: AsyncClient) -> None:
        """A create_category whose name already exists gets name_conflict=true."""
        await client.post("/api/v1/categories", json={"name": "Спорт"})

        fake = QueuedLLMClient([_create_category_json(name="Спорт")])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/onboarding/draft", json={"transcript": "заведи спорт"}
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        assert response.json()["operations"][0]["name_conflict"] is True

    async def test_transcript_absent_from_logs_on_failure(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The transcript never reaches the logs, even on the 502 path."""
        secret = "мой-секретный-транскрипт-12345"
        fake = QueuedLLMClient(["bad", "bad again"])
        app.dependency_overrides[get_llm_client] = lambda: fake
        with caplog.at_level(logging.DEBUG):
            try:
                response = await client.post(
                    "/api/v1/onboarding/draft", json={"transcript": secret}
                )
            finally:
                app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 502
        assert secret not in caplog.text
