"""
Tests for POST /api/v1/day/{date}/plan and the plan half of GET /api/v1/day/{date}.

Every acceptance case of `#87` is here, in the words of the ticket: the plan is
visible in the order it was sent, the fifth task is named rather than counted,
a free item cannot be scheduled, a task without a window or a criterion or a
goal does not save, `23:30-00:30` reads as sixty minutes, overlapping windows
are reported, an unknown label survives the round trip, and a second POST
replaces the plan instead of doubling it.
"""

# [review:need-review] PHASE-03/87, PHASE-03/93
# summary: API tests for the whole-document plan — order preserved, the offending line named in every 422, the midnight window measured, overlaps found by the database, unknown labels kept in `extra`, and a repeated POST replacing rather than accumulating; the goal every task names is now a real row, seeded by `seeded_goal`
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud

DAY_URL = "/api/v1/day"

# A Monday under the current canon: four work tasks, all of them to be closed.
PLAN_DAY = date(2026, 8, 31)
PLAN_URL = f"{DAY_URL}/{PLAN_DAY.isoformat()}/plan"

MINUTES_IN_HOUR = 60


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it, plus goal 1 of the quarter.

    The test database is built by `create_all`, which never runs the migration's
    seed, so without this every plan would be judged by a canon describing no
    date at all. `seeded_goal` is here for the same reason: `task()` below names
    goal 1, and since `#93` that column has a foreign key.
    """
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


def document(**overrides: Any) -> dict[str, Any]:
    """A minimal plan; tests replace `sections` with what they are testing."""
    body: dict[str, Any] = {
        "title": "План 2026-08-31 (пн)",
        "lede": "Понедельник, четыре задачи",
        "sections": [],
    }
    body.update(overrides)
    return body


async def test_a_sent_plan_is_visible_on_the_day_in_the_order_it_was_sent(
    client: AsyncClient,
) -> None:
    """The first acceptance case: sections and items keep their order."""
    body = document(
        sections=[
            {
                "kind": "anchors",
                "title": "Якоря",
                "items": [
                    {"kind": "anchor", "code": "подъём", "text_md": "Подъём 06:00"},
                    {"kind": "anchor", "code": "спорт", "text_md": "Силовая 25 мин"},
                ],
            },
            {"kind": "work", "title": "Работа", "items": [task("W1")]},
            {
                "kind": "free",
                "title": "Свободный вечер",
                "items": [
                    {"kind": "bullet", "rigidity": "free", "text_md": "Что захочется"},
                ],
            },
        ]
    )

    created = await client.post(PLAN_URL, json=body)
    assert created.status_code == 201

    day = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
    assert day.status_code == 200
    detail = day.json()
    assert detail["has_plan"] is True

    sections = detail["plan"]["sections"]
    assert [section["kind"] for section in sections] == ["anchors", "work", "free"]
    assert [section["ord"] for section in sections] == [0, 1, 2]
    assert [item["code"] for item in sections[0]["items"]] == ["подъём", "спорт"]


async def test_a_day_without_a_plan_still_answers(client: AsyncClient) -> None:
    """Unchanged from `#86`: "плана нет" is an answer, not a 404."""
    response = await client.get(f"{DAY_URL}/2026-08-29")

    assert response.status_code == 200
    assert response.json()["has_plan"] is False
    assert response.json()["plan"] is None


async def test_a_fifth_task_is_refused_and_the_fifth_task_is_named(
    client: AsyncClient,
) -> None:
    """
    The acceptance case: 422 says `W5`, not "validation error".

    The bar is four because the fifth task is the one that turns a day into
    overtime; an answer that does not name it leaves the author re-reading a
    document they just wrote.
    """
    body = document(
        sections=[
            {
                "kind": "work",
                "items": [
                    task(f"W{n}", f"{8 + n:02d}:00-{9 + n:02d}:00") for n in range(1, 6)
                ],
            }
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "too_many_tasks"
    assert detail["item_code"] == "W5"


async def test_an_item_of_the_free_block_cannot_be_given_a_window(
    client: AsyncClient,
) -> None:
    """Свободный вечерний блок нечем расписать — это и есть «не перезакручивать»."""
    body = document(
        sections=[
            {
                "kind": "free",
                "items": [
                    {
                        "kind": "bullet",
                        "code": "E1",
                        "rigidity": "free",
                        "text_md": "Вечер",
                        "window": "19:00-21:00",
                    }
                ],
            }
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "free_item_has_window"
    assert response.json()["detail"]["item_code"] == "E1"


async def test_a_task_without_a_window_is_refused(client: AsyncClient) -> None:
    body = document(sections=[{"kind": "work", "items": [task("W1", window=None)]}])

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["item_code"] == "W1"


async def test_a_task_without_a_criterion_is_refused(client: AsyncClient) -> None:
    body = document(
        sections=[{"kind": "work", "items": [task("W1", done_criterion=None)]}]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "task_without_window_or_criterion"


async def test_a_task_tied_to_nothing_and_explained_by_nothing_is_refused(
    client: AsyncClient,
) -> None:
    """Несвязанную задачу нельзя вписать молча."""
    body = document(
        sections=[{"kind": "work", "items": [task("W1", quarter_goal_id=None)]}]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "task_is_not_linked"


async def test_a_task_explained_instead_of_linked_is_accepted(
    client: AsyncClient,
) -> None:
    body = document(
        sections=[
            {
                "kind": "work",
                "items": [
                    task(
                        "W1",
                        quarter_goal_id=None,
                        unlinked_reason="чужая срочность, но письмо просрочено вторые сутки",
                    )
                ],
            }
        ]
    )

    assert (await client.post(PLAN_URL, json=body)).status_code == 201


async def test_a_window_across_midnight_is_sixty_minutes(
    client: AsyncClient,
) -> None:
    """The acceptance case: `23:30-00:30` is an hour, not a negative duration."""
    body = document(
        sections=[
            {
                "kind": "evening",
                "items": [
                    {
                        "kind": "bullet",
                        "code": "N1",
                        "text_md": "Дочитать главу",
                        "window": "23:30-00:30",
                    }
                ],
            }
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 201
    schedule = response.json()["schedule"]
    assert len(schedule) == 1
    assert schedule[0]["minutes"] == MINUTES_IN_HOUR


async def test_two_tasks_whose_windows_collide_are_reported_as_an_overlap(
    client: AsyncClient,
) -> None:
    """
    The acceptance case behind the GiST index.

    Found by a self-join on `&&` in the database, so the schedule on screen is
    one consumer of the fact rather than the only place that knows it.
    """
    body = document(
        sections=[
            {
                "kind": "work",
                "items": [
                    task("W1", "09:00-11:00"),
                    task("W2", "10:00-12:00"),
                ],
            }
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 201
    overlaps = response.json()["overlaps"]
    assert len(overlaps) == 1
    assert overlaps[0]["overlap_minutes"] == 60

    schedule = {
        entry["code"]: entry["item_id"] for entry in response.json()["schedule"]
    }
    assert overlaps[0]["left_item_id"] == schedule["W1"]
    assert overlaps[0]["right_item_id"] == schedule["W2"]


async def test_a_point_stands_on_the_schedule_without_a_length(
    client: AsyncClient,
) -> None:
    """
    Точечный якорь — строка расписания без длительности.

    Так модель пишет подъём и старт работы: «06:00-06:00». Пока конец такого
    окна толкался на сутки вперёд, строка становилась суточным блоком; строки
    без конца расписание вообще не показывало. Момент обязан быть виден и обязан
    быть без минут — ровно как «20:00 — Конец» в шаблоне плана.
    """
    body = document(
        sections=[
            {
                "kind": "anchors",
                "items": [
                    {
                        "kind": "anchor",
                        "code": "подъём",
                        "text_md": "Подъём",
                        "window": "06:00-06:00",
                    }
                ],
            }
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 201
    schedule = response.json()["schedule"]
    assert len(schedule) == 1
    assert schedule[0]["code"] == "подъём"
    assert schedule[0]["minutes"] is None
    assert schedule[0]["ends_at"] is None


async def test_a_point_overlaps_nothing(client: AsyncClient) -> None:
    """
    Момент не занимает времени, поэтому пересекаться ему нечем.

    Приёмка того самого дня: «31 наложение · 66 ч 15 мин» на плане, где не
    накладывалось ничего. Два точечных якоря стали суточными отрезками и
    перекрыли весь день и друг друга.
    """
    body = document(
        sections=[
            {
                "kind": "anchors",
                "items": [
                    {
                        "kind": "anchor",
                        "code": "подъём",
                        "text_md": "Подъём",
                        "window": "06:00-06:00",
                    },
                    {
                        "kind": "anchor",
                        "code": "старт_работы",
                        "text_md": "Старт работы",
                        "window": "07:45-07:45",
                    },
                ],
            },
            {"kind": "work", "items": [task("W1", "09:00-11:00")]},
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 201
    assert response.json()["overlaps"] == []


async def test_windows_that_only_touch_do_not_count_as_an_overlap(
    client: AsyncClient,
) -> None:
    """`tstzrange` is half-open, so 09:00-10:00 and 10:00-11:00 are back to back."""
    body = document(
        sections=[
            {
                "kind": "work",
                "items": [task("W1", "09:00-10:00"), task("W2", "10:00-11:00")],
            }
        ]
    )

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 201
    assert response.json()["overlaps"] == []


async def test_a_label_without_a_column_of_its_own_survives_the_round_trip(
    client: AsyncClient,
) -> None:
    """
    The acceptance case: `Формат :: аудио` arrives and reads back.

    Six labels earned columns because queries and checks need them; the other
    nine-odd are not worth a schema and are far too worth keeping to drop.
    """
    body = document(
        sections=[
            {
                "kind": "study",
                "items": [
                    {
                        "kind": "bullet",
                        "code": "S1",
                        "text_md": "Лекция про транзакции",
                        "extra": {"Формат": "аудио", "Материал": "PDF на 40 страниц"},
                    }
                ],
            }
        ]
    )

    assert (await client.post(PLAN_URL, json=body)).status_code == 201

    day = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
    item = day.json()["plan"]["sections"][0]["items"][0]
    assert item["extra"]["Формат"] == "аудио"
    assert item["extra"]["Материал"] == "PDF на 40 страниц"


async def test_a_minimum_comes_back_as_a_child_with_its_own_line(
    client: AsyncClient,
) -> None:
    """
    29 August: a minimum declared inside a task and without its own tick is not
    done. It is a nested item, so `#88` can give it a mark of its own.
    """
    body = document(
        sections=[
            {
                "kind": "training",
                "items": [
                    {
                        "kind": "bullet",
                        "code": "T1",
                        "text_md": "Подтягивания 3x5, RIR 2",
                        "children": [
                            {
                                "kind": "minimum",
                                "code": "T1-min",
                                "text_md": "Улица + разминка + один подход",
                            }
                        ],
                    }
                ],
            }
        ]
    )

    assert (await client.post(PLAN_URL, json=body)).status_code == 201

    day = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
    parent = day.json()["plan"]["sections"][0]["items"][0]
    assert len(parent["children"]) == 1
    assert parent["children"][0]["kind"] == "minimum"
    assert parent["children"][0]["parent_id"] == parent["id"]


async def test_a_second_post_replaces_the_plan_rather_than_doubling_it(
    client: AsyncClient,
) -> None:
    """The acceptance case: no second section claiming the same `ord`."""
    first = document(
        sections=[{"kind": "work", "title": "Первый", "items": [task("W1")]}]
    )
    second = document(sections=[{"kind": "study", "title": "Второй", "items": []}])

    assert (await client.post(PLAN_URL, json=first)).status_code == 201
    assert (await client.post(PLAN_URL, json=second)).status_code == 201

    day = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
    sections = day.json()["plan"]["sections"]
    assert len(sections) == 1
    assert sections[0]["title"] == "Второй"


async def test_a_rejected_plan_leaves_the_previous_one_untouched(
    client: AsyncClient,
) -> None:
    """
    A 422 must not empty the day on its way out.

    The whole document is judged before a single row is deleted, so a plan that
    will not be accepted never gets to destroy the plan that was.
    """
    good = document(
        sections=[{"kind": "work", "title": "Хороший", "items": [task("W1")]}]
    )
    assert (await client.post(PLAN_URL, json=good)).status_code == 201

    over_the_bar = document(
        sections=[
            {
                "kind": "work",
                "items": [
                    task(f"W{n}", f"{8 + n:02d}:00-{9 + n:02d}:00") for n in range(1, 6)
                ],
            }
        ]
    )
    assert (await client.post(PLAN_URL, json=over_the_bar)).status_code == 422

    day = await client.get(f"{DAY_URL}/{PLAN_DAY.isoformat()}")
    assert day.json()["plan"]["sections"][0]["title"] == "Хороший"


async def test_an_ordinary_task_cannot_declare_itself_immovable(
    client: AsyncClient,
) -> None:
    """Не перезакручивать: жёсткими бывают только края дня."""
    body = document(sections=[{"kind": "work", "items": [task("W1", rigidity="hard")]}])

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "hard_is_not_an_edge"


async def test_the_plan_route_needs_the_api_key(db_session: AsyncSession) -> None:
    """Every router gets `require_api_key` from `API_ROUTERS`; this proves it."""
    from app.core.database import get_db
    from app.main import app

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(app=app, base_url="http://test") as bare:
        response = await bare.post(PLAN_URL, json=document())
    app.dependency_overrides.clear()

    assert response.status_code == 401


async def test_an_unknown_item_kind_is_refused_by_the_database(
    client: AsyncClient,
) -> None:
    """
    The vocabulary of item kinds is closed, and the CHECK is what closes it.

    A typo in `kind` would otherwise become a line nothing counts: not a task
    for the bar, not an anchor for the verdict, and invisible in every query
    that names the kinds it cares about.
    """
    body = document(
        sections=[{"kind": "work", "items": [{"kind": "taks", "text_md": "опечатка"}]}]
    )

    with pytest.raises(Exception) as error:
        await client.post(PLAN_URL, json=body)
    assert "ck_plan_item_kind" in str(error.value)
