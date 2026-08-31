# [review:need-review] PHASE-03/148
# summary: generation against a mocked LLM — a plan that breaks the canon twice ends as a skeleton and writes not one of its lines, a raised LLMError and a hung call end the same way with their own reason codes, a missing backend answers a plan rather than 503, the model is called at most twice, and neither the prompt nor the repair prompt nor any log line carries personal text
"""
Генерация плана моделью: что происходит, когда модель ошиблась.

Проверяется главное обещание среза: **день без плана не остаётся никогда**.
Модель не настроена, упала, зависла, дважды нарушила канон — во всех четырёх
случаях в базе лежит план, помечен `fallback`, и код причины записан.

Второе обещание — **между моделью и базой нет короткого пути**. План с рабочей
задачей в свободном вечере не записывается ни одной строкой: `plan_item`
принадлежит скелету, а не ответу модели.

Третье — **личный текст никуда не уезжает**. Промпт собран из канона и
производных флагов, ремонтный промпт — из кодов, логи — из дат и кодов.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.crud import day as day_crud
from app.day import generate, skeleton
from app.llm import day_plan as day_plan_llm
from app.llm.client import LLMClient, LLMError
from app.main import app
from app.models.plan import DayPlan, PlanItem
from app.schemas.day_plan import GeneratedDayPlan

from tests.test_day_constraints import WORKDAY, rule

DAY_URL = "/api/v1/day"

# Текст, которого не должно быть ни в одном промпте и ни в одном логе.
COMPLAINT_TEXT = "болит плечо при жиме над головой"
TRAINING_GATE = "no_overhead_press"
PERSONAL_ITEM_TEXT = "созвон про результаты биопсии"


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Строка канона, которой у `create_all` нет: без неё день отвечает 404."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


class QueuedLLMClient(LLMClient):
    """Модель-заглушка: отдаёт заготовленные ответы по очереди, считая вызовы."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("QueuedLLMClient ran out of responses")
        return self._responses.pop(0)


class BrokenLLMClient(LLMClient):
    """Модель, которая падает: кончилась подписка, лёг апстрим."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        raise LLMError("anthropic API error: APIStatusError")


class HangingLLMClient(LLMClient):
    """Модель, которая не отвечает: вызов упирается в бюджет."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


def _work_in_the_free_evening(target: date) -> str:
    """Ответ модели, кладущий рабочую задачу в свободный вечер."""
    return (
        '{"title": "день", "sections": [{"title": "Работа", "kind": "work", '
        '"items": [{"code": "W1", "kind": "task", "rigidity": "soft", '
        f'"text": "{PERSONAL_ITEM_TEXT}", "window": "20:00-21:00", '
        '"done_criterion": "сделано", "unlinked_reason": "нет цели"}]}]}'
    )


async def _generate(client: AsyncClient, target: date, llm: LLMClient | None) -> dict:
    """Позвать генерацию с подменённой моделью и вернуть тело ответа."""
    app.dependency_overrides[get_llm_client] = lambda: llm
    try:
        response = await client.post(f"{DAY_URL}/{target.isoformat()}/plan/generate")
    finally:
        app.dependency_overrides.pop(get_llm_client, None)
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.asyncio
class TestTheDayIsNeverLeftWithoutAPlan:
    """Четыре способа для модели подвести, и один и тот же исход."""

    async def test_a_plan_breaking_the_canon_twice_ends_as_a_skeleton(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        answer = _work_in_the_free_evening(WORKDAY)
        fake = QueuedLLMClient([answer, answer])

        body = await _generate(client, WORKDAY, fake)

        assert body["source"] == generate.AUTHOR_FALLBACK
        assert body["fallback_reason"] == generate.REASON_PLAN_INVALID
        # Ровно два обращения: попытка и один ремонтный заход.
        assert len(fake.prompts) == 2

    async def test_not_one_line_of_the_refused_plan_reaches_the_database(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        answer = _work_in_the_free_evening(WORKDAY)
        await _generate(client, WORKDAY, QueuedLLMClient([answer, answer]))

        rows = await db_session.execute(
            select(PlanItem).where(PlanItem.text_md == PERSONAL_ITEM_TEXT)
        )
        assert rows.scalars().all() == []

    async def test_a_broken_model_still_leaves_a_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        broken = BrokenLLMClient()

        body = await _generate(client, WORKDAY, broken)

        assert body["source"] == generate.AUTHOR_FALLBACK
        assert body["fallback_reason"] == generate.REASON_LLM_ERROR
        assert body["sections"] != []
        # Падение на первом вызове ремонтом не лечится: ремонт чинит ответ, а
        # ответа не было.
        assert broken.calls == 1

    async def test_a_missing_backend_answers_a_plan_rather_than_503(
        self, client: AsyncClient
    ) -> None:
        body = await _generate(client, WORKDAY, None)

        assert body["source"] == generate.AUTHOR_FALLBACK
        assert body["fallback_reason"] == generate.REASON_LLM_NOT_CONFIGURED
        assert body["sections"] != []

    async def test_a_hung_call_is_cut_off_by_the_budget(self) -> None:
        """
        Потолок на вызов проверяется на самой обёртке, а не ожиданием 120 секунд.

        Тест, который ждал бы настоящий бюджет, шёл бы две минуты и проверял бы
        терпение, а не код.
        """
        hanging = HangingLLMClient()
        timed = generate._TimedClient(hanging, budget=0.01)

        with pytest.raises(asyncio.TimeoutError):
            await timed.generate("prompt")
        assert hanging.calls == 1

    async def test_a_generation_that_runs_out_of_budget_writes_the_skeleton(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(generate, "TOTAL_BUDGET_SECONDS", 0.01)
        hanging = HangingLLMClient()

        body = await _generate(client, WORKDAY, hanging)

        assert body["source"] == generate.AUTHOR_FALLBACK
        assert body["fallback_reason"] == generate.REASON_LLM_TIMEOUT


@pytest.mark.asyncio
class TestAPlanThatPasses:
    """Ответ, прошедший форму и канон, пишется как есть и под своим авторством."""

    async def test_a_clean_plan_is_stored_as_the_model_s(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # Скелет — это гарантированно чистый план: он собран из той же строки
        # канона, против которой проверяется. Модель, «вернувшая» его, — самый
        # честный способ проверить счастливый путь, не выдумывая расписание.
        built = skeleton.skeleton_plan(WORKDAY, rule())
        answer = _skeleton_as_model_answer(built)
        fake = QueuedLLMClient([answer])

        body = await _generate(client, WORKDAY, fake)

        assert body["source"] == generate.AUTHOR_LLM
        assert body["fallback_reason"] is None
        assert len(fake.prompts) == 1
        stored = await db_session.execute(
            select(DayPlan).where(DayPlan.day_date == WORKDAY)
        )
        row = stored.scalars().one()
        assert row.source == generate.AUTHOR_LLM
        assert row.fallback_reason is None


def _skeleton_as_model_answer(built: skeleton.SkeletonPlan) -> str:
    """Скелет, переписанный в JSON, который умеет отвечать модель."""
    import json

    from app.crud.plan_violation import skeleton_document

    document = skeleton_document(built, rule())
    sections = []
    counter = 0
    for section in document.sections:
        items = []
        for item in section.items:
            counter += 1
            items.append(
                {
                    "code": item.code or f"L{counter}",
                    "kind": item.kind,
                    "rigidity": item.rigidity,
                    "text": item.text_md,
                    "window": item.window,
                    "done_criterion": item.done_criterion,
                    "unlinked_reason": item.unlinked_reason,
                }
            )
        sections.append({"title": section.title, "kind": section.kind, "items": items})
    return json.dumps({"title": document.title, "sections": sections})


class TestNothingPersonalLeavesTheProcess:
    """Промпт, ремонтный промпт и логи — коды и канон, не текст."""

    def test_the_prompt_carries_a_gate_flag_and_not_the_complaint(self) -> None:
        prompt = day_plan_llm.build_prompt(
            WORKDAY,
            rule(),
            skeleton.Signals(is_training_day=True),
            gates=(TRAINING_GATE,),
        )

        assert f"training_gate: {TRAINING_GATE}" in prompt
        assert COMPLAINT_TEXT not in prompt

    def test_the_repair_prompt_names_rule_codes_and_item_codes_only(self) -> None:
        plan = GeneratedDayPlan.model_validate(
            {
                "title": "день",
                "sections": [
                    {
                        "title": "Работа",
                        "kind": "work",
                        "items": [
                            {
                                "code": "W1",
                                "kind": "task",
                                "rigidity": "soft",
                                "text": PERSONAL_ITEM_TEXT,
                                "window": "20:00-21:00",
                                "done_criterion": "сделано",
                                "unlinked_reason": "нет цели",
                            }
                        ],
                    }
                ],
            }
        )
        from app.day.constraints import check_all
        from app.schemas.day_plan import to_draft

        violations = check_all(to_draft(plan, WORKDAY, rule()), rule())
        assert violations != []

        summary = day_plan_llm.violation_summary(violations, plan.codes())
        repaired = day_plan_llm.build_repair("BASE", "PREVIOUS ANSWER", summary)

        assert "free_evening_not_empty" in summary or any(
            violation.rule_code in summary for violation in violations
        )
        assert "W1" in summary
        # Ни текста пункта, ни предыдущего ответа целиком.
        assert PERSONAL_ITEM_TEXT not in repaired
        assert "PREVIOUS ANSWER" not in repaired

    def test_no_logger_call_in_the_new_code_takes_a_text(self) -> None:
        """
        Грепом, а не дисциплиной: логи переживают день, а строка плана бывает
        названа диагнозом.
        """
        root = Path(__file__).resolve().parents[1] / "app"
        sources = [
            root / "day" / "generate.py",
            root / "llm" / "day_plan.py",
            root / "schemas" / "day_plan.py",
        ]
        forbidden = re.compile(
            r"logger\.\w+\([^)]*\b("
            r"text|text_md|title|note|notebook|report|complaint|prompt|raw"
            r")\b"
        )
        for source in sources:
            body = source.read_text(encoding="utf-8")
            assert forbidden.search(body) is None, source.name


@pytest.mark.asyncio
class TestOneTransaction:
    """Частично применённого плана не бывает."""

    async def test_a_second_generation_replaces_the_first_whole(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        built = skeleton.skeleton_plan(WORKDAY, rule())
        answer = _skeleton_as_model_answer(built)
        await _generate(client, WORKDAY, QueuedLLMClient([answer]))
        first = await db_session.execute(
            select(DayPlan).where(DayPlan.day_date == WORKDAY)
        )
        assert first.scalars().one().source == generate.AUTHOR_LLM

        await _generate(client, WORKDAY, BrokenLLMClient())

        rows = await db_session.execute(
            select(DayPlan).where(DayPlan.day_date == WORKDAY)
        )
        plans = rows.scalars().all()
        # Один план на день — это инвариант таблицы, и вторая генерация его не
        # нарушает: она заменяет документ целиком, а не дописывает второй.
        assert len(plans) == 1
        assert plans[0].source == generate.AUTHOR_FALLBACK

    async def test_neighbour_days_are_untouched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _generate(client, WORKDAY, None)

        for offset in (-1, 1):
            neighbour = WORKDAY + timedelta(days=offset)
            rows = await db_session.execute(
                select(DayPlan).where(DayPlan.day_date == neighbour)
            )
            assert rows.scalars().all() == []


@pytest.mark.asyncio
async def test_the_reason_survives_a_re_read(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Код причины лежит в базе, а не только в ответе на генерацию."""
    with caplog.at_level(logging.DEBUG):
        await _generate(client, WORKDAY, BrokenLLMClient())

    read = await client.get(f"{DAY_URL}/{WORKDAY.isoformat()}")
    assert read.status_code == 200, read.text
    assert read.json()["plan"]["fallback_reason"] == generate.REASON_LLM_ERROR
    assert PERSONAL_ITEM_TEXT not in caplog.text
