# [review:need-review] PHASE-03/115
# summary: the day plan a chat may propose — applied to an empty day it becomes the day's plan through the same `replace_plan` everything else uses; offered for a day that already has one it never reaches the card and answers 409 if it got there anyway; breaking one of the eight rules it is refused by rule code and writes not a single row
"""
Чат предлагает план дня — и не умеет переписать существующий.

Проверяются три обещания среза.

**Пустой день чат собрать может.** Предложение доезжает до плашки, применение
кладёт его тем же `replace_plan`, которым пишут скилл и ручка генерации.

**Занятый день — нет.** Операция применима только ко дню без плана, и это
проверяется дважды: предложение на занятый день не становится плашкой вовсе, а
предложение, доехавшее до применения (план на дне появился, пока плашка висела),
отвечает 409 и оставляет существующий план нетронутым.

**Нарушивший канон план не сохраняется молча.** Восемь правил `#147` судят его на
уровне `block`: до плашки он не доезжает, а на применении отвечает 422 с кодом
правила. Ни одной строки в базе при этом не появляется.

Того, чего в схеме нет, здесь нет и в тестах: невыразимость замены проверяет
`test_chat_plan_schema.py` — на JSON Schema, а не на прогоне промпта.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import _attach_plan
from app.crud import chat as chat_crud
from app.crud import day as day_crud
from app.day.constraints import RULE_FREE_EVENING_EMPTY
from app.models.chat import MESSAGE_ROLE_ASSISTANT, ChatPlan as ChatPlanRow
from app.models.plan import DayPlan, PlanItem
from app.models.plan_revision import AUTHOR_AI, PlanRevision

from tests.test_day_constraints import WORKDAY

CHAT_URL = "/api/v1/chat"
DAY_URL = "/api/v1/day"

# Текст рабочей задачи, которой в отказе быть не должно: задача бывает названа
# диагнозом, и ни один ответ, ни одна строка `plan_violation` её не цитируют.
PERSONAL_TASK_TEXT = "созвон про результаты биопсии"


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Строка канона, которой у `create_all` нет: без неё день отвечает 404."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


def anchors_section() -> dict[str, Any]:
    """Якоря канона: подъём и спорт, оба до старта работы."""
    return {
        "title": "Якоря",
        "kind": "anchors",
        "items": [
            {
                "code": "подъём",
                "kind": "anchor",
                "rigidity": "hard",
                "text": "подъём",
                "window": "06:00-06:15",
            },
            {
                "code": "спорт",
                "kind": "anchor",
                "rigidity": "hard",
                "text": "зарядка",
                "window": "06:30-07:15",
            },
        ],
    }


def work_item(code: str, window: str) -> dict[str, Any]:
    """Одна рабочая задача с окном и критерием готовности."""
    return {
        "code": code,
        "kind": "task",
        "rigidity": "soft",
        "text": PERSONAL_TASK_TEXT,
        "window": window,
        "done_criterion": "ветка смержена",
        "unlinked_reason": "нет цели квартала",
    }


def legal_day_plan() -> dict[str, Any]:
    """План, который проходит все восемь правил."""
    return {
        "op": "draft_day_plan",
        "title": "среда",
        "sections": [
            anchors_section(),
            {
                "title": "Работа",
                "kind": "work",
                "items": [work_item("W1", "08:00-10:00")],
            },
        ],
    }


def day_plan_in_the_free_evening() -> dict[str, Any]:
    """
    Тот же план плюс рабочая задача в свободном вечере.

    Ломается ровно одно правило: якоря на месте, задач две из разрешённых
    четырёх, окна не пересекаются, все строки на целевой день.
    """
    plan = legal_day_plan()
    plan["sections"][1]["items"].append(work_item("W2", "20:00-21:00"))
    return plan


def day_plan_with_an_unreadable_window() -> dict[str, Any]:
    """
    План, у которого окно — слово, а не время.

    Схема такое пропускает: `window` — строка, и `«утром»` длиннее нуля знаков.
    Документ из него не собирается, и это обязано быть отказом, а не упавшим
    ходом: разбор ответа не роняет разговор, а применение отвечает 422.
    """
    plan = legal_day_plan()
    plan["sections"][1]["items"][0]["window"] = "утром"
    return plan


def answer_with(plan: dict[str, Any], prose: str = "Собрал день.") -> str:
    """Ответ модели: слова человеку и блок JSON рядом, как просит промпт."""
    return f"{prose}\n\n```json\n{json.dumps({'plan': plan}, ensure_ascii=False)}\n```"


async def attach(
    client: AsyncClient, db_session: AsyncSession, answer: str
) -> ChatPlanRow | None:
    """
    Прогнать ответ модели через тот же путь, которым его снимает закрытый ход.

    Ход в тесте не гоняется: он требует бэкенда модели, а проверяется здесь то,
    что происходит после ответа.
    """
    conversation = await client.post(f"{CHAT_URL}/conversations", json={})
    assert conversation.status_code == 201, conversation.text
    conversation_id = int(conversation.json()["id"])

    seq = await chat_crud.next_seq(db_session, conversation_id)
    message = await chat_crud.add_message(
        db_session,
        conversation_id=conversation_id,
        seq=seq,
        role=MESSAGE_ROLE_ASSISTANT,
        content=answer,
    )
    await _attach_plan(db_session, message_id=message.id, text=answer, complete=True)
    await db_session.commit()
    rows = await chat_crud.plans_for_messages(db_session, [message.id])
    return rows.get(message.id)


async def store_proposal(
    client: AsyncClient, db_session: AsyncSession, plan: dict[str, Any]
) -> int:
    """
    Положить предложение в обход проверок рождения и вернуть его id.

    Так выглядит плашка, которую человек увидел вчера: на момент показа она была
    применима, а между показом и нажатием состояние дня успело смениться. Ровно
    этот случай и проверяет вторая проверка — та, что стоит перед записью.
    """
    conversation = await client.post(f"{CHAT_URL}/conversations", json={})
    assert conversation.status_code == 201, conversation.text
    conversation_id = int(conversation.json()["id"])

    seq = await chat_crud.next_seq(db_session, conversation_id)
    message = await chat_crud.add_message(
        db_session,
        conversation_id=conversation_id,
        seq=seq,
        role=MESSAGE_ROLE_ASSISTANT,
        content="Собрал день.",
    )
    row = await chat_crud.save_plan(
        db_session,
        message_id=message.id,
        entry_date=date.fromisoformat(str(plan["entry_date"])),
        plan=plan,
    )
    await db_session.commit()
    return row.id


def proposal(day_plan: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    """Предложение чата целиком, каким его хранит `chat_plans.plan`."""
    body: dict[str, Any] = {"entry_date": WORKDAY.isoformat(), **extra}
    if day_plan is not None:
        body["day_plan"] = day_plan
    return body


async def make_existing_plan(client: AsyncClient) -> str:
    """Собрать дню план из канона и вернуть его идентификатор."""
    response = await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan/skeleton")
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def read_plan(client: AsyncClient) -> dict[str, Any]:
    """План дня так, как его читает экран: полем карточки дня, а не своей ручкой."""
    response = await client.get(f"{DAY_URL}/{WORKDAY.isoformat()}")
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan is not None, "на дне нет плана"
    return dict(plan)


async def count_items(db_session: AsyncSession) -> int:
    """Сколько строк плана лежит в базе всего."""
    result = await db_session.execute(select(func.count()).select_from(PlanItem))
    return int(result.scalar_one())


@pytest.mark.asyncio
class TestProposing:
    """Что становится плашкой, а что остаётся обычным сообщением."""

    async def test_a_day_plan_for_an_empty_day_reaches_the_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        row = await attach(client, db_session, answer_with(proposal(legal_day_plan())))
        assert row is not None
        assert row.plan["day_plan"]["op"] == "draft_day_plan"

    async def test_a_day_that_already_has_a_plan_gets_no_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Плашка, которая на нажатии отвечает 409, — это не предложение.

        Есть ли у дня план — факт базы, а не часть пересказа, и решает его
        сервер: модель могла ответить мимо инструкции, и это ничего не меняет.
        """
        await make_existing_plan(client)

        row = await attach(client, db_session, answer_with(proposal(legal_day_plan())))
        assert row is None

    async def test_a_day_plan_breaking_a_rule_gets_no_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        row = await attach(
            client,
            db_session,
            answer_with(proposal(day_plan_in_the_free_evening())),
        )
        assert row is None

    async def test_a_day_plan_that_does_not_become_a_document_gets_no_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Нечитаемое окно — отсутствие плашки, а не упавший ход."""
        row = await attach(
            client,
            db_session,
            answer_with(proposal(day_plan_with_an_unreadable_window())),
        )
        assert row is None

    async def test_the_ticks_of_the_same_reply_survive_a_refused_day_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Снимается операция, а не всё предложение.

        Число из той же реплики применимо независимо от того, занят ли день
        планом, и терять его было бы платой за чужую ошибку.
        """
        await make_existing_plan(client)
        metrics = [
            {
                "op": "log_metric",
                "category_id": 1,
                "field_id": 7,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]

        row = await attach(
            client,
            db_session,
            answer_with(proposal(legal_day_plan(), metrics=metrics)),
        )
        assert row is not None
        assert row.plan.get("day_plan") is None
        assert len(row.plan["metrics"]) == 1


@pytest.mark.asyncio
class TestApplying:
    """Применение: один путь записи и две проверки перед ним."""

    async def test_an_offered_day_plan_becomes_the_day_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        plan_id = await store_proposal(client, db_session, proposal(legal_day_plan()))

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["applied_operations"] == 1
        assert body["day_plan_id"] is not None

        stored = await read_plan(client)
        codes = [
            item["code"] for section in stored["sections"] for item in section["items"]
        ]
        assert codes == ["подъём", "спорт", "W1"]

    async def test_the_written_plan_says_the_model_wrote_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Кем собран план — часть состояния дня, а не примечание к нему.

        Источник `llm` и автор первой ревизии `ai`: строки написала модель, а
        человек их принял, и накопленные дифы обязаны это помнить.
        """
        plan_id = await store_proposal(client, db_session, proposal(legal_day_plan()))
        applied = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert applied.status_code == 201, applied.text

        assert (await read_plan(client))["source"] == "llm"
        authors = await db_session.execute(
            select(PlanRevision.author).where(PlanRevision.day_date == WORKDAY)
        )
        assert list(authors.scalars().all()) == [AUTHOR_AI]

    async def test_a_day_that_already_has_a_plan_answers_409_and_keeps_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Вторая половина защиты: план появился, пока плашка висела.

        Предложение сохранено в обход проверок рождения — так выглядит вчерашняя
        плашка. Молча переписать день ей нечем, и отказ обязан быть отказом, а не
        перезаписью: сгенерированный документ чеканит новые id строк, то есть
        вместе с планом исчезли бы все отметки дня.
        """
        plan_id = await store_proposal(client, db_session, proposal(legal_day_plan()))
        before = await make_existing_plan(client)

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert response.status_code == 409, response.text

        stored = await read_plan(client)
        assert str(stored["id"]) == before
        assert stored["source"] != "llm"

    async def test_a_plan_breaking_a_rule_is_refused_by_its_rule_code(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Отказ называет правило и id пунктов — и ни одной строки плана.

        `Violation.detail` текста не носит намеренно: строки нарушений живут
        дольше плана, который их породил, а задача бывает названа диагнозом.
        """
        plan_id = await store_proposal(
            client, db_session, proposal(day_plan_in_the_free_evening())
        )

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["error"] == "day_plan_violates_canon"
        assert [one["rule_code"] for one in detail["violations"]] == [
            RULE_FREE_EVENING_EMPTY
        ]
        assert PERSONAL_TASK_TEXT not in response.text

    async def test_not_one_line_of_the_refused_plan_reaches_the_database(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        plan_id = await store_proposal(
            client, db_session, proposal(day_plan_in_the_free_evening())
        )

        refused = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert refused.status_code == 422

        assert await count_items(db_session) == 0
        plans = await db_session.execute(select(func.count()).select_from(DayPlan))
        assert plans.scalar_one() == 0

    async def test_a_day_plan_that_does_not_become_a_document_answers_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Тот же 422 и то же тело, каким отвечает запись плана человеку."""
        plan_id = await store_proposal(
            client, db_session, proposal(day_plan_with_an_unreadable_window())
        )

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "bad_window"
        assert await count_items(db_session) == 0

    async def test_taking_a_day_plan_that_was_not_offered_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Применить можно подмножество показанного и ничего сверх него."""
        metrics = [
            {
                "op": "log_metric",
                "category_id": 1,
                "field_id": 7,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]
        plan_id = await store_proposal(
            client, db_session, proposal(None, metrics=metrics)
        )

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"day_plan": True}
        )
        assert response.status_code == 422, response.text
        assert await count_items(db_session) == 0

    async def test_an_apply_that_takes_nothing_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Применение, которое ничего не пишет, — мёртвая кнопка на экране."""
        plan_id = await store_proposal(client, db_session, proposal(legal_day_plan()))

        response = await client.post(f"{CHAT_URL}/plans/{plan_id}/apply", json={})
        assert response.status_code == 422, response.text
        assert await count_items(db_session) == 0
