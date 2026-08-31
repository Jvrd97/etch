"""
Тренировка через API: день, состояние, жалобы, рекорды.

Три вещи, которые до `#92` не работали никак. Тренировка дня жила динамическими
ключами frontmatter и не запрашивалась; гейты `/train` жили прозой скилла и
выполнялись тем, кто их прочитал; минимум объявлялся внутри блока тренировки и
не имел своей галки — 29 августа он не был выполнен именно поэтому, а 30-го,
уже вынесенный отдельным пунктом, не был выполнен снова.
"""

# [review:need-review] PHASE-03/92
# summary: API tests for the training of a day and the state — the minimum carries its own plan item, two skipped days show as skipped_days = 2 on the page, an open shoulder complaint takes pull-ups out of the suggestion and closing it puts them back, a personal record answers with its date and target, and a second recompute changes nothing but recomputed_at
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud

DAY_URL = "/api/v1/day"
STATE_URL = "/api/v1/training/state"
COMPLAINTS_URL = "/api/v1/body-complaints"
RECORDS_URL = "/api/v1/personal-records"

PULLUPS = "подтягивания"


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    await day_crud.seed_rules(db_session)
    yield


async def put_training(client: AsyncClient, on: date, **body: Any) -> dict[str, Any]:
    response = await client.put(f"{DAY_URL}/{on.isoformat()}/training", json=body)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def state(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(STATE_URL)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_a_day_with_nothing_recorded_answers_null(client: AsyncClient) -> None:
    response = await client.get(f"{DAY_URL}/2026-08-24/training")

    assert response.status_code == 200
    assert response.json() is None


async def test_the_training_of_a_day_shows_planned_done_and_the_minimum(
    client: AsyncClient,
) -> None:
    stored = await put_training(
        client,
        date(2026, 8, 30),
        planned_md="только pull: подтягивания 3x5 RIR 2",
        done_md="улица 15 мин, один подход подтягиваний",
        minimum_md="улица + разминка + один подход",
        patterns=["pull"],
        sets={"pull": 1},
    )

    assert stored["planned_md"].startswith("только pull")
    assert stored["done_md"].startswith("улица")
    assert stored["minimum_md"].startswith("улица")


async def test_the_minimum_gets_its_own_plan_item(client: AsyncClient) -> None:
    # 29 августа: минимум, объявленный внутри задачи и без своей галки, не
    # выполняется. С 30-го он отдельный отмечаемый пункт — и ссылка на него
    # часть контракта, а не вёрстки.
    on = date(2026, 8, 30)
    plan = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={
            "sections": [
                {
                    "kind": "training",
                    "title": "Тренировка",
                    "items": [
                        {"kind": "bullet", "text_md": "силовая: pull"},
                        {"kind": "minimum", "text_md": "минимум: улица + разминка"},
                    ],
                }
            ]
        },
    )
    assert plan.status_code == 201, plan.text
    minimum = next(
        item
        for item in plan.json()["sections"][0]["items"]
        if item["kind"] == "minimum"
    )

    stored = await put_training(client, on, minimum_item_id=minimum["id"])
    assert stored["minimum_item_id"] == minimum["id"]

    # И отмечается он своей галкой, отдельной от галки тренировки.
    marked = await client.put(
        f"{DAY_URL}/{on.isoformat()}/marks/{minimum['id']}", json={"state": "done"}
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["state"] == "done"


async def test_two_skipped_days_in_a_row_show_as_two(client: AsyncClient) -> None:
    # Приёмка тикета: пропуск двух дней подряд поднимает `skipped_days` до 2, и
    # это видно снаружи, а не только в чистой функции.
    today = today_local()
    await put_training(client, today - timedelta(days=1), skipped=True)
    await put_training(client, today, skipped=True)

    assert (await state(client))["skipped_days"] == 2


async def test_an_open_shoulder_complaint_removes_pullups_from_the_offer(
    client: AsyncClient,
) -> None:
    opened = await client.post(
        COMPLAINTS_URL,
        json={
            "area": "левое плечо",
            "context": "3-й подход подтягиваний, 5 повторов",
            "severity": "кольнуло, прошло",
        },
    )
    assert opened.status_code == 201, opened.text

    offer = (await state(client))["suggestion"]
    assert PULLUPS not in offer["exercises"]
    assert any(one["exercise"] == PULLUPS for one in offer["excluded"])


async def test_closing_the_complaint_brings_pullups_back(client: AsyncClient) -> None:
    opened = await client.post(COMPLAINTS_URL, json={"area": "левое плечо"})
    complaint_id = opened.json()["id"]

    closed = await client.patch(
        f"{COMPLAINTS_URL}/{complaint_id}",
        json={"status": "closed", "closed_reason": "нагрузка была, симптомов нет"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["closed_on"] is not None

    offer = (await state(client))["suggestion"]
    assert PULLUPS in offer["exercises"]


async def test_a_heavy_pattern_trained_yesterday_is_not_offered_today(
    client: AsyncClient,
) -> None:
    today = today_local()
    await put_training(
        client,
        today - timedelta(days=1),
        patterns=["pull"],
        heavy_patterns=["pull"],
        sets={"pull": 4},
    )

    payload = await state(client)
    assert payload["last_heavy_pull"] == (today - timedelta(days=1)).isoformat()
    assert PULLUPS not in payload["suggestion"]["exercises"]


async def test_closing_a_complaint_that_does_not_exist_is_a_404(
    client: AsyncClient,
) -> None:
    response = await client.patch(
        f"{COMPLAINTS_URL}/00000000-0000-0000-0000-000000000000",
        json={"status": "closed"},
    )

    assert response.status_code == 404


async def test_a_complaint_cannot_be_reopened_through_the_patch(
    client: AsyncClient,
) -> None:
    opened = await client.post(COMPLAINTS_URL, json={"area": "колено"})
    response = await client.patch(
        f"{COMPLAINTS_URL}/{opened.json()['id']}", json={"status": "open"}
    )

    assert response.status_code == 422


async def test_a_personal_record_answers_with_its_date_and_target(
    client: AsyncClient,
) -> None:
    created = await client.post(
        RECORDS_URL,
        json={
            "exercise": "подтягивания",
            "sets": "9/10/5/3",
            "achieved_on": "2026-08-10",
            "target": "4x8 RIR 1-2",
        },
    )
    assert created.status_code == 201, created.text

    listed = await client.get(RECORDS_URL)
    assert listed.status_code == 200
    record = listed.json()[0]
    assert record["achieved_on"] == "2026-08-10"
    assert record["target"] == "4x8 RIR 1-2"
    assert record["sets"] == "9/10/5/3"


async def test_recomputing_twice_changes_only_the_timestamp(
    client: AsyncClient,
) -> None:
    # Приёмка тикета. Снимок — значение функции от строк, поэтому второе чтение
    # отличается только моментом пересчёта.
    await put_training(
        client, today_local(), patterns=["push"], heavy_patterns=["push"]
    )

    first = await state(client)
    second = await state(client)

    assert second["recomputed_at"] >= first["recomputed_at"]
    for key in first:
        if key == "recomputed_at":
            continue
        assert first[key] == second[key], key


async def test_the_authored_progression_survives_the_recompute(
    client: AsyncClient,
) -> None:
    written = await client.put(
        STATE_URL,
        json={"progression_stage": {"pull": "объём 4x6-8 RIR 1-2"}},
    )
    assert written.status_code == 200, written.text

    assert (await state(client))["progression_stage"] == {"pull": "объём 4x6-8 RIR 1-2"}


async def test_a_write_of_the_state_cannot_name_a_derived_field(
    client: AsyncClient,
) -> None:
    # Состояние, которое можно вписать руками, было бы вторым источником истины
    # и первым, который разойдётся с фактами.
    response = await client.put(
        STATE_URL, json={"last_heavy_pull": "2026-08-01", "progression_stage": {}}
    )

    assert response.status_code == 200, response.text
    assert response.json()["last_heavy_pull"] is None
