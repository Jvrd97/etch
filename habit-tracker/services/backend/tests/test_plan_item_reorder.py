"""
Tests for POST /api/v1/day/{date}/plan/items/{id}/move — the order of a plan.

The acceptance cases of `#110` that are about place rather than content: an item
dragged from the fourth position to the first leaves a section without holes and
without twins, the same order comes back on a re-read, an item moved to another
section leaves the old one in a single request, and a position past the end
means "to the end" rather than a refusal.
"""

# [review:need-review] PHASE-03/110
# summary: API tests for moving one plan item — a level renumbered whole rather than one `ord` written at a time, the source level closed behind a departing item, a child that moves under another parent, and the refusals that stay refusals (an item as its own parent, a section of another day)
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud

DAY_URL = "/api/v1/day"
PLAN_DAY = date(2026, 8, 31)
PLAN_URL = f"{DAY_URL}/{PLAN_DAY.isoformat()}/plan"

FOUR = ("Первый", "Второй", "Третий", "Четвёртый")


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The canon rows and goal 1 of the quarter — see `tests/test_plan_post.py`."""
    await day_crud.seed_rules(db_session)
    yield


def bullet(text: str, **overrides: Any) -> dict[str, Any]:
    """A line with nothing to break: no window, no criterion, no goal."""
    item: dict[str, Any] = {"kind": "bullet", "text_md": text}
    item.update(overrides)
    return item


async def seed(client: AsyncClient, sections: list[dict[str, Any]]) -> Any:
    """Put a plan on the day and hand back what the server stored."""
    response = await client.post(
        PLAN_URL, json={"title": "План 2026-08-31 (пн)", "sections": sections}
    )
    assert response.status_code == 201, response.text
    return response.json()


def texts(section: dict[str, Any]) -> list[str]:
    """The texts of a section's top level, in the order the server returned."""
    return [item["text_md"] for item in section["items"]]


def ords(section: dict[str, Any]) -> list[int]:
    """The `ord` of a section's top level, in the order the server returned."""
    return [item["ord"] for item in section["items"]]


async def four_lines(client: AsyncClient) -> tuple[str, list[dict[str, Any]]]:
    """One evening section of four plain lines; hands back its id and its items."""
    plan = await seed(
        client,
        [{"title": "Вечер", "kind": "evening", "items": [bullet(one) for one in FOUR]}],
    )
    section = plan["sections"][0]
    return section["id"], section["items"]


class TestMoveInsideOneSection:
    """Перестановка внутри уровня: без дыр, без дублей, тем же чтением."""

    async def test_the_fourth_item_dragged_to_the_top_renumbers_the_level(
        self, client: AsyncClient
    ) -> None:
        """
        Пятый пункт Acceptance: `ord` без дыр и без дублей после перетаскивания.

        Перенумеровывается уровень целиком, а не одна строка: построчная запись
        `ord` на середине последовательности — это и есть та дыра, ради которой
        перестановка сделана отдельной операцией, а не полем в патче.
        """
        section_id, items = await four_lines(client)
        fourth = items[3]

        response = await client.post(
            f"{PLAN_URL}/items/{fourth['id']}/move",
            json={"section_id": section_id, "position": 0},
        )

        assert response.status_code == 200, response.text
        section = response.json()["plan"]["sections"][0]
        assert texts(section) == ["Четвёртый", "Первый", "Второй", "Третий"]
        assert ords(section) == [0, 1, 2, 3]

    async def test_the_new_order_survives_a_re_read(self, client: AsyncClient) -> None:
        """Тот же пункт Acceptance: повторное чтение отдаёт тот же порядок."""
        section_id, items = await four_lines(client)

        await client.post(
            f"{PLAN_URL}/items/{items[3]['id']}/move",
            json={"section_id": section_id, "position": 0},
        )

        reread = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        section = reread.json()["plan"]["sections"][0]
        assert texts(section) == ["Четвёртый", "Первый", "Второй", "Третий"]
        assert ords(section) == [0, 1, 2, 3]

    async def test_a_position_past_the_end_means_the_end(
        self, client: AsyncClient
    ) -> None:
        """
        Перетаскивание в пустоту под последней строкой — это «в конец».

        Отвечать на него 422 значило бы спорить с рукой: ниже последнего пункта
        места нет ни у одного экрана, и промах туда имеет ровно одно значение.
        """
        section_id, items = await four_lines(client)

        response = await client.post(
            f"{PLAN_URL}/items/{items[0]['id']}/move",
            json={"section_id": section_id, "position": 99},
        )

        section = response.json()["plan"]["sections"][0]
        assert texts(section) == ["Второй", "Третий", "Четвёртый", "Первый"]
        assert ords(section) == [0, 1, 2, 3]

    async def test_moving_an_item_onto_its_own_place_changes_nothing(
        self, client: AsyncClient
    ) -> None:
        """Перенос на своё же место — не ошибка и не перестановка соседей."""
        section_id, items = await four_lines(client)

        response = await client.post(
            f"{PLAN_URL}/items/{items[1]['id']}/move",
            json={"section_id": section_id, "position": 1},
        )

        section = response.json()["plan"]["sections"][0]
        assert texts(section) == list(FOUR)
        assert ords(section) == [0, 1, 2, 3]


class TestMoveBetweenSections:
    """Перенос в другую секцию — один запрос, оба уровня в порядке."""

    async def test_an_item_leaves_the_old_section_and_appears_in_the_new_one(
        self, client: AsyncClient
    ) -> None:
        """
        Шестой пункт Acceptance: исчезает из старой, появляется в новой.

        Одним запросом, потому что «удалить и создать» — это новый `id`, а с ним
        потерянная отметка #88 и потерянная история #150.
        """
        plan = await seed(
            client,
            [
                {
                    "title": "Вечер",
                    "kind": "evening",
                    "items": [bullet("Первый"), bullet("Второй")],
                },
                {"title": "Очередь", "kind": "queue", "items": [bullet("Ждёт")]},
            ],
        )
        evening, queue = plan["sections"]
        moving = evening["items"][0]

        response = await client.post(
            f"{PLAN_URL}/items/{moving['id']}/move",
            json={"section_id": queue["id"], "position": 0},
        )

        assert response.status_code == 200, response.text
        after_evening, after_queue = response.json()["plan"]["sections"]
        assert texts(after_evening) == ["Второй"]
        assert ords(after_evening) == [0]
        assert texts(after_queue) == ["Первый", "Ждёт"]
        assert ords(after_queue) == [0, 1]

    async def test_the_moved_item_keeps_its_id_and_its_mark(
        self, client: AsyncClient
    ) -> None:
        """Перенос — это место, а не новая строка: отметка остаётся на пункте."""
        plan = await seed(
            client,
            [
                {"title": "Вечер", "kind": "evening", "items": [bullet("Первый")]},
                {"title": "Очередь", "kind": "queue", "items": []},
            ],
        )
        evening, queue = plan["sections"]
        moving = evening["items"][0]
        await client.put(
            f"{DAY_URL}/{PLAN_DAY.isoformat()}/marks/{moving['id']}",
            json={"state": "done", "source": "web"},
        )

        response = await client.post(
            f"{PLAN_URL}/items/{moving['id']}/move",
            json={"section_id": queue["id"], "position": 0},
        )

        assert response.json()["item"]["id"] == moving["id"]
        reread = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        marks = {mark["item_id"]: mark for mark in reread.json()["marks"]}
        assert marks[moving["id"]]["state"] == "done"


class TestMoveAcrossLevels:
    """Уровень — это секция плюс родитель, и перенос умеет менять оба."""

    async def test_a_child_can_be_lifted_to_the_top_level(
        self, client: AsyncClient
    ) -> None:
        """Шаг, ставший самостоятельным пунктом, встаёт в уровень секции."""
        plan = await seed(
            client,
            [
                {
                    "title": "Вечер",
                    "kind": "evening",
                    "items": [
                        bullet("Родитель", children=[bullet("Ребёнок")]),
                        bullet("Сосед"),
                    ],
                }
            ],
        )
        section = plan["sections"][0]
        child = section["items"][0]["children"][0]

        response = await client.post(
            f"{PLAN_URL}/items/{child['id']}/move",
            json={"section_id": section["id"], "parent_id": None, "position": 0},
        )

        assert response.status_code == 200, response.text
        after = response.json()["plan"]["sections"][0]
        assert texts(after) == ["Ребёнок", "Родитель", "Сосед"]
        assert ords(after) == [0, 1, 2]
        assert after["items"][1]["children"] == []

    async def test_an_item_cannot_become_its_own_parent(
        self, client: AsyncClient
    ) -> None:
        """Пункт, ставший своим родителем, — это дерево без корня, и это 422."""
        section_id, items = await four_lines(client)
        first = items[0]

        response = await client.post(
            f"{PLAN_URL}/items/{first['id']}/move",
            json={
                "section_id": section_id,
                "parent_id": first["id"],
                "position": 0,
            },
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "item_cannot_parent_itself"

    async def test_a_parent_from_another_section_is_a_404(
        self, client: AsyncClient
    ) -> None:
        """
        Половина уровня из чужой секции уровнем не является.

        Родитель в одной секции, а пункт — в другой: такая пара рисуется на
        экране как строка, уехавшая из своего блока, и лечится отказом, а не
        тихой перевязкой.
        """
        plan = await seed(
            client,
            [
                {"title": "Вечер", "kind": "evening", "items": [bullet("Первый")]},
                {"title": "Очередь", "kind": "queue", "items": [bullet("Ждёт")]},
            ],
        )
        evening, queue = plan["sections"]

        response = await client.post(
            f"{PLAN_URL}/items/{evening['items'][0]['id']}/move",
            json={
                "section_id": evening["id"],
                "parent_id": queue["items"][0]["id"],
                "position": 0,
            },
        )

        assert response.status_code == 404

    async def test_a_section_of_another_day_is_a_404(self, client: AsyncClient) -> None:
        """Секция назначения адресуется внутри дня, как и всё остальное в плане."""
        section_id, items = await four_lines(client)

        response = await client.post(
            f"{DAY_URL}/2026-08-30/plan/items/{items[0]['id']}/move",
            json={"section_id": section_id, "position": 0},
        )

        assert response.status_code == 404
