"""
Tests for the plan and the quick marks meeting: `planned` and the order it buys.

Every acceptance case of `#130`. A day whose plan names buttons puts those
buttons first and marks them; a day without a plan gets the directory's own
order and nothing else; a tap on a planned button closes the plan item it
belongs to, so nobody marks the same thing twice; a button deleted after the
plan was written breaks neither the directory nor the plan; and a request for a
past date answers with the plan of *that* day.
"""

# [review:need-review] PHASE-03/130
# summary: API tests for the planned quick mark — the order the server decides (planned first, directory order inside each half), the flag the agent window reads through the same one selection, the plan item closed by a tap rather than by a second hand movement, the button deleted out from under a written plan, and the past date that answers with its own day
from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud

QUICK_MARKS_URL = "/api/v1/quick-marks"
DAY_URL = "/api/v1/day"

# A Monday under the current canon, the same one the plan tests use.
PLAN_DAY = date(2026, 8, 31)
YESTERDAY = date(2026, 8, 30)


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The canon rows and goal 1 — the plan is judged by them, see `#87`."""
    await day_crud.seed_rules(db_session)
    yield


async def make_category(client: AsyncClient, name: str) -> dict[str, Any]:
    """A form category with one number field."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "display_mode": "form",
            "fields": [{"name": "Объём", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_mark(client: AsyncClient, name: str, label: str, **over: Any) -> int:
    """A button over a fresh category; hands back its id."""
    category = await make_category(client, name)
    payload: dict[str, Any] = {
        "label": label,
        "category_id": category["id"],
        "field_id": int(category["fields"][0]["id"]),
        "kind": "increment",
        "step": 250,
        "unit_label": "мл",
    }
    payload.update(over)
    response = await client.post(QUICK_MARKS_URL, json=payload)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def put_plan(
    client: AsyncClient, on: date, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """One evening section carrying `items`; hands back the stored plan."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={
            "title": f"План {on.isoformat()}",
            "sections": [{"title": "Вечер", "kind": "evening", "items": items}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def line(text: str, **over: Any) -> dict[str, Any]:
    """A plain line of the plan; nothing in it can break a rule."""
    item: dict[str, Any] = {"kind": "bullet", "text_md": text}
    item.update(over)
    return item


async def server_day(client: AsyncClient) -> date:
    """
    Какой день сейчас у сервера.

    Спрашивается, а не вычисляется: тап всегда ложится в `local_date()` момента
    запроса, и тест, посчитавший день по календарю машины, разошёлся бы с
    сервером ровно между полуночью и часом начала дня — то есть в тот момент,
    ради которого граница суток и заведена.
    """
    response = await client.get(QUICK_MARKS_URL)
    assert response.status_code == 200, response.text
    return date.fromisoformat(response.json()[0]["entry_date"])


async def listed(client: AsyncClient, on: date | None = None) -> list[dict[str, Any]]:
    """The directory as the screen reads it, for `on` or for today."""
    url = QUICK_MARKS_URL if on is None else f"{QUICK_MARKS_URL}?date={on.isoformat()}"
    response = await client.get(url)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


class TestPlannedFirst:
    """Кнопки из плана — первыми и помеченными; без плана — порядок справочника."""

    async def test_a_button_named_by_the_plan_comes_first_and_is_marked(
        self, client: AsyncClient
    ) -> None:
        """
        Первый пункт Acceptance: плановые впереди и отличимы с одного взгляда.

        Порядок в справочнике обратный нарочно: если бы плановая кнопка и так
        стояла первой, тест доказывал бы только то, что список не перевернулся.
        """
        water = await make_mark(client, "Вода", "+250 мл", order=1)
        pushups = await make_mark(client, "Отжимания", "+10", order=2)
        await put_plan(client, PLAN_DAY, [line("Отжаться", quick_mark_id=pushups)])

        marks = await listed(client, PLAN_DAY)

        assert [one["id"] for one in marks] == [pushups, water]
        assert [one["planned"] for one in marks] == [True, False]
        assert marks[0]["plan_item_id"] is not None
        assert marks[1]["plan_item_id"] is None

    async def test_the_directory_order_survives_inside_each_half(
        self, client: AsyncClient
    ) -> None:
        """
        «Плановая» поднимает кнопку, а не перетасовывает её с соседками.

        Иначе порядок, который человек задал руками, каждое утро сменялся бы на
        порядок, в котором `/day-open` перечислил пункты.
        """
        first = await make_mark(client, "Вода", "+250 мл", order=1)
        second = await make_mark(client, "Отжимания", "+10", order=2)
        third = await make_mark(client, "Витамин D", "+1", order=3)
        fourth = await make_mark(client, "Чтение", "+10 стр", order=4)
        await put_plan(
            client,
            PLAN_DAY,
            [
                line("Витамин", quick_mark_id=third),
                line("Отжаться", quick_mark_id=second),
            ],
        )

        marks = await listed(client, PLAN_DAY)

        # Плановые — в порядке справочника (2, 3), а не плана (3, 2).
        assert [one["id"] for one in marks] == [second, third, first, fourth]

    async def test_a_day_without_a_plan_answers_with_the_directory_order(
        self, client: AsyncClient
    ) -> None:
        """
        Второй пункт Acceptance: ни пустого блока, ни сообщения о пропавшем плане.

        Ответ — тот же список, что и до этого тикета, и `planned` у всех False.
        """
        water = await make_mark(client, "Вода", "+250 мл", order=1)
        pushups = await make_mark(client, "Отжимания", "+10", order=2)

        marks = await listed(client, PLAN_DAY)

        assert [one["id"] for one in marks] == [water, pushups]
        assert not any(one["planned"] for one in marks)

    async def test_a_past_date_answers_with_the_plan_of_that_day(
        self, client: AsyncClient
    ) -> None:
        """
        Шестой пункт Acceptance: `date=` отдаёт план **того** дня.

        Кнопка в плане вчера и не в плане сегодня — это две разные выдачи, и
        путать их значит показывать вчерашний день сегодняшним.
        """
        pushups = await make_mark(client, "Отжимания", "+10", order=1)
        await put_plan(client, YESTERDAY, [line("Отжаться", quick_mark_id=pushups)])
        await put_plan(client, PLAN_DAY, [line("Ничего не отмечать")])

        yesterday = await listed(client, YESTERDAY)
        today = await listed(client, PLAN_DAY)

        assert yesterday[0]["planned"] is True
        assert today[0]["planned"] is False

    async def test_one_selection_serves_every_surface(
        self, client: AsyncClient
    ) -> None:
        """
        Пятый пункт Acceptance: у окна агента тот же признак и тот же порядок.

        Проверяется не второй ручкой, а тем, что второй выборки не существует:
        порядок и `planned` считает `list_quick_marks`, и любая поверхность —
        веб, окно агента (#125), iOS — читает её же. Фильтр `surface` добавляет
        #125 внутрь этого пути, а не рядом с ним.
        """
        from app.crud import quick_mark as quick_mark_crud

        assert quick_mark_crud.ListedMark.planned.__doc__ is not None
        pushups = await make_mark(client, "Отжимания", "+10", order=1)
        await put_plan(client, PLAN_DAY, [line("Отжаться", quick_mark_id=pushups)])

        marks = await listed(client, PLAN_DAY)

        assert marks[0]["planned"] is True


class TestTapClosesThePlanItem:
    """Отметка кнопки закрывает пункт плана — иначе человек отмечает дважды."""

    async def test_a_tap_on_a_planned_button_closes_its_line(
        self, client: AsyncClient
    ) -> None:
        """Третий пункт Acceptance: в плане отмечать второй раз не нужно."""
        pushups = await make_mark(client, "Отжимания", "+10", order=1)
        today = await server_day(client)
        plan = await put_plan(client, today, [line("Отжаться", quick_mark_id=pushups)])
        item_id = plan["sections"][0]["items"][0]["id"]

        tapped = await client.post(f"{QUICK_MARKS_URL}/{pushups}/events", json={})
        assert tapped.status_code == 201, tapped.text

        day = await client.get(f"{DAY_URL}/{today.isoformat()}")
        marks = {one["item_id"]: one for one in day.json()["marks"]}
        assert marks[item_id]["state"] == "done"

    async def test_a_tap_on_an_unplanned_button_marks_nothing(
        self, client: AsyncClient
    ) -> None:
        """Кнопка вне плана не имеет пункта, который могла бы закрыть."""
        water = await make_mark(client, "Вода", "+250 мл", order=1)
        today = await server_day(client)
        await put_plan(client, today, [line("Просто строка")])

        await client.post(f"{QUICK_MARKS_URL}/{water}/events", json={})

        day = await client.get(f"{DAY_URL}/{today.isoformat()}")
        assert day.json()["marks"] == []

    async def test_a_tick_taken_back_does_not_reopen_the_line(
        self, client: AsyncClient
    ) -> None:
        """
        Закрытие идёт только вперёд.

        Отметка пункта — суждение человека о дне; стирать его потому, что
        счётчик вернулся к нулю, значит спорить с автором дня.
        """
        vitamins = await client.post(
            "/api/v1/categories",
            json={
                "name": "Витамины",
                "display_mode": "checklist",
                "fields": [{"name": "D3", "field_type": "boolean", "order": 1}],
            },
        )
        category = vitamins.json()
        created = await client.post(
            QUICK_MARKS_URL,
            json={
                "label": "D3",
                "category_id": category["id"],
                "field_id": int(category["fields"][0]["id"]),
                "kind": "check",
            },
        )
        button = int(created.json()["id"])
        today = await server_day(client)
        plan = await put_plan(client, today, [line("Витамин", quick_mark_id=button)])
        item_id = plan["sections"][0]["items"][0]["id"]

        await client.post(f"{QUICK_MARKS_URL}/{button}/events", json={})
        await client.post(f"{QUICK_MARKS_URL}/{button}/events", json={"value": 0})

        day = await client.get(f"{DAY_URL}/{today.isoformat()}")
        marks = {one["item_id"]: one for one in day.json()["marks"]}
        assert marks[item_id]["state"] == "done"


class TestADeletedButton:
    """Кнопка, удалённая после составления плана, ничего не роняет."""

    async def test_the_plan_survives_the_button_leaving_the_directory(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Четвёртый пункт Acceptance: ни Today, ни выдача плана не падают.

        `ON DELETE SET NULL` — потому что кнопку удаляют, а прожитый день
        остаётся: пункт без кнопки становится обычным пунктом, отмечаемым рукой.
        """
        from sqlalchemy import delete

        from app.models.quick_mark import QuickMark

        pushups = await make_mark(client, "Отжимания", "+10", order=1)
        plan = await put_plan(
            client, PLAN_DAY, [line("Отжаться", quick_mark_id=pushups)]
        )
        item_id = plan["sections"][0]["items"][0]["id"]

        await db_session.execute(delete(QuickMark).where(QuickMark.id == pushups))
        await db_session.flush()

        day = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
        assert day.status_code == 200, day.text
        stored = day.json()["plan"]["sections"][0]["items"][0]
        assert stored["id"] == item_id
        assert stored["quick_mark_id"] is None
        assert await listed(client, PLAN_DAY) == []


class TestTheSameButtonTwiceInOneDay:
    """Одна кнопка в двух пунктах — состояние возможное, и оно не двоится."""

    async def test_the_first_line_by_position_owns_the_button(
        self, client: AsyncClient
    ) -> None:
        """
        Закрывается первый по `(секция, позиция)`, а не оба.

        Закрыть оба одной отметкой значило бы сказать про вечернюю воду то, чего
        не было: человек нажал один раз.
        """
        water = await make_mark(client, "Вода", "+250 мл", order=1)
        today = await server_day(client)
        plan = await put_plan(
            client,
            today,
            [
                line("Вода утром", quick_mark_id=water),
                line("Вода вечером", quick_mark_id=water),
            ],
        )
        morning, evening = (one["id"] for one in plan["sections"][0]["items"])

        await client.post(f"{QUICK_MARKS_URL}/{water}/events", json={})

        day = await client.get(f"{DAY_URL}/{today.isoformat()}")
        marks = {one["item_id"]: one for one in day.json()["marks"]}
        assert marks[morning]["state"] == "done"
        assert evening not in marks
