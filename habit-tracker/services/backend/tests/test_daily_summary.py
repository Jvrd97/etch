"""
Tests for the day-text -> numeric-metric plan (POST /api/v1/daily-summary/draft)
and its transactional application (POST /api/v1/daily-summary/apply).
"""

# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: unit tests for plan parsing/validation/prompt rules + API tests (503/502/repair, atomic apply, transcript persisted and never logged)
import json
import logging
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core.config import settings
from app.crud import category as category_crud
from app.crud.daily_summary import (
    DAILY_SUMMARY_SOURCE,
    DailySummaryApplyError,
    validate_metric_ops,
)
from app.crud.values import format_number
from app.llm.client import LLMClient, LLMError
from app.llm.daily_summary import (
    DAILY_SUMMARY_SYSTEM_PROMPT,
    DailySummaryPlanError,
    build_catalog,
    build_prompt,
    generate_daily_summary_plan,
    parse_plan,
)
from app.main import app
from app.models import Entry, Transcript
from app.schemas.daily_summary import LogMetricOp

ENTRY_DATE = "2026-07-30"
ENTRY_DAY = date(2026, 7, 30)


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


def _plan_json(
    category_id: int,
    field_id: int,
    value: float = 30,
    *,
    uncertain: bool = False,
    implausible: bool = False,
) -> str:
    return json.dumps(
        {
            "metrics": [
                {
                    "op": "log_metric",
                    "category_id": category_id,
                    "field_id": field_id,
                    "value": value,
                    "source_text": "отжался 30 раз",
                    "uncertain": uncertain,
                    "implausible": implausible,
                }
            ],
            "unresolved": [],
        }
    )


async def _make_category(
    client: AsyncClient,
    db_session: AsyncSession,
    name: str,
    field_type: str = "number",
) -> tuple[int, int]:
    """Create a one-field category through the API; return (category_id, field_id)."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "fields": [{"name": "Значение", "field_type": field_type, "order": 1}],
        },
    )
    assert response.status_code == 201
    data = response.json()
    category = await category_crud.get_category(db_session, data["id"])
    assert category is not None
    return category.id, category.fields[0].id


# --------------------------------------------------------------------------- #
# Parsing and the prompt catalogue
# --------------------------------------------------------------------------- #


class TestParsePlan:
    def test_parses_metric_with_ids(self) -> None:
        plan = parse_plan(_plan_json(3, 7))
        assert len(plan.metrics) == 1
        metric = plan.metrics[0]
        assert metric.category_id == 3
        assert metric.field_id == 7
        assert metric.value == 30

    def test_extracts_json_from_markdown_fence_and_prose(self) -> None:
        wrapped = "Вот план:\n```json\n" + _plan_json(3, 7) + "\n```\nГотово"
        plan = parse_plan(wrapped)
        assert plan.metrics[0].category_id == 3

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(DailySummaryPlanError):
            parse_plan("совсем не json")

    def test_metric_without_field_id_is_rejected(self) -> None:
        """Names never resolve anything: a metric without ids is not a metric."""
        payload = json.dumps(
            {
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": 3,
                        "value": 30,
                        "source_text": "отжался 30 раз",
                    }
                ],
                "unresolved": [],
            }
        )
        with pytest.raises(DailySummaryPlanError):
            parse_plan(payload)

    def test_destructive_operation_is_not_expressible(self) -> None:
        """The schema has no delete/rename op — extra keys are forbidden."""
        payload = json.dumps(
            {
                "metrics": [
                    {
                        "op": "delete_category",
                        "category_id": 3,
                        "field_id": 7,
                        "value": 1,
                        "source_text": "x",
                    }
                ],
                "unresolved": [],
            }
        )
        with pytest.raises(DailySummaryPlanError):
            parse_plan(payload)

    def test_unresolved_metrics_are_kept_with_their_wording(self) -> None:
        payload = json.dumps(
            {
                "metrics": [],
                "unresolved": [
                    {"text": "погулял с собакой", "reason": "нет категории"}
                ],
            }
        )
        plan = parse_plan(payload)
        assert plan.unresolved[0].text == "погулял с собакой"


@pytest.mark.asyncio
class TestCatalog:
    async def test_catalog_carries_category_and_field_ids(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        categories = await category_crud.get_categories(db_session, limit=None)

        catalog = build_catalog(categories)

        assert f"category_id={category_id}" in catalog
        assert f"field_id={field_id}" in catalog

    async def test_prompt_carries_the_date_the_day_is_filed_under(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Without the date, "вчера" in a retelling has nothing to be relative to."""
        await _make_category(client, db_session, "Спорт")
        categories = await category_crud.get_categories(db_session, limit=None)

        prompt = build_prompt("вчера отжался 30 раз", categories, ENTRY_DAY)

        assert ENTRY_DATE in prompt


class TestPromptRules:
    def test_duration_rule_states_whole_seconds_with_an_example(self) -> None:
        """A duration field stores seconds and nothing converts after the model."""
        assert "duration" in DAILY_SUMMARY_SYSTEM_PROMPT
        assert "WHOLE SECONDS" in DAILY_SUMMARY_SYSTEM_PROMPT
        assert "2400" in DAILY_SUMMARY_SYSTEM_PROMPT

    def test_relative_dates_are_pinned_to_the_given_day(self) -> None:
        assert "вчера" in DAILY_SUMMARY_SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# Semantic validation
# --------------------------------------------------------------------------- #


def _op(category_id: int, field_id: int, value: float = 30) -> LogMetricOp:
    return LogMetricOp(
        category_id=category_id,
        field_id=field_id,
        value=value,
        source_text="отжался 30 раз",
    )


@pytest.mark.asyncio
class TestValidateMetricOps:
    async def test_unknown_category_id_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_category(client, db_session, "Спорт")
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_metric_ops([_op(9999, 1)], categories)

        assert errors and "category_id" in errors[0]

    async def test_field_from_another_category_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        sport_id, _ = await _make_category(client, db_session, "Спорт")
        _, other_field_id = await _make_category(client, db_session, "Сон")
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_metric_ops([_op(sport_id, other_field_id)], categories)

        assert errors and "field_id" in errors[0]

    async def test_non_numeric_field_under_a_number_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(
            client, db_session, "Заметки", field_type="text"
        )
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_metric_ops([_op(category_id, field_id)], categories)

        assert errors and "field_type" in errors[0]

    async def test_valid_op_passes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        categories = await category_crud.get_categories(db_session, limit=None)

        assert validate_metric_ops([_op(category_id, field_id)], categories) == []

    async def test_errors_never_echo_the_user_wording(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Validation text is shown and logged around; it must carry ids only."""
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_metric_ops([_op(9999, 1)], categories)

        assert all("отжался" not in error for error in errors)


# --------------------------------------------------------------------------- #
# Draft endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
class TestDraftEndpoint:
    async def test_returns_503_without_backend(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LLM_BACKEND", "api")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

        response = await client.post(
            "/api/v1/daily-summary/draft",
            json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
        )

        assert response.status_code == 503

    async def test_happy_path_returns_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        fake = QueuedLLMClient([_plan_json(category_id, field_id)])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        metric = response.json()["metrics"][0]
        assert metric["category_id"] == category_id
        assert metric["field_id"] == field_id

    async def test_repair_pass_recovers_from_a_bad_first_answer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        fake = QueuedLLMClient(["не json", _plan_json(category_id, field_id)])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        assert len(fake.prompts) == 2

    async def test_double_failure_returns_502(self, client: AsyncClient) -> None:
        fake = QueuedLLMClient(["нет", "всё ещё нет"])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 502
        assert len(fake.prompts) == 2

    async def test_backend_failure_returns_502(self, client: AsyncClient) -> None:
        class FailingLLMClient(LLMClient):
            async def generate(self, prompt: str) -> str:
                raise LLMError("backend timed out")

        app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 502

    async def test_transcript_is_stored_once_with_its_source(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        fake = QueuedLLMClient([_plan_json(category_id, field_id)])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        rows = (await db_session.execute(select(Transcript))).scalars().all()
        assert len(rows) == 1
        assert rows[0].source == DAILY_SUMMARY_SOURCE
        assert rows[0].text == "отжался 30 раз"

    async def test_transcript_absent_from_logs_on_failure(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = "мой-секретный-пересказ-дня-12345"
        fake = QueuedLLMClient(["плохо", "снова плохо"])
        app.dependency_overrides[get_llm_client] = lambda: fake
        with caplog.at_level(logging.DEBUG):
            try:
                response = await client.post(
                    "/api/v1/daily-summary/draft",
                    json={"transcript": secret, "entry_date": ENTRY_DATE},
                )
            finally:
                app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 502
        assert secret not in caplog.text


# --------------------------------------------------------------------------- #
# Apply endpoint
# --------------------------------------------------------------------------- #


def _apply_payload(ops: list[dict[str, object]]) -> dict[str, object]:
    return {"entry_date": ENTRY_DATE, "metrics": ops}


def _metric_payload(
    category_id: int, field_id: int, value: float = 30
) -> dict[str, object]:
    return {
        "op": "log_metric",
        "category_id": category_id,
        "field_id": field_id,
        "value": value,
        "source_text": "отжался 30 раз",
    }


@pytest.mark.asyncio
class TestApplyEndpoint:
    async def test_creates_entries_visible_through_the_entries_api(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(category_id, field_id, 30)]),
        )

        assert response.status_code == 201
        entries = (
            await client.get(f"/api/v1/entries?category_id={category_id}")
        ).json()
        assert len(entries) == 1
        assert entries[0]["entry_date"] == ENTRY_DATE
        assert entries[0]["values"][0]["field_id"] == field_id
        assert entries[0]["values"][0]["value"] == "30"

    async def test_metrics_of_one_category_share_a_single_entry(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Спорт",
                "fields": [
                    {"name": "Отжимания", "field_type": "number", "order": 1},
                    {"name": "Подтягивания", "field_type": "number", "order": 2},
                ],
            },
        )
        category = await category_crud.get_category(db_session, response.json()["id"])
        assert category is not None
        first, second = category.fields[0].id, category.fields[1].id

        applied = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload(
                [
                    _metric_payload(category.id, first, 30),
                    _metric_payload(category.id, second, 10),
                ]
            ),
        )

        assert applied.status_code == 201
        entries = (
            await client.get(f"/api/v1/entries?category_id={category.id}")
        ).json()
        assert len(entries) == 1
        assert len(entries[0]["values"]) == 2

    async def test_failure_midway_leaves_nothing_behind(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The second metric is invalid; the first one must not survive it."""
        good_category, good_field = await _make_category(client, db_session, "Спорт")

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload(
                [
                    _metric_payload(good_category, good_field, 30),
                    _metric_payload(good_category, 999999, 10),
                ]
            ),
        )

        assert response.status_code == 400
        rows = (await db_session.execute(select(Entry))).scalars().all()
        assert rows == []

    async def test_retry_after_a_failure_writes_the_day_once(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        failed = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload(
                [
                    _metric_payload(category_id, field_id, 30),
                    _metric_payload(category_id, 999999, 10),
                ]
            ),
        )
        assert failed.status_code == 400

        retried = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(category_id, field_id, 30)]),
        )

        assert retried.status_code == 201
        entries = (
            await client.get(f"/api/v1/entries?category_id={category_id}")
        ).json()
        assert len(entries) == 1

    async def test_empty_plan_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/daily-summary/apply", json=_apply_payload([])
        )
        assert response.status_code == 422

    async def test_apply_error_carries_ids_only(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, _ = await _make_category(client, db_session, "Спорт")

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(category_id, 999999, 10)]),
        )

        assert response.status_code == 400
        assert "отжался" not in response.json()["detail"]


@pytest.mark.asyncio
class TestApplyErrorType:
    async def test_error_reports_its_http_status(self) -> None:
        error = DailySummaryApplyError(400, "field_id 1 not found")
        assert error.status_code == 400
        assert error.detail == "field_id 1 not found"


@pytest.mark.asyncio
class TestGeneratePlanRepair:
    async def test_repair_prompt_carries_the_failure_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        categories = await category_crud.get_categories(db_session, limit=None)
        fake = QueuedLLMClient(["мусор", _plan_json(category_id, field_id)])

        plan = await generate_daily_summary_plan(
            fake, categories, "отжался 30 раз", ENTRY_DAY
        )

        assert len(fake.prompts) == 2
        assert "отклонён" in fake.prompts[1] or "rejected" in fake.prompts[1]
        assert plan.metrics[0].field_id == field_id


class TestFormatNumber:
    """The one rule for rendering a number into the EAV text column."""

    def test_whole_number_loses_its_decimal_tail(self) -> None:
        assert format_number(30.0) == "30"

    def test_fraction_is_rendered_not_repr_ed(self) -> None:
        assert format_number(2.5) == "2.5"
