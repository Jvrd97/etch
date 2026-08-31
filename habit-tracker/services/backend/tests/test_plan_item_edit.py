"""
Tests for the per-item editor of the plan: PATCH, POST, DELETE of one line.

Every acceptance case of `#110` that is about editing rather than about order:
a window edited on the page survives a re-read under the same id, editing the
text does not drop the mark of `#88`, a new item lands at the end of its level,
deleting a task takes its `minimum` with it, an edit that breaks a rule of the
document passes with a warning, and an edit that breaks a `CHECK` is refused
with the code of the rule and the line.
"""

# [review:need-review] PHASE-03/110
# summary: API tests for editing one plan item — the id and the mark that survive a patch, the child that leaves with its parent, the asymmetry between a rule the database enforces (422) and a rule of the document a human is only warned about (200 + warnings), and the two tabs that write over each other without breeding a second row
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.models.plan import EDITED_BY_HUMAN, PlanItem

DAY_URL = "/api/v1/day"

# The same Monday `#87` tests: four work tasks under the current canon.
PLAN_DAY = date(2026, 8, 31)
PLAN_URL = f"{DAY_URL}/{PLAN_DAY.isoformat()}/plan"
ITEMS_URL = f"{PLAN_URL}/items"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The canon rows and goal 1 of the quarter — see `tests/test_plan_post.py`."""
    await day_crud.seed_rules(db_session)
    yield


def task(code: str, window: str = "09:00-10:00", **overrides: Any) -> dict[str, Any]:
    """A task that satisfies every row-level rule, before a test breaks one."""
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


async def seed_plan(client: AsyncClient, sections: list[dict[str, Any]]) -> Any:
    """Put a plan on the day and hand back what the server stored."""
    response = await client.post(
        PLAN_URL,
        json={"title": "План 2026-08-31 (пн)", "sections": sections},
    )
    assert response.status_code == 201, response.text
    return response.json()


def only_section(plan: dict[str, Any]) -> dict[str, Any]:
    """The single section of a one-section plan."""
    return plan["sections"][0]


async def one_work_task(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """A plan of one work section with one task; hands back the plan and the item."""
    plan = await seed_plan(
        client, [{"title": "Работа", "kind": "work", "items": [task("W1")]}]
    )
    return plan, only_section(plan)["items"][0]


class TestPatchOneItem:
    """Правка пункта: id жив, отметка жива, поля меняются по одному."""

    async def test_the_window_is_edited_and_the_item_keeps_its_id(
        self, client: AsyncClient
    ) -> None:
        """
        Первый пункт Acceptance: окно правится, а `plan_item.id` тот же.

        Id проверяется не из аккуратности: на нём висят отметки #88 и записи
        #150, и правка, которая его меняет, — это не правка, а замена.
        """
        _, item = await one_work_task(client)

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"window": "11:00-12:30"}
        )

        assert response.status_code == 200, response.text
        edited = response.json()["item"]
        assert edited["id"] == item["id"]
        # Сравнение через расписание, а не через строку: окно приходит из «ЧЧ:ММ»
        # по местным часам дня, а хранится и отдаётся в UTC, и сверять его с
        # набранным текстом значило бы вписать в тест смещение зоны.
        window = next(
            entry
            for entry in response.json()["plan"]["schedule"]
            if entry["item_id"] == item["id"]
        )
        assert window["minutes"] == 90
        assert edited["starts_at"] != item["starts_at"]

        reread = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        stored = only_section(reread.json()["plan"])["items"][0]
        assert stored["id"] == item["id"]
        assert stored["starts_at"] == edited["starts_at"]

    async def test_a_field_that_was_not_sent_is_not_touched(
        self, client: AsyncClient
    ) -> None:
        """
        «Не прислали» и «обнулили» — разные приказы.

        Патч из одного поля не имеет права стереть остальные: иначе правка
        слова в тексте снимала бы у задачи критерий и окно, а с ними — и право
        существовать по `CHECK`.
        """
        _, item = await one_work_task(client)

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"text_md": "Задача W1, переписанная"}
        )

        assert response.status_code == 200, response.text
        edited = response.json()["item"]
        assert edited["text_md"] == "Задача W1, переписанная"
        assert edited["text_plain"] == "Задача W1, переписанная"
        assert edited["done_criterion"] == "письмо отправлено"
        assert edited["starts_at"] == item["starts_at"]

    async def test_null_in_the_body_clears_the_field(self, client: AsyncClient) -> None:
        """`null` — это «убрать значение», и на пункте, которому оно позволено."""
        plan = await seed_plan(
            client,
            [
                {
                    "title": "Вечер",
                    "kind": "evening",
                    "items": [
                        {
                            "kind": "bullet",
                            "text_md": "Прогулка",
                            "why_md": "чтобы не сидеть",
                        }
                    ],
                }
            ],
        )
        item = only_section(plan)["items"][0]

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"why_md": None}
        )

        assert response.status_code == 200, response.text
        assert response.json()["item"]["why_md"] is None

    async def test_editing_the_text_does_not_drop_the_mark(
        self, client: AsyncClient
    ) -> None:
        """
        Второй пункт Acceptance: правка текста не сбрасывает отметку #88.

        Ровно то, чего не умеет `POST .../plan`: он сносит план и кладёт новый,
        а отметку переносит только у строк, приславших свой id обратно.
        """
        _, item = await one_work_task(client)
        marked = await client.put(
            f"{DAY_URL}/{PLAN_DAY.isoformat()}/marks/{item['id']}",
            json={"state": "done", "note": "сделал до обеда", "source": "web"},
        )
        assert marked.status_code == 200, marked.text

        await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"text_md": "Задача W1 (уточнил)"}
        )

        reread = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        marks = {mark["item_id"]: mark for mark in reread.json()["marks"]}
        assert marks[item["id"]]["state"] == "done"
        assert marks[item["id"]]["note"] == "сделал до обеда"

    async def test_an_edit_records_who_made_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Правка отмечается как человеческая — на это опирается #150 и #147."""
        _, item = await one_work_task(client)

        await client.patch(f"{ITEMS_URL}/{item['id']}", json={"code": "W1a"})

        stored = await db_session.get(PlanItem, item["id"])
        assert stored is not None
        await db_session.refresh(stored)
        assert stored.edited_by == EDITED_BY_HUMAN

    async def test_an_item_of_another_day_is_a_404(self, client: AsyncClient) -> None:
        """Пункт адресуется как «эта строка этого дня»; чужой id — 404."""
        _, item = await one_work_task(client)

        response = await client.patch(
            f"{DAY_URL}/2026-08-30/plan/items/{item['id']}", json={"code": "W9"}
        )

        assert response.status_code == 404

    async def test_two_tabs_editing_the_same_item_leave_one_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Девятый пункт Acceptance: пункта-призрака не появляется.

        Две вкладки пишут по одному и тому же id, побеждает последняя, и вторая
        строка не заводится — адресация по id этого просто не допускает.
        """
        _, item = await one_work_task(client)

        first = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"text_md": "из первой вкладки"}
        )
        second = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"text_md": "из второй вкладки"}
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["item"]["text_md"] == "из второй вкладки"
        rows = await db_session.execute(
            select(func.count()).select_from(PlanItem).where(PlanItem.id == item["id"])
        )
        assert rows.scalar_one() == 1


class TestDatabaseRefusesWhatCheckRefuses:
    """Отказ остаётся там, где отказывает сам `CHECK`, — и называет правило."""

    async def test_removing_the_criterion_of_a_task_is_a_422_naming_the_rule(
        self, client: AsyncClient
    ) -> None:
        """
        Восьмой пункт Acceptance: 422 с кодом правила, а не «validation error».

        `CHECK` — граница для всех писателей сразу, и правка человека её не
        двигает: задача без критерия «Сделано» не задача, а пожелание.
        """
        _, item = await one_work_task(client)

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"done_criterion": None}
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "task_without_window_or_criterion"

    async def test_a_window_on_a_free_item_is_refused(
        self, client: AsyncClient
    ) -> None:
        """Свободный вечер физически нерасписуем — это `CHECK`, а не уговор."""
        plan = await seed_plan(
            client,
            [
                {
                    "title": "Свободное",
                    "kind": "free",
                    "items": [
                        {"kind": "bullet", "rigidity": "free", "text_md": "Что захочу"}
                    ],
                }
            ],
        )
        item = only_section(plan)["items"][0]

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"window": "20:00-21:00"}
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "free_item_has_window"

    async def test_a_refused_edit_leaves_the_item_as_it_was(
        self, client: AsyncClient
    ) -> None:
        """Отказ ничего не портит: пункт остаётся тем, чем был до правки."""
        _, item = await one_work_task(client)

        await client.patch(f"{ITEMS_URL}/{item['id']}", json={"done_criterion": None})

        reread = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        stored = only_section(reread.json()["plan"])["items"][0]
        assert stored["done_criterion"] == "письмо отправлено"


class TestHumanIsWarnedWhereMachineIsRefused:
    """Асимметрия строгости: правило документа человеку не запрещает, а сообщает."""

    async def test_a_fifth_task_added_by_hand_passes_with_a_warning(
        self, client: AsyncClient
    ) -> None:
        """
        Седьмой пункт Acceptance в его сути: правка проходит, канон сообщает.

        Тот же документ, присланный машиной, получил бы 422 `too_many_tasks` —
        это проверено в `tests/test_plan_post.py`. Здесь человек добавляет
        пятую задачу руками, получает 200, и правило приезжает предупреждением.
        """
        plan = await seed_plan(
            client,
            [
                {
                    "title": "Работа",
                    "kind": "work",
                    "items": [
                        task(f"W{index}", f"0{index}:00-0{index}:30")
                        for index in range(1, 5)
                    ],
                }
            ],
        )
        section_id = only_section(plan)["id"]

        response = await client.post(
            f"{PLAN_URL}/sections/{section_id}/items",
            json={
                "kind": "task",
                "code": "W5",
                "text_md": "Пятая задача",
                "window": "18:00-19:00",
                "done_criterion": "письмо отправлено",
                "quarter_goal_id": 1,
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["item"]["code"] == "W5"
        assert [warning["error"] for warning in body["warnings"]] == ["too_many_tasks"]
        assert body["warnings"][0]["item_code"] == "W5"

    async def test_an_edit_that_breaks_nothing_carries_no_warnings(
        self, client: AsyncClient
    ) -> None:
        """Пустой список — правка ничего не нарушила, и это тоже ответ."""
        _, item = await one_work_task(client)

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"window": "13:00-14:00"}
        )

        assert response.json()["warnings"] == []

    async def test_a_task_that_calls_itself_hard_is_warned_not_refused(
        self, client: AsyncClient
    ) -> None:
        """
        «Жёсткими бывают только края дня» — правило документа, не строки.

        Машине оно запрещает запись; человеку сообщает, потому что решение «эта
        встреча всё-таки неподвижна» принимает он, а не валидатор.
        """
        _, item = await one_work_task(client)

        response = await client.patch(
            f"{ITEMS_URL}/{item['id']}", json={"rigidity": "hard"}
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["item"]["rigidity"] == "hard"
        assert [warning["error"] for warning in body["warnings"]] == [
            "hard_is_not_an_edge"
        ]


class TestAddAndDelete:
    """Пункт заводится в конец уровня и уходит вместе с детьми."""

    async def test_a_new_item_lands_at_the_end_of_the_section(
        self, client: AsyncClient
    ) -> None:
        """Третий пункт Acceptance: новый пункт встаёт в конец, `ord` цел."""
        plan = await seed_plan(
            client,
            [
                {
                    "title": "Вечер",
                    "kind": "evening",
                    "items": [
                        {"kind": "bullet", "text_md": "Первый"},
                        {"kind": "bullet", "text_md": "Второй"},
                    ],
                }
            ],
        )
        section_id = only_section(plan)["id"]

        response = await client.post(
            f"{PLAN_URL}/sections/{section_id}/items",
            json={"kind": "bullet", "text_md": "Третий"},
        )

        assert response.status_code == 201, response.text
        items = only_section(response.json()["plan"])["items"]
        assert [item["text_md"] for item in items] == ["Первый", "Второй", "Третий"]
        assert [item["ord"] for item in items] == [0, 1, 2]

    async def test_a_child_is_created_under_its_parent(
        self, client: AsyncClient
    ) -> None:
        """«Минимум» заводится ребёнком и получает свою галку, как в #88."""
        plan = await seed_plan(
            client,
            [{"title": "Тренировка", "kind": "training", "items": [task("T1")]}],
        )
        section = only_section(plan)
        parent = section["items"][0]

        response = await client.post(
            f"{PLAN_URL}/sections/{section['id']}/items",
            json={
                "kind": "minimum",
                "text_md": "Минимум: 20 приседаний",
                "parent_id": parent["id"],
            },
        )

        assert response.status_code == 201, response.text
        stored = only_section(response.json()["plan"])["items"][0]
        assert [child["text_md"] for child in stored["children"]] == [
            "Минимум: 20 приседаний"
        ]

    async def test_deleting_a_task_takes_its_minimum_with_it(
        self, client: AsyncClient
    ) -> None:
        """
        Четвёртый пункт Acceptance: сирот в секции не остаётся.

        Минимум без своей задачи — пункт, который никто не сделает и который
        29 августа уже показало на экране как отдельную строку ниоткуда.
        """
        plan = await seed_plan(
            client,
            [
                {
                    "title": "Тренировка",
                    "kind": "training",
                    "items": [
                        task(
                            "T1",
                            children=[
                                {"kind": "minimum", "text_md": "Минимум: 20 приседаний"}
                            ],
                        )
                    ],
                }
            ],
        )
        parent = only_section(plan)["items"][0]

        response = await client.delete(f"{ITEMS_URL}/{parent['id']}")

        assert response.status_code == 200, response.text
        assert response.json()["item"] is None
        assert only_section(response.json()["plan"])["items"] == []

        reread = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        assert only_section(reread.json()["plan"])["items"] == []

    async def test_deleting_closes_the_gap_in_ord(self, client: AsyncClient) -> None:
        """Уровень смыкается: дыра в `ord` — это дыра и в порядке на экране."""
        plan = await seed_plan(
            client,
            [
                {
                    "title": "Вечер",
                    "kind": "evening",
                    "items": [
                        {"kind": "bullet", "text_md": name}
                        for name in ("Первый", "Второй", "Третий")
                    ],
                }
            ],
        )
        middle = only_section(plan)["items"][1]

        response = await client.delete(f"{ITEMS_URL}/{middle['id']}")

        items = only_section(response.json()["plan"])["items"]
        assert [item["text_md"] for item in items] == ["Первый", "Третий"]
        assert [item["ord"] for item in items] == [0, 1]

    async def test_deleting_an_item_that_is_not_there_is_a_404(
        self, client: AsyncClient
    ) -> None:
        """Удаление того, чего нет, — 404, а не тихое «готово»."""
        await one_work_task(client)

        response = await client.delete(
            f"{ITEMS_URL}/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404

    async def test_a_section_of_another_day_is_a_404(self, client: AsyncClient) -> None:
        """Секция адресуется внутри дня; чужая — 404, а не тихая запись в чужой план."""
        plan = await seed_plan(
            client, [{"title": "Работа", "kind": "work", "items": [task("W1")]}]
        )
        section_id = only_section(plan)["id"]

        response = await client.post(
            f"{DAY_URL}/2026-08-30/plan/sections/{section_id}/items",
            json={"kind": "bullet", "text_md": "Не туда"},
        )

        assert response.status_code == 404
