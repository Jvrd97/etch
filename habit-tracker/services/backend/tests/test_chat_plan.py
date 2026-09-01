"""
Чат предлагает — человек применяет.

Реплика «я отжался 30 раз и выпил витамины» рождает плашку с галочками; тап по
«применить» кладёт записи в базу. Пишет при этом не модель и не ручка чата, а
уже работающий `apply_daily_summary` — тот же транзакционный путь и тот же
`Idempotency-Key`, что у экрана разбора дня.

Проверяется здесь три вещи. Повторное применение с тем же ключом отвечает 200 и
не пишет вторых записей. Применить можно только показанное: операция, дописанная
в обход плашки, отвергается сверкой с `chat_plans.plan`. И факт применения
переживает удаление квитанции — `applied_summary_id` стоит без внешнего ключа
намеренно.

Того, чего в схеме плана нет, здесь нет и в тестах: класс W2 проверяется
`test_chat_plan_schema.py` — на JSON Schema, а не на прогоне промпта.
"""

# [review:need-review] PHASE-03/115
# summary: tests for the plan parsed out of an answer (fenced block, prose around it, a broken one that leaves the turn standing), the apply that goes through apply_daily_summary with an Idempotency-Key, the narrowing to what was actually shown, 422 on a tick in a non-checklist category, dismiss, and the applied fact surviving the receipt's deletion

import json
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.chat.plan import ChatPlanError, parse_plan, plan_from_answer
from app.models.applied_daily_summary import AppliedDailySummary
from app.models.chat import (
    MESSAGE_ROLE_ASSISTANT,
    PLAN_STATUS_APPLIED,
    PLAN_STATUS_DISMISSED,
    PLAN_STATUS_STALE,
)
from app.models.entry import Entry

CHAT_URL = "/api/v1/chat"
DAY = date(2026, 8, 31)


def answer_with(plan: dict[str, object], prose: str = "Записал.") -> str:
    """Ответ модели: слова человеку и блок JSON рядом, как просит промпт."""
    return f"{prose}\n\n```json\n{json.dumps({'plan': plan}, ensure_ascii=False)}\n```"


@pytest.mark.asyncio
class TestParsing:
    """Как план достаётся из ответа — и что бывает, когда не достаётся."""

    def test_a_fenced_block_in_prose_is_found(self) -> None:
        plan = parse_plan(
            answer_with(
                {
                    "entry_date": DAY.isoformat(),
                    "metrics": [
                        {
                            "op": "log_metric",
                            "category_id": 1,
                            "field_id": 7,
                            "value": 30,
                            "source_text": "отжался 30 раз",
                        }
                    ],
                }
            )
        )
        assert plan.entry_date == DAY
        assert plan.operation_count() == 1

    def test_the_plan_is_taken_from_the_last_object_of_the_answer(self) -> None:
        """
        Ответ бывает не одним объектом — берётся последний, несущий `plan`.

        Прежний разбор вырезал кусок от первой открывающей скобки до последней
        закрывающей во всём тексте. Ответ, где перед планом стоит ещё один
        объект — процитированный, обсуждаемый, оставшийся от прошлого захода, —
        давал span с двумя объектами и прозой между ними, то есть битый JSON и
        молчаливое отсутствие плашки.
        """
        plan = parse_plan(
            'Ты просил {"query": "day_card"} — вот что вышло.\n\n'
            + answer_with(
                {
                    "entry_date": DAY.isoformat(),
                    "journal": {"op": "write_journal", "content": "день прошёл"},
                }
            )
        )
        assert plan.entry_date == DAY
        assert plan.journal is not None

    def test_an_object_without_a_plan_key_does_not_shadow_the_one_with_it(
        self,
    ) -> None:
        """Последним берётся не любой объект, а тот, в котором план есть."""
        plan = parse_plan(
            answer_with(
                {
                    "entry_date": DAY.isoformat(),
                    "journal": {"op": "write_journal", "content": "день прошёл"},
                }
            )
            + '\n\nА `{"need": [...]}` я больше не прошу.'
        )
        assert plan.journal is not None

    async def test_an_answer_without_a_block_carries_no_plan(self) -> None:
        """Самый частый случай разговора: просто ответ словами."""
        assert await plan_from_answer("Понял, ничего записывать не надо.") is None

    async def test_a_broken_plan_leaves_the_turn_standing(self) -> None:
        """
        Сломанный JSON — это отсутствие плашки, а не упавший ход.

        Ремонт здесь не настроен, поэтому первый же отказ и есть окончательный;
        важно, что наружу он выходит как `None`, а не как исключение.
        """
        answer = 'Записал.\n\n```json\n{"plan": {"entry_date": "не дата"}}\n```'
        assert await plan_from_answer(answer) is None

    def test_a_plan_with_no_operations_is_not_a_plan(self) -> None:
        """Плашка без операций нарисовала бы кнопку, которая ничего не делает."""
        with pytest.raises(ChatPlanError):
            parse_plan(answer_with({"entry_date": DAY.isoformat()}))

    async def test_an_answer_that_tries_to_untick_produces_no_card(self) -> None:
        """
        «Убери вчерашнюю отметку про бег» не превращается в план.

        Даже если модель ответит мимо инструкции и выпишет операцию снятия
        отметки, схема её не примет: `extra="forbid"` на плане и на каждой
        операции превращает выдуманное слово в отказ, а отказ — в отсутствие
        плашки. Ни одной записи при этом не появляется, потому что появляться
        нечему: применять нечего.
        """
        answer = answer_with(
            {
                "entry_date": DAY.isoformat(),
                "checklist": [
                    {
                        "op": "uncheck",
                        "category_id": 2,
                        "field_id": 9,
                        "source_text": "убери отметку про бег",
                    }
                ],
            }
        )
        assert await plan_from_answer(answer) is None

    async def test_an_answer_that_tries_to_replace_the_day_text_produces_no_card(
        self,
    ) -> None:
        """
        Замена текста дня — тоже W2, и её нет в `mode`.

        `JournalOp` экрана разбора дня умеет сказать `replace`; план чата — нет.
        Разница существенна: `replace` теряет уже написанное.
        """
        answer = answer_with(
            {
                "entry_date": DAY.isoformat(),
                "journal": {
                    "op": "write_journal",
                    "content": "новый текст",
                    "mode": "replace",
                },
            }
        )
        assert await plan_from_answer(answer) is None

    async def test_the_repair_pass_is_asked_exactly_once(self) -> None:
        """Модель, промахнувшаяся дважды, не сходится — второго круга нет."""
        calls: list[str] = []

        async def repair(prompt: str) -> str:
            calls.append(prompt)
            return "всё ещё не JSON"

        answer = 'Записал.\n\n```json\n{"plan": {"entry_date": "не дата"}}\n```'
        assert await plan_from_answer(answer, repair=repair) is None
        assert len(calls) == 1


async def make_checklist_category(client: AsyncClient, name: str) -> tuple[int, int]:
    """Чеклистовая категория с одной галочкой."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "display_mode": "checklist",
            "fields": [{"name": "Витамины", "field_type": "boolean", "order": 1}],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return int(body["id"]), int(body["fields"][0]["id"])


async def make_number_category(client: AsyncClient, name: str) -> tuple[int, int]:
    """Обычная категория с числовым полем."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "fields": [{"name": "Повторы", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return int(body["id"]), int(body["fields"][0]["id"])


async def store_plan(
    client: AsyncClient, db_session: AsyncSession, plan: dict[str, object]
) -> int:
    """
    Положить план так, как его кладёт ход, и вернуть его идентификатор.

    Ход в тесте не гоняется: он требует бэкенда модели, а проверяется здесь то,
    что происходит после ответа. Сообщение и план пишутся тем же кодом, которым
    их пишет `_attach_plan`.
    """
    from app.crud import chat as chat_crud

    conversation = await client.post(f"{CHAT_URL}/conversations", json={})
    assert conversation.status_code == 201
    conversation_id = int(conversation.json()["id"])

    seq = await chat_crud.next_seq(db_session, conversation_id)
    message = await chat_crud.add_message(
        db_session,
        conversation_id=conversation_id,
        seq=seq,
        role=MESSAGE_ROLE_ASSISTANT,
        content="Записал.",
    )
    row = await chat_crud.save_plan(
        db_session,
        message_id=message.id,
        entry_date=date.fromisoformat(str(plan["entry_date"])),
        plan=plan,
    )
    await db_session.commit()
    return row.id


@pytest.mark.asyncio
class TestApply:
    """Применение: тот же транзакционный путь, что у экрана разбора дня."""

    async def test_two_ticks_become_exactly_two_records(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """«Отжался 30 раз и выпил витамины» — две записи и ни одной лишней."""
        sport_id, reps_id = await make_number_category(client, "Спорт")
        vitamins_id, vitamin_field_id = await make_checklist_category(
            client, "Витамины"
        )
        plan = {
            "entry_date": DAY.isoformat(),
            "metrics": [
                {
                    "op": "log_metric",
                    "category_id": sport_id,
                    "field_id": reps_id,
                    "value": 30,
                    "source_text": "отжался 30 раз",
                }
            ],
            "checklist": [
                {
                    "op": "check",
                    "category_id": vitamins_id,
                    "field_id": vitamin_field_id,
                    "source_text": "выпил витамины",
                }
            ],
        }
        plan_id = await store_plan(client, db_session, plan)

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply",
            json={"metrics": plan["metrics"], "checklist": plan["checklist"]},
            headers={"Idempotency-Key": "chat-plan-1"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["applied_operations"] == 2
        assert body["plan"]["status"] == PLAN_STATUS_APPLIED
        assert body["plan"]["applied_at"] is not None

        count = await db_session.execute(
            select(func.count()).select_from(Entry).where(Entry.entry_date == DAY)
        )
        assert count.scalar_one() == 2

    async def test_a_second_tap_writes_nothing_and_answers_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        sport_id, reps_id = await make_number_category(client, "Спорт")
        metrics = [
            {
                "op": "log_metric",
                "category_id": sport_id,
                "field_id": reps_id,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]
        plan_id = await store_plan(
            client, db_session, {"entry_date": DAY.isoformat(), "metrics": metrics}
        )
        headers = {"Idempotency-Key": "chat-plan-repeat"}

        first = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply",
            json={"metrics": metrics},
            headers=headers,
        )
        assert first.status_code == 201

        before = (
            await db_session.execute(select(func.count()).select_from(Entry))
        ).scalar_one()
        second = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply",
            json={"metrics": metrics},
            headers=headers,
        )
        assert second.status_code == 200
        after = (
            await db_session.execute(select(func.count()).select_from(Entry))
        ).scalar_one()
        assert after == before

    async def test_an_operation_that_was_not_shown_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Применить можно подмножество показанного и ничего сверх него.

        Иначе плашка была бы просто ещё одним путём записи в базу, а строка
        `chat_plans` не доказывала бы, что применено ровно то, что было видно.
        """
        sport_id, reps_id = await make_number_category(client, "Спорт")
        shown = {
            "op": "log_metric",
            "category_id": sport_id,
            "field_id": reps_id,
            "value": 30,
            "source_text": "отжался 30 раз",
        }
        plan_id = await store_plan(
            client, db_session, {"entry_date": DAY.isoformat(), "metrics": [shown]}
        )

        smuggled = {**shown, "value": 300}
        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"metrics": [smuggled]}
        )
        assert response.status_code == 422
        assert "показан" in response.json()["detail"]

    async def test_unticking_a_row_writes_only_what_is_left(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Снятая на плашке галочка не записывается."""
        sport_id, reps_id = await make_number_category(client, "Спорт")
        vitamins_id, vitamin_field_id = await make_checklist_category(
            client, "Витамины"
        )
        metrics = [
            {
                "op": "log_metric",
                "category_id": sport_id,
                "field_id": reps_id,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]
        checklist = [
            {
                "op": "check",
                "category_id": vitamins_id,
                "field_id": vitamin_field_id,
                "source_text": "выпил витамины",
            }
        ]
        plan_id = await store_plan(
            client,
            db_session,
            {
                "entry_date": DAY.isoformat(),
                "metrics": metrics,
                "checklist": checklist,
            },
        )

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"metrics": metrics}
        )
        assert response.status_code == 201
        assert response.json()["applied_operations"] == 1

        count = await db_session.execute(
            select(func.count()).select_from(Entry).where(Entry.entry_date == DAY)
        )
        assert count.scalar_one() == 1

    async def test_a_tick_in_a_form_category_is_refused_with_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Тот же код, что у экрана разбора дня.

        Галку умеет ставить не только чат: `PUT /entries/checklist` существует
        раньше и отвечает 422 на не-checklist категорию. Та же ошибка, пришедшая
        через план чата, не становится другой ошибкой.
        """
        form_id, number_id = await make_number_category(client, "Спорт")
        boolean = await client.post(
            f"/api/v1/categories/{form_id}/fields",
            json={"name": "Размялся", "field_type": "boolean", "order": 2},
        )
        assert boolean.status_code == 201
        checklist = [
            {
                "op": "check",
                "category_id": form_id,
                "field_id": int(boolean.json()["id"]),
                "source_text": "размялся",
            }
        ]
        plan_id = await store_plan(
            client,
            db_session,
            {"entry_date": DAY.isoformat(), "checklist": checklist},
        )

        response = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply", json={"checklist": checklist}
        )
        assert response.status_code == 422

    async def test_applying_a_plan_stales_the_other_one_of_that_date(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        sport_id, reps_id = await make_number_category(client, "Спорт")
        metrics = [
            {
                "op": "log_metric",
                "category_id": sport_id,
                "field_id": reps_id,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]
        payload = {"entry_date": DAY.isoformat(), "metrics": metrics}
        older = await store_plan(client, db_session, payload)
        newer = await store_plan(client, db_session, payload)

        applied = await client.post(
            f"{CHAT_URL}/plans/{newer}/apply", json={"metrics": metrics}
        )
        assert applied.status_code == 201

        stale = await client.get(f"{CHAT_URL}/plans/{older}")
        assert stale.json()["status"] == PLAN_STATUS_STALE

        blocked = await client.post(
            f"{CHAT_URL}/plans/{older}/apply", json={"metrics": metrics}
        )
        assert blocked.status_code == 409

    async def test_the_applied_fact_survives_the_receipt_being_deleted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        `applied_summary_id` стоит без внешнего ключа намеренно.

        Удаление квитанции из `applied_daily_summaries` не должно стирать факт,
        что план применяли: разговор — это история, и она не переписывается
        уборкой в другой таблице.
        """
        sport_id, reps_id = await make_number_category(client, "Спорт")
        metrics = [
            {
                "op": "log_metric",
                "category_id": sport_id,
                "field_id": reps_id,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]
        plan_id = await store_plan(
            client, db_session, {"entry_date": DAY.isoformat(), "metrics": metrics}
        )
        applied = await client.post(
            f"{CHAT_URL}/plans/{plan_id}/apply",
            json={"metrics": metrics},
            headers={"Idempotency-Key": "chat-plan-receipt"},
        )
        assert applied.status_code == 201
        assert applied.json()["plan"]["applied_summary_id"] is not None

        await db_session.execute(delete(AppliedDailySummary))
        await db_session.commit()

        still = await client.get(f"{CHAT_URL}/plans/{plan_id}")
        assert still.json()["status"] == PLAN_STATUS_APPLIED
        assert still.json()["applied_at"] is not None


@pytest.mark.asyncio
class TestReadAndDismiss:
    """План живёт дольше хода, в котором прозвучал."""

    async def test_a_plan_from_two_turns_ago_reads_back_unchanged(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        sport_id, reps_id = await make_number_category(client, "Спорт")
        metrics = [
            {
                "op": "log_metric",
                "category_id": sport_id,
                "field_id": reps_id,
                "value": 30,
                "source_text": "отжался 30 раз",
            }
        ]
        plan_id = await store_plan(
            client, db_session, {"entry_date": DAY.isoformat(), "metrics": metrics}
        )

        response = await client.get(f"{CHAT_URL}/plans/{plan_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["plan"]["metrics"][0]["value"] == 30
        assert body["plan"]["entry_date"] == DAY.isoformat()
        assert body["operation_count"] == 1

    async def test_the_feed_points_at_the_plan_of_its_message(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Плашка ищется по ленте, а не отдельным запросом на каждое сообщение."""
        from app.crud import chat as chat_crud

        sport_id, reps_id = await make_number_category(client, "Спорт")
        conversation = await client.post(f"{CHAT_URL}/conversations", json={})
        conversation_id = int(conversation.json()["id"])
        message = await chat_crud.add_message(
            db_session,
            conversation_id=conversation_id,
            seq=1,
            role=MESSAGE_ROLE_ASSISTANT,
            content="Записал.",
        )
        row = await chat_crud.save_plan(
            db_session,
            message_id=message.id,
            entry_date=DAY,
            plan={
                "entry_date": DAY.isoformat(),
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": sport_id,
                        "field_id": reps_id,
                        "value": 30,
                        "source_text": "отжался 30 раз",
                    }
                ],
            },
        )
        await db_session.commit()

        detail = await client.get(f"{CHAT_URL}/conversations/{conversation_id}")
        assert detail.status_code == 200
        assert [one["plan_id"] for one in detail.json()["messages"]] == [row.id]

    async def test_dismiss_leaves_the_plan_as_a_fact(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """«Что мне предлагали и что я не взял» читается только по строке."""
        sport_id, reps_id = await make_number_category(client, "Спорт")
        plan_id = await store_plan(
            client,
            db_session,
            {
                "entry_date": DAY.isoformat(),
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": sport_id,
                        "field_id": reps_id,
                        "value": 30,
                        "source_text": "отжался 30 раз",
                    }
                ],
            },
        )

        response = await client.post(f"{CHAT_URL}/plans/{plan_id}/dismiss")
        assert response.status_code == 204

        after = await client.get(f"{CHAT_URL}/plans/{plan_id}")
        assert after.json()["status"] == PLAN_STATUS_DISMISSED
