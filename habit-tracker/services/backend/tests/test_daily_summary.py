"""
Tests for the day-text -> numeric-metric plan (POST /api/v1/daily-summary/draft)
and its transactional application (POST /api/v1/daily-summary/apply).
"""

# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: unit tests for plan parsing/validation/prompt rules + API tests (503/502/repair, atomic apply with the journal, append/create collision in the draft, idempotent replay incl. journal-only and the lost race, 409 on a key reused with a new metric, a new journal or another date, transcript persisted and never logged)
import json
import logging
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core.config import settings
from app.crud import category as category_crud
from app.crud import daily_summary as daily_summary_crud
from app.crud import journal as journal_crud
from app.crud.daily_summary import (
    DAILY_SUMMARY_SOURCE,
    DailySummaryApplyError,
    validate_metric_ops,
)
from app.crud.journal import DAY_JOURNAL_SEPARATOR
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
from app.models import AppliedDailySummary, Entry, JournalEntry, Transcript
from app.schemas.daily_summary import LogMetricOp

ENTRY_DATE = "2026-07-30"
ENTRY_DAY = date(2026, 7, 30)

# The generated body of the day, as the model would write it. Defined up here
# because `_plan_json` embeds it: a constant used by a helper must exist before
# the helper, not two hundred lines below it.
DAY_TEXT = "## Спорт\n\nОтжался 30 раз."
MORNING_TEXT = "Проснулся разбитым, но встал."


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
    journal: bool = False,
) -> str:
    payload: dict[str, object] = {
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
    if journal:
        payload["journal"] = {
            "title": "Разбор дня",
            "content": DAY_TEXT,
            "mood": None,
            "tags": None,
        }
    return json.dumps(payload)


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


# --------------------------------------------------------------------------- #
# The journal operation: one entry per day, appended to rather than duplicated
# --------------------------------------------------------------------------- #


def _journal_payload(
    content: str = DAY_TEXT,
    mode: str = "append",
    *,
    title: str | None = "Разбор дня",
) -> dict[str, object]:
    """The apply-side journal op: no `existing_entry_id`, the server resolves the day."""
    return {
        "op": "write_journal",
        "title": title,
        "content": content,
        "mood": None,
        "tags": None,
        "mode": mode,
    }


async def _make_journal_entry(
    client: AsyncClient, content: str = MORNING_TEXT, entry_date: str = ENTRY_DATE
) -> int:
    response = await client.post(
        "/api/v1/journal",
        json={"content": content, "entry_date": entry_date, "title": "Утро"},
    )
    assert response.status_code == 201
    entry_id: int = response.json()["id"]
    return entry_id


async def _journal_entries(db: AsyncSession) -> list[JournalEntry]:
    rows = await db.execute(select(JournalEntry).order_by(JournalEntry.id))
    return list(rows.scalars().all())


@pytest.mark.asyncio
class TestJournalApply:
    async def test_day_text_and_metrics_land_in_one_apply(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [_metric_payload(category_id, field_id, 30)],
                "journal": _journal_payload(mode="create"),
            },
        )

        assert response.status_code == 201
        entries = await _journal_entries(db_session)
        assert len(entries) == 1
        assert entries[0].content == DAY_TEXT
        assert entries[0].entry_date == ENTRY_DAY
        assert response.json()["journal_entry_id"] == entries[0].id
        assert len((await db_session.execute(select(Entry))).scalars().all()) == 1

    async def test_the_requested_mode_reaches_the_journal_layer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Apply passes the mode through; what each mode does is `write_day_journal`'s
        own contract, covered in `test_journal.py::TestWriteDayJournal`."""
        existing_id = await _make_journal_entry(client)
        category_id, field_id = await _make_category(client, db_session, "Спорт")

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [_metric_payload(category_id, field_id, 30)],
                "journal": _journal_payload(mode="replace"),
            },
        )

        assert response.status_code == 201
        entries = await _journal_entries(db_session)
        assert len(entries) == 1
        assert entries[0].id == existing_id
        assert entries[0].content == DAY_TEXT

    async def test_a_failing_journal_write_rolls_the_metrics_back(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")

        async def boom(*args: object, **kwargs: object) -> JournalEntry:
            raise RuntimeError("journal write failed")

        monkeypatch.setattr(journal_crud, "write_day_journal", boom)

        with pytest.raises(RuntimeError):
            await client.post(
                "/api/v1/daily-summary/apply",
                json={
                    "entry_date": ENTRY_DATE,
                    "metrics": [_metric_payload(category_id, field_id, 30)],
                    "journal": _journal_payload(mode="create"),
                },
            )

        assert (await db_session.execute(select(Entry))).scalars().all() == []
        assert await _journal_entries(db_session) == []

    async def test_apply_without_metrics_or_journal_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={"entry_date": ENTRY_DATE, "metrics": []},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestJournalCollisionInDraft:
    async def test_draft_offers_an_append_when_the_day_already_has_text(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        existing_id = await _make_journal_entry(client)
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        fake = QueuedLLMClient([_plan_json(category_id, field_id, journal=True)])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 200
        journal = response.json()["journal"]
        assert journal["mode"] == "append"
        assert journal["existing_entry_id"] == existing_id

    async def test_draft_offers_a_create_when_the_day_is_empty(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        fake = QueuedLLMClient([_plan_json(category_id, field_id, journal=True)])
        app.dependency_overrides[get_llm_client] = lambda: fake
        try:
            response = await client.post(
                "/api/v1/daily-summary/draft",
                json={"transcript": "отжался 30 раз", "entry_date": ENTRY_DATE},
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        journal = response.json()["journal"]
        assert journal["mode"] == "create"
        assert journal["existing_entry_id"] is None
        assert journal["content"] == DAY_TEXT

    async def test_a_plan_without_a_journal_stays_without_one(
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

        assert response.json()["journal"] is None


class TestJournalPromptRules:
    def test_prompt_asks_for_a_markdown_body_of_the_day(self) -> None:
        assert "journal" in DAILY_SUMMARY_SYSTEM_PROMPT
        assert "Markdown" in DAILY_SUMMARY_SYSTEM_PROMPT

    def test_prompt_forbids_inventing_what_was_not_said(self) -> None:
        assert "Record only what was actually said" in DAILY_SUMMARY_SYSTEM_PROMPT
        assert "implausible" in DAILY_SUMMARY_SYSTEM_PROMPT


@pytest.mark.asyncio
class TestApplyIdempotency:
    async def test_replaying_a_successful_apply_writes_the_day_once(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        payload = {
            "entry_date": ENTRY_DATE,
            "metrics": [_metric_payload(category_id, field_id, 30)],
            "journal": _journal_payload(mode="create"),
        }
        headers = {"Idempotency-Key": "day-2026-07-30"}

        first = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )
        second = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["entry_ids"] == first.json()["entry_ids"]
        assert len((await db_session.execute(select(Entry))).scalars().all()) == 1
        entries = await _journal_entries(db_session)
        assert len(entries) == 1
        assert entries[0].content == DAY_TEXT

    async def test_a_different_key_writes_a_second_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The key dedups replays, not deliberate re-entry of the same day."""
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        payload = {
            "entry_date": ENTRY_DATE,
            "metrics": [_metric_payload(category_id, field_id, 30)],
        }

        await client.post(
            "/api/v1/daily-summary/apply",
            json=payload,
            headers={"Idempotency-Key": "a"},
        )
        second = await client.post(
            "/api/v1/daily-summary/apply",
            json=payload,
            headers={"Idempotency-Key": "b"},
        )

        assert second.status_code == 201
        assert len((await db_session.execute(select(Entry))).scalars().all()) == 2

    async def test_a_key_reused_with_an_extra_metric_is_a_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One more checkbox under the same key is a new intent, not a replay.

        Answering 200 would look like success and lose the added metric for good,
        because the key can never write it afterwards either.
        """
        sport_id, sport_field = await _make_category(client, db_session, "Спорт")
        sleep_id, sleep_field = await _make_category(client, db_session, "Сон")
        headers = {"Idempotency-Key": "day-2026-07-30"}

        first = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(sport_id, sport_field, 30)]),
            headers=headers,
        )
        second = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload(
                [
                    _metric_payload(sport_id, sport_field, 30),
                    _metric_payload(sleep_id, sleep_field, 8),
                ]
            ),
            headers=headers,
        )

        assert first.status_code == 201
        assert second.status_code == 409
        assert str(sleep_id) in second.json()["detail"]
        assert "отжался" not in second.json()["detail"]
        assert len((await db_session.execute(select(Entry))).scalars().all()) == 1

    async def test_a_key_reused_with_an_added_journal_is_a_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The day gained its text under a key that already wrote only numbers.

        The mirror image of the extra-metric case: answering 200 would look like
        the retelling was written when the receipt says no journal was, and the
        key can never write it afterwards either.
        """
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        headers = {"Idempotency-Key": "day-2026-07-30"}

        first = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(category_id, field_id, 30)]),
            headers=headers,
        )
        second = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [_metric_payload(category_id, field_id, 30)],
                "journal": _journal_payload(mode="create"),
            },
            headers=headers,
        )

        assert first.status_code == 201
        assert second.status_code == 409
        assert DAY_TEXT not in second.json()["detail"]
        assert await _journal_entries(db_session) == []

    async def test_a_key_reused_for_another_date_is_a_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One key belongs to one day; reusing it for the next day writes nothing.

        Without the date check the second day would be answered with the first
        day's ids and silently never recorded.
        """
        other_date = "2026-07-31"
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        headers = {"Idempotency-Key": "day-2026-07-30"}

        first = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(category_id, field_id, 30)]),
            headers=headers,
        )
        second = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": other_date,
                "metrics": [_metric_payload(category_id, field_id, 30)],
            },
            headers=headers,
        )

        assert first.status_code == 201
        assert second.status_code == 409
        rows = (
            (
                await db_session.execute(
                    select(Entry).where(Entry.entry_date == date(2026, 7, 31))
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    async def test_a_lost_race_answers_with_the_winners_result(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two applies of one key overlap: the loser answers 200, not 500.

        The race is staged by blinding the first lookup — exactly what a
        concurrent winner committing right after it would look like — so the
        insert is the one that discovers the duplicate.
        """
        category_id, field_id = await _make_category(client, db_session, "Спорт")
        payload = {
            "entry_date": ENTRY_DATE,
            "metrics": [_metric_payload(category_id, field_id, 30)],
            "journal": _journal_payload(mode="create"),
        }
        headers = {"Idempotency-Key": "raced"}

        first = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )
        assert first.status_code == 201

        real_find = daily_summary_crud.find_applied_summary
        lookups = {"count": 0}

        async def blind_once(*args: Any, **kwargs: Any) -> Any:
            lookups["count"] += 1
            if lookups["count"] == 1:
                return None
            return await real_find(*args, **kwargs)

        monkeypatch.setattr(daily_summary_crud, "find_applied_summary", blind_once)

        second = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )

        assert second.status_code == 200
        assert second.json() == first.json()
        assert len((await db_session.execute(select(Entry))).scalars().all()) == 1
        entries = await _journal_entries(db_session)
        assert len(entries) == 1
        assert entries[0].content == DAY_TEXT
        receipts = (
            (await db_session.execute(select(AppliedDailySummary))).scalars().all()
        )
        assert len(receipts) == 1

    async def test_a_lost_race_with_an_extra_metric_answers_409_not_500(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The loser of the race carries a metric the winner never wrote.

        The re-read in the IntegrityError branch then rejects rather than
        returns, and that rejection is the client's 409 — an unhandled
        DailySummaryApplyError there would surface as a 500 instead.
        """
        sport_id, sport_field = await _make_category(client, db_session, "Спорт")
        sleep_id, sleep_field = await _make_category(client, db_session, "Сон")
        headers = {"Idempotency-Key": "raced-with-extra"}

        first = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload([_metric_payload(sport_id, sport_field, 30)]),
            headers=headers,
        )
        assert first.status_code == 201

        real_find = daily_summary_crud.find_applied_summary
        lookups = {"count": 0}

        async def blind_once(*args: Any, **kwargs: Any) -> Any:
            lookups["count"] += 1
            if lookups["count"] == 1:
                return None
            return await real_find(*args, **kwargs)

        monkeypatch.setattr(daily_summary_crud, "find_applied_summary", blind_once)

        second = await client.post(
            "/api/v1/daily-summary/apply",
            json=_apply_payload(
                [
                    _metric_payload(sport_id, sport_field, 30),
                    _metric_payload(sleep_id, sleep_field, 8),
                ]
            ),
            headers=headers,
        )

        assert second.status_code == 409
        assert str(sleep_id) in second.json()["detail"]
        assert len((await db_session.execute(select(Entry))).scalars().all()) == 1


@pytest.mark.asyncio
class TestJournalOnlyIdempotency:
    """An apply with no metrics at all still has to be deduped by the key.

    This is the case the entry-borne key could not cover: nothing keyed was
    created, so a replay looked like a fresh apply and appended the retelling to
    itself.
    """

    async def test_replaying_a_journal_only_create_writes_the_text_once(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        payload = {
            "entry_date": ENTRY_DATE,
            "metrics": [],
            "journal": _journal_payload(mode="create"),
        }
        headers = {"Idempotency-Key": "journal-only-2026-07-30"}

        first = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )
        second = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["entry_ids"] == first.json()["entry_ids"]
        assert second.json()["journal_entry_id"] == first.json()["journal_entry_id"]

        entries = await _journal_entries(db_session)
        assert len(entries) == 1
        assert entries[0].content == DAY_TEXT
        assert DAY_JOURNAL_SEPARATOR not in entries[0].content
        assert entries[0].content.count(DAY_TEXT) == 1

    async def test_replaying_a_journal_only_append_appends_once(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        existing_id = await _make_journal_entry(client)
        payload = {
            "entry_date": ENTRY_DATE,
            "metrics": [],
            "journal": _journal_payload(mode="append"),
        }
        headers = {"Idempotency-Key": "journal-append-2026-07-30"}

        first = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )
        second = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["journal_entry_id"] == existing_id

        entries = await _journal_entries(db_session)
        assert len(entries) == 1
        assert entries[0].content == f"{MORNING_TEXT}{DAY_JOURNAL_SEPARATOR}{DAY_TEXT}"
        assert entries[0].content.count(DAY_JOURNAL_SEPARATOR) == 1
