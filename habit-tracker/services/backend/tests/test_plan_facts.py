"""
Tests for the plan line that writes into a category's history (`#200`).

A line of the plan names a category and one of its fields — «Отжимания», the
field «Повторения», a target of 300. The person types what was actually done
right in the plan, and that number becomes an ordinary entry of the category:
the same row the category history, its totals and its streak read. Nothing here
is a second history of measurements.

What is pinned down:

* the target is not a fact — a plan of 300 writes nothing, a tick writes
  nothing, 100 done is stored as 100;
* a repeated request and a double tap land once; a correction 300 → 200 edits
  the entry the plan wrote, and only «Добавить ещё» adds a second one;
* the fact and the mark are one transaction, so a refused fact never leaves the
  line ticked;
* the date of the fact is the day of the plan, not today;
* a wrong field, a wrong unit, a field of another category, an archived
  category and a removed field are all refused by name rather than written into
  whatever field happened to be there;
* independent entries of the same day — typed by hand, imported — are neither
  rewritten nor added to;
* the plan going away, or being rewritten, leaves the history where it was;
* reading the plan does not cost more queries for more linked lines.
"""

# [review:need-review] PHASE-03/200
# summary: API tests for plan lines linked to a category — the link read back with its state, 300 push-ups / 3 km / a gym visit written as entries of their categories, the correction, the replay and the concurrent double tap, the refusals by field, unit, type, owner and link state, the date of a historic day, the untick that keeps history, edits made in the history read back in the plan, the plan replaced without losing a fact, and a query count that does not grow with linked lines
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from datetime import date
from io import StringIO
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient, Response
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import plan_fact as fact_crud
from app.models import Entry
from app.models.plan import PlanItem
from app.schemas.plan_fact import PlanFactIn, PlanFactValueIn
from tests.conftest import TestSessionLocal, test_engine

DAY_URL = "/api/v1/day"
ENTRIES_URL = "/api/v1/entries"
CATEGORIES_URL = "/api/v1/categories"

# A Monday under the current canon, the same day the other plan tests use. It is
# also in the past relative to the machine's clock, which is what the date test
# needs: a fact for it must not land on today.
PLAN_DAY = date(2026, 8, 31)
NEXT_DAY = date(2026, 9, 1)


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The canon rows and goal 1 — the plan is judged by them, see `#87`."""
    await day_crud.seed_rules(db_session)
    yield


async def make_category(
    client: AsyncClient,
    name: str,
    fields: list[dict[str, Any]],
    **over: Any,
) -> dict[str, Any]:
    """A category with `fields`, as the categories screen creates it."""
    payload: dict[str, Any] = {"name": name, "display_mode": "form", "fields": fields}
    payload.update(over)
    response = await client.post(CATEGORIES_URL, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


def field_id(category: dict[str, Any], index: int = 0) -> int:
    """Id of the `index`-th field of a category answer."""
    return int(category["fields"][index]["id"])


@pytest.fixture
async def pushups(client: AsyncClient) -> dict[str, Any]:
    """«Отжимания» — one number field counted in repetitions."""
    return await make_category(
        client,
        "Отжимания",
        [{"name": "Повторения", "field_type": "number", "order": 1, "unit": "раз"}],
    )


@pytest.fixture
async def walk(client: AsyncClient) -> dict[str, Any]:
    """«Прогулка» — distance in kilometres."""
    return await make_category(
        client,
        "Прогулка",
        [{"name": "Дистанция", "field_type": "number", "order": 1, "unit": "км"}],
    )


@pytest.fixture
async def gym(client: AsyncClient) -> dict[str, Any]:
    """«Спортзал» — one box: was there or not."""
    return await make_category(
        client,
        "Спортзал",
        [{"name": "Посетил", "field_type": "boolean", "order": 1}],
    )


@pytest.fixture
async def workout(client: AsyncClient) -> dict[str, Any]:
    """A composite category: sets, repetitions and time spent."""
    return await make_category(
        client,
        "Тренировка",
        [
            {"name": "Подходы", "field_type": "number", "order": 1},
            {"name": "Повторения", "field_type": "number", "order": 2},
            {"name": "Время", "field_type": "duration", "order": 3},
        ],
    )


def line(text: str, **over: Any) -> dict[str, Any]:
    """A plain line of the plan; nothing in it can break a rule."""
    item: dict[str, Any] = {"kind": "bullet", "text_md": text}
    item.update(over)
    return item


def linked(
    text: str, category: dict[str, Any], index: int = 0, **over: Any
) -> dict[str, Any]:
    """A line linked to the `index`-th field of `category`."""
    return line(
        text, category_id=category["id"], field_id=field_id(category, index), **over
    )


async def post_plan(
    client: AsyncClient, on: date, items: list[dict[str, Any]]
) -> Response:
    """One evening section carrying `items`, answered as is."""
    return await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={
            "title": f"План {on.isoformat()}",
            "sections": [{"title": "Вечер", "kind": "evening", "items": items}],
        },
    )


async def put_plan(
    client: AsyncClient, on: date, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """The plan stored; hands back the stored plan."""
    response = await post_plan(client, on, items)
    assert response.status_code == 201, response.text
    return dict(response.json())


def first_item(plan: dict[str, Any]) -> dict[str, Any]:
    """The first line of the first section."""
    return dict(plan["sections"][0]["items"][0])


def facts_url(on: date, item_id: str, entry_id: int | None = None) -> str:
    """Where the facts of one line live."""
    base = f"{DAY_URL}/{on.isoformat()}/plan/items/{item_id}/facts"
    return base if entry_id is None else f"{base}/{entry_id}"


async def record(
    client: AsyncClient,
    on: date,
    item_id: str,
    values: list[dict[str, Any]],
    key: str | None = None,
    **over: Any,
) -> Response:
    """`POST .../facts` under a fresh key unless one is named."""
    body: dict[str, Any] = {"values": values}
    body.update(over)
    return await client.post(
        facts_url(on, item_id),
        json=body,
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


async def day(client: AsyncClient, on: date) -> dict[str, Any]:
    """The day as the screen reads it."""
    response = await client.get(f"{DAY_URL}/{on.isoformat()}")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def facts_of(client: AsyncClient, on: date, item_id: str) -> dict[str, Any]:
    """The facts block of one line, read through `GET /day`."""
    body = await day(client, on)
    found = [one for one in body["plan_facts"] if one["item_id"] == item_id]
    assert len(found) == 1, body["plan_facts"]
    return dict(found[0])


async def history(client: AsyncClient, category_id: int) -> list[dict[str, Any]]:
    """The category history, as its own screen reads it."""
    response = await client.get(ENTRIES_URL, params={"category_id": category_id})
    assert response.status_code == 200, response.text
    return list(response.json())


def value_of(entry: dict[str, Any], of_field: int) -> str | None:
    """The stored text of one field of an entry."""
    for one in entry["values"]:
        if int(one["field_id"]) == of_field:
            return one["value"]
    return None


class TestTheLink:
    """A line names a category and a field; the plan reads that back."""

    async def test_the_link_and_its_target_are_read_back_with_the_category(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item = first_item(plan)
        assert item["category_id"] == pushups["id"]
        assert item["field_id"] == field_id(pushups)
        assert item["target_value"] == 300

        facts = await facts_of(client, PLAN_DAY, item["id"])
        link = facts["link"]
        assert link["category_name"] == "Отжимания"
        assert link["field_name"] == "Повторения"
        assert link["field_type"] == "number"
        assert link["unit"] == "раз"
        assert link["target_value"] == 300
        assert link["state"] == "ok"
        # The plan alone is a target, never a fact.
        assert facts["entries"] == []
        assert facts["total"] is None
        assert facts["progress"] == "none"
        assert await history(client, pushups["id"]) == []

    async def test_a_line_without_a_link_has_no_facts_block(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        await put_plan(client, PLAN_DAY, [line("Просто строка")])
        assert (await day(client, PLAN_DAY))["plan_facts"] == []

    async def test_a_field_of_another_category_is_refused_by_the_document(
        self, client: AsyncClient, pushups: dict[str, Any], walk: dict[str, Any]
    ) -> None:
        response = await post_plan(
            client,
            PLAN_DAY,
            [
                line(
                    "Отжимания",
                    code="P1",
                    category_id=pushups["id"],
                    field_id=field_id(walk),
                )
            ],
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "plan_link_invalid"
        assert response.json()["detail"]["item_code"] == "P1"

    async def test_an_unknown_category_is_refused_by_the_editor(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [line("Отжимания")])
        item = first_item(plan)
        response = await client.patch(
            f"{DAY_URL}/{PLAN_DAY.isoformat()}/plan/items/{item['id']}",
            json={"category_id": 999_999, "field_id": field_id(pushups)},
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "plan_link_invalid"

    async def test_a_target_on_a_box_is_refused(
        self, client: AsyncClient, gym: dict[str, Any]
    ) -> None:
        response = await post_plan(
            client, PLAN_DAY, [linked("Зал", gym, target_value=1)]
        )
        assert response.status_code == 422, response.text

    async def test_a_checklist_category_is_refused(self, client: AsyncClient) -> None:
        """A checklist keeps one entry per day (ADR-0007); a plan fact would be a second."""
        vitamins = await make_category(
            client,
            "Витамины",
            [{"name": "D3", "field_type": "boolean", "order": 1}],
            display_mode="checklist",
        )
        response = await post_plan(client, PLAN_DAY, [linked("Витамины", vitamins)])
        assert response.status_code == 422, response.text

    async def test_the_editor_links_and_unlinks_a_line(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [line("Отжимания")])
        item_url = (
            f"{DAY_URL}/{PLAN_DAY.isoformat()}/plan/items/{first_item(plan)['id']}"
        )

        linked_answer = await client.patch(
            item_url,
            json={
                "category_id": pushups["id"],
                "field_id": field_id(pushups),
                "target_value": 300,
            },
        )
        assert linked_answer.status_code == 200, linked_answer.text
        assert linked_answer.json()["item"]["category_id"] == pushups["id"]

        # Clearing the category clears the field and the target with it: an
        # unlinked line with a target left over would be a target of nothing.
        unlinked = await client.patch(item_url, json={"category_id": None})
        assert unlinked.status_code == 200, unlinked.text
        item = unlinked.json()["item"]
        assert (item["category_id"], item["field_id"], item["target_value"]) == (
            None,
            None,
            None,
        )


class TestRecordingAFact:
    """300 push-ups, 3 km and a gym visit become entries of their categories."""

    async def test_300_creates_exactly_one_entry_in_the_category_history(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]

        response = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )

        assert response.status_code == 201, response.text
        entries = await history(client, pushups["id"])
        assert len(entries) == 1
        assert entries[0]["entry_date"] == PLAN_DAY.isoformat()
        assert value_of(entries[0], field_id(pushups)) == "300"
        facts = await facts_of(client, PLAN_DAY, item_id)
        assert [one["entry_id"] for one in facts["entries"]] == [entries[0]["id"]]
        assert facts["total"] == 300
        assert facts["progress"] == "met"

    async def test_100_of_300_is_stored_as_100_and_shown_as_partial(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]

        await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 100}]
        )

        facts = await facts_of(client, PLAN_DAY, item_id)
        assert facts["total"] == 100
        assert facts["progress"] == "partial"
        # No mark was asked for, so none was invented.
        assert (await day(client, PLAN_DAY))["marks"] == []

    async def test_the_walk_keeps_its_distance_and_unit(
        self, client: AsyncClient, walk: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Прогулка", walk)])
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(walk), "value": 3.5, "unit": "км"}],
        )

        assert response.status_code == 201, response.text
        entries = await history(client, walk["id"])
        assert value_of(entries[0], field_id(walk)) == "3.5"
        facts = response.json()["facts"]
        assert facts["link"]["unit"] == "км"
        assert facts["total"] == 3.5
        # No target: the fact is recorded, there is nothing to compare it with.
        assert facts["progress"] == "recorded"

    async def test_the_gym_stores_the_visit_as_a_box(
        self, client: AsyncClient, gym: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Зал", gym)])
        item_id = first_item(plan)["id"]

        response = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(gym), "value": True}]
        )

        assert response.status_code == 201, response.text
        entries = await history(client, gym["id"])
        assert value_of(entries[0], field_id(gym)) == "true"
        facts = response.json()["facts"]
        assert facts["total"] is None
        assert facts["done"] is True
        assert facts["progress"] == "met"

    async def test_a_composite_category_fills_several_fields_in_one_entry(
        self, client: AsyncClient, workout: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Тренировка", workout, 1, target_value=100)]
        )
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [
                {"field_id": field_id(workout, 0), "value": 4},
                {"field_id": field_id(workout, 1), "value": 120},
                {"field_id": field_id(workout, 2), "value": 1800},
            ],
        )

        assert response.status_code == 201, response.text
        entries = await history(client, workout["id"])
        assert len(entries) == 1
        assert value_of(entries[0], field_id(workout, 0)) == "4"
        assert value_of(entries[0], field_id(workout, 1)) == "120"
        assert value_of(entries[0], field_id(workout, 2)) == "1800"
        # The total and the progress follow the linked field, not the sum of all.
        assert response.json()["facts"]["total"] == 120
        assert response.json()["facts"]["progress"] == "met"

    async def test_the_fact_and_the_mark_land_in_one_write(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(pushups), "value": 300}],
            mark="done",
        )

        assert response.status_code == 201, response.text
        assert response.json()["mark"]["state"] == "done"
        marks = (await day(client, PLAN_DAY))["marks"]
        assert [(one["item_id"], one["state"]) for one in marks] == [(item_id, "done")]


class TestNoDoubleCounting:
    """Replay, correction and «Добавить ещё» each mean what they say."""

    async def test_a_replayed_request_returns_the_stored_fact(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        values = [{"field_id": field_id(pushups), "value": 300}]
        key = str(uuid.uuid4())

        first = await record(client, PLAN_DAY, item_id, values, key=key)
        again = await record(client, PLAN_DAY, item_id, values, key=key)

        assert first.status_code == 201, first.text
        assert again.status_code == 200, again.text
        assert again.json()["entry_id"] == first.json()["entry_id"]
        assert len(await history(client, pushups["id"])) == 1

    async def test_a_key_spent_on_another_line_is_a_conflict(
        self, client: AsyncClient, pushups: dict[str, Any], walk: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client,
            PLAN_DAY,
            [linked("Отжимания", pushups), linked("Прогулка", walk)],
        )
        first_line, second_line = plan["sections"][0]["items"]
        key = str(uuid.uuid4())
        await record(
            client,
            PLAN_DAY,
            first_line["id"],
            [{"field_id": field_id(pushups), "value": 10}],
            key=key,
        )

        response = await record(
            client,
            PLAN_DAY,
            second_line["id"],
            [{"field_id": field_id(walk), "value": 3}],
            key=key,
        )

        assert response.status_code == 409, response.text
        assert await history(client, walk["id"]) == []

    async def test_a_correction_changes_the_entry_rather_than_adding(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]
        written = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )
        entry_id = written.json()["entry_id"]

        response = await client.put(
            facts_url(PLAN_DAY, item_id, entry_id),
            json={"values": [{"field_id": field_id(pushups), "value": 200}]},
        )

        assert response.status_code == 200, response.text
        entries = await history(client, pushups["id"])
        assert [one["id"] for one in entries] == [entry_id]
        assert value_of(entries[0], field_id(pushups)) == "200"
        assert response.json()["facts"]["total"] == 200
        assert response.json()["facts"]["progress"] == "partial"

    async def test_add_more_is_a_second_entry(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]
        values = [{"field_id": field_id(pushups), "value": 150}]

        await record(client, PLAN_DAY, item_id, values)
        second = await record(client, PLAN_DAY, item_id, values)

        assert second.status_code == 201, second.text
        assert len(await history(client, pushups["id"])) == 2
        assert second.json()["facts"]["total"] == 300
        assert second.json()["facts"]["progress"] == "met"

    async def test_a_double_tap_from_two_connections_lands_once(
        self, client: AsyncClient, pushups: dict[str, Any], db_session: AsyncSession
    ) -> None:
        """
        Two transactions racing with one key: the unique key is the referee.

        Real sessions on real connections, not the test client: the client
        shares one session, and two requests through it can never overlap.
        """
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        await db_session.commit()
        item_id = uuid.UUID(first_item(plan)["id"])
        key = str(uuid.uuid4())
        data = PlanFactIn(
            values=[PlanFactValueIn(field_id=field_id(pushups), value=300)]
        )

        async def tap() -> fact_crud.FactWrite:
            async with TestSessionLocal() as session:
                item = await session.get(PlanItem, item_id)
                assert item is not None
                written = await fact_crud.record_fact(
                    session, PLAN_DAY, item, data, idempotency_key=key
                )
                await session.commit()
                return written

        first, second = await asyncio.gather(tap(), tap())

        assert first.entry_id == second.entry_id
        assert sorted([first.replayed, second.replayed]) == [False, True]
        async with TestSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Entry)
                .where(Entry.category_id == pushups["id"])
            )
        assert count == 1

    async def test_a_refused_fact_leaves_the_line_unticked(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(pushups), "value": True}],
            mark="done",
        )

        assert response.status_code == 422, response.text
        assert (await day(client, PLAN_DAY))["marks"] == []
        assert await history(client, pushups["id"]) == []

    async def test_a_plain_tick_does_not_invent_a_quantity(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]

        response = await client.put(
            f"{DAY_URL}/{PLAN_DAY.isoformat()}/marks/{item_id}",
            json={"state": "done"},
        )

        assert response.status_code == 200, response.text
        assert await history(client, pushups["id"]) == []
        assert (await facts_of(client, PLAN_DAY, item_id))["progress"] == "none"


class TestRefusals:
    """Wrong field, unit, type, owner or link state — refused, nothing written."""

    async def test_a_field_outside_the_linked_category(
        self, client: AsyncClient, pushups: dict[str, Any], walk: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [
                {"field_id": field_id(pushups), "value": 10},
                {"field_id": field_id(walk), "value": 3},
            ],
        )

        assert response.status_code == 422, response.text
        assert await history(client, pushups["id"]) == []
        assert await history(client, walk["id"]) == []

    async def test_a_wrong_unit(
        self, client: AsyncClient, walk: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Прогулка", walk)])
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(walk), "value": 3000, "unit": "м"}],
        )

        assert response.status_code == 422, response.text
        assert await history(client, walk["id"]) == []

    async def test_a_number_into_a_box(
        self, client: AsyncClient, gym: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Зал", gym)])
        item_id = first_item(plan)["id"]

        response = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(gym), "value": 1}]
        )

        assert response.status_code == 422, response.text

    async def test_a_fraction_of_a_second(
        self, client: AsyncClient, workout: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Тренировка", workout, 2)])
        item_id = first_item(plan)["id"]

        response = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(workout, 2), "value": 1.5}],
        )

        assert response.status_code == 422, response.text

    async def test_a_write_without_the_linked_field(
        self, client: AsyncClient, workout: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Тренировка", workout, 1)])
        item_id = first_item(plan)["id"]

        response = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(workout, 0), "value": 4}]
        )

        assert response.status_code == 422, response.text

    async def test_a_line_that_is_not_linked(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [line("Просто строка")])

        response = await record(
            client,
            PLAN_DAY,
            first_item(plan)["id"],
            [{"field_id": field_id(pushups), "value": 10}],
        )

        assert response.status_code == 409, response.text
        assert await history(client, pushups["id"]) == []

    async def test_a_line_of_another_day(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])

        response = await record(
            client,
            NEXT_DAY,
            first_item(plan)["id"],
            [{"field_id": field_id(pushups), "value": 10}],
        )

        assert response.status_code == 404, response.text

    async def test_an_entry_the_line_did_not_write(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        independent = await client.post(
            ENTRIES_URL,
            json={
                "category_id": pushups["id"],
                "entry_date": PLAN_DAY.isoformat(),
                "values": [{"field_id": field_id(pushups), "value": "50"}],
            },
        )
        assert independent.status_code == 201, independent.text

        response = await client.put(
            facts_url(PLAN_DAY, first_item(plan)["id"], independent.json()["id"]),
            json={"values": [{"field_id": field_id(pushups), "value": 1}]},
        )

        assert response.status_code == 404, response.text
        assert (
            value_of((await history(client, pushups["id"]))[0], field_id(pushups))
            == "50"
        )

    async def test_an_archived_category_is_a_state_not_a_write(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        archived = await client.patch(
            f"{CATEGORIES_URL}/{pushups['id']}", json={"is_active": False}
        )
        assert archived.status_code == 200, archived.text

        assert (await facts_of(client, PLAN_DAY, item_id))["link"][
            "state"
        ] == "category_archived"
        response = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 10}]
        )
        assert response.status_code == 409, response.text
        assert await history(client, pushups["id"]) == []

    async def test_a_removed_field_is_a_state_not_a_write_into_another(
        self, client: AsyncClient, workout: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Тренировка", workout, 1)])
        item_id = first_item(plan)["id"]
        kept = [
            {
                "id": one["id"],
                "name": one["name"],
                "field_type": one["field_type"],
                "order": one["order"],
            }
            for one in workout["fields"]
            if int(one["id"]) != field_id(workout, 1)
        ]
        removed = await client.patch(
            f"{CATEGORIES_URL}/{workout['id']}", json={"fields": kept}
        )
        assert removed.status_code == 200, removed.text

        facts = await facts_of(client, PLAN_DAY, item_id)
        assert facts["link"]["state"] == "field_missing"
        assert facts["link"]["field_id"] is None
        response = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(workout, 0), "value": 4}]
        )
        assert response.status_code == 409, response.text
        assert await history(client, workout["id"]) == []


class TestDates:
    """The day of the fact is the day of the plan, unless the person says otherwise."""

    async def test_a_historic_day_writes_into_that_day(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])

        await record(
            client,
            PLAN_DAY,
            first_item(plan)["id"],
            [{"field_id": field_id(pushups), "value": 30}],
        )

        [entry] = await history(client, pushups["id"])
        assert entry["entry_date"] == PLAN_DAY.isoformat()
        assert entry["entry_date"] != date.today().isoformat()

    async def test_a_named_date_moves_the_fact_and_keeps_the_link(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        written = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 30}]
        )

        moved = await client.put(
            facts_url(PLAN_DAY, item_id, written.json()["entry_id"]),
            json={
                "values": [{"field_id": field_id(pushups), "value": 30}],
                "entry_date": NEXT_DAY.isoformat(),
            },
        )

        assert moved.status_code == 200, moved.text
        [entry] = await history(client, pushups["id"])
        assert entry["entry_date"] == NEXT_DAY.isoformat()
        facts = await facts_of(client, PLAN_DAY, item_id)
        assert [one["entry_date"] for one in facts["entries"]] == [NEXT_DAY.isoformat()]


class TestTheMarkFollowsTheFact:
    """A correction or a delete that leaves the line short takes «сделано» back."""

    async def mark_of(self, client: AsyncClient, item_id: str) -> str | None:
        """The state of the line's mark as the day reads it, or None."""
        marks = (await day(client, PLAN_DAY))["marks"]
        found = [one["state"] for one in marks if one["item_id"] == item_id]
        return found[0] if found else None

    async def test_300_corrected_to_200_takes_done_back(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]
        written = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(pushups), "value": 300}],
            mark="done",
        )

        response = await client.put(
            facts_url(PLAN_DAY, item_id, written.json()["entry_id"]),
            json={
                "values": [{"field_id": field_id(pushups), "value": 200}],
                "mark": "unmark",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["mark"]["state"] is None
        assert await self.mark_of(client, item_id) is None
        assert len(await history(client, pushups["id"])) == 1

    async def test_was_corrected_to_was_not_takes_done_back(
        self, client: AsyncClient, gym: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Зал", gym)])
        item_id = first_item(plan)["id"]
        written = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(gym), "value": True}],
            mark="done",
        )

        response = await client.put(
            facts_url(PLAN_DAY, item_id, written.json()["entry_id"]),
            json={
                "values": [{"field_id": field_id(gym), "value": False}],
                "mark": "unmark",
            },
        )

        assert response.status_code == 200, response.text
        assert await self.mark_of(client, item_id) is None

    async def test_deleting_the_only_fact_takes_done_back(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        written = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(pushups), "value": 300}],
            mark="done",
        )

        response = await client.delete(
            facts_url(PLAN_DAY, item_id, written.json()["entry_id"]),
            params={"mark": "unmark"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["mark"]["state"] is None
        assert await self.mark_of(client, item_id) is None

    async def test_unmark_leaves_a_mark_other_than_done(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]
        written = await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(pushups), "value": 100}],
            mark="skipped",
        )

        response = await client.put(
            facts_url(PLAN_DAY, item_id, written.json()["entry_id"]),
            json={
                "values": [{"field_id": field_id(pushups), "value": 50}],
                "mark": "unmark",
            },
        )

        assert response.status_code == 200, response.text
        assert await self.mark_of(client, item_id) == "skipped"

    async def test_delete_without_a_mark_leaves_done(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        values = [{"field_id": field_id(pushups), "value": 150}]
        first = await record(client, PLAN_DAY, item_id, values, mark="done")
        await record(client, PLAN_DAY, item_id, values)

        response = await client.delete(
            facts_url(PLAN_DAY, item_id, first.json()["entry_id"])
        )

        assert response.status_code == 200, response.text
        assert await self.mark_of(client, item_id) == "done"


class TestHistoryStaysTheHistory:
    """The plan reads the history; it does not own it."""

    async def test_untick_keeps_the_entry(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        await record(
            client,
            PLAN_DAY,
            item_id,
            [{"field_id": field_id(pushups), "value": 300}],
            mark="done",
        )

        response = await client.put(
            f"{DAY_URL}/{PLAN_DAY.isoformat()}/marks/{item_id}", json={"state": None}
        )

        assert response.status_code == 200, response.text
        assert len(await history(client, pushups["id"])) == 1
        assert len((await facts_of(client, PLAN_DAY, item_id))["entries"]) == 1

    async def test_delete_is_an_explicit_action(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        written = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )

        response = await client.delete(
            facts_url(PLAN_DAY, item_id, written.json()["entry_id"])
        )

        assert response.status_code == 200, response.text
        assert await history(client, pushups["id"]) == []
        assert response.json()["facts"]["entries"] == []

    async def test_an_edit_in_the_history_reads_back_in_the_plan(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]
        written = await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )

        edited = await client.patch(
            f"{ENTRIES_URL}/{written.json()['entry_id']}",
            json={"values": [{"field_id": field_id(pushups), "value": "250"}]},
        )

        assert edited.status_code == 200, edited.text
        facts = await facts_of(client, PLAN_DAY, item_id)
        assert facts["total"] == 250
        assert facts["progress"] == "partial"

    async def test_independent_entries_are_neither_rewritten_nor_added(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(
            client, PLAN_DAY, [linked("Отжимания", pushups, target_value=300)]
        )
        item_id = first_item(plan)["id"]
        imported = await client.post(
            ENTRIES_URL,
            json={
                "category_id": pushups["id"],
                "entry_date": PLAN_DAY.isoformat(),
                "values": [{"field_id": field_id(pushups), "value": "50"}],
            },
        )
        assert imported.status_code == 201, imported.text

        await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )

        by_id = {one["id"]: one for one in await history(client, pushups["id"])}
        assert len(by_id) == 2
        assert value_of(by_id[imported.json()["id"]], field_id(pushups)) == "50"
        assert (await facts_of(client, PLAN_DAY, item_id))["total"] == 300

    async def test_a_rewritten_plan_leaves_the_history(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )

        await put_plan(client, PLAN_DAY, [line("Совсем другой план")])

        assert len(await history(client, pushups["id"])) == 1
        assert (await day(client, PLAN_DAY))["plan_facts"] == []

    async def test_a_line_kept_through_a_rewrite_keeps_its_facts(
        self, client: AsyncClient, pushups: dict[str, Any]
    ) -> None:
        plan = await put_plan(client, PLAN_DAY, [linked("Отжимания", pushups)])
        item_id = first_item(plan)["id"]
        await record(
            client, PLAN_DAY, item_id, [{"field_id": field_id(pushups), "value": 300}]
        )

        await put_plan(
            client, PLAN_DAY, [linked("Отжимания, вечером", pushups, id=item_id)]
        )

        assert len((await facts_of(client, PLAN_DAY, item_id))["entries"]) == 1


@contextmanager
def counted_statements() -> Iterator[list[str]]:
    """Every SQL statement the engine sends while the block runs."""
    seen: list[str] = []

    def count(  # noqa: PLR0913 - the signature of the SQLAlchemy event
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        seen.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        yield seen
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)


class TestReadCost:
    """More linked lines and more facts do not mean more queries."""

    async def test_reading_the_day_does_not_grow_with_linked_lines(
        self,
        client: AsyncClient,
        pushups: dict[str, Any],
        walk: dict[str, Any],
        gym: dict[str, Any],
        workout: dict[str, Any],
    ) -> None:
        categories = [pushups, walk, gym, workout]

        async def plan_with(linked_count: int) -> None:
            items = [
                linked(f"Строка {index}", category, code=f"L{index}")
                if index < linked_count
                else line(f"Строка {index}", code=f"L{index}")
                for index, category in enumerate(categories)
            ]
            plan = await put_plan(client, PLAN_DAY, items)
            for item, category in zip(
                plan["sections"][0]["items"][:linked_count], categories, strict=False
            ):
                value: bool | int = True if category is gym else 5
                for _ in range(2):
                    await record(
                        client,
                        PLAN_DAY,
                        item["id"],
                        [{"field_id": field_id(category), "value": value}],
                    )
            await day(client, PLAN_DAY)

        await plan_with(1)
        with counted_statements() as one_linked:
            await day(client, PLAN_DAY)

        await plan_with(len(categories))
        with counted_statements() as all_linked:
            await day(client, PLAN_DAY)

        assert len(all_linked) == len(one_linked)


# --- the migration ----------------------------------------------------------

LINK_REVISION = "c4e6a8b0d2f3"


def _alembic_config(buffer: StringIO) -> Config:
    """
    Alembic built in code and writing SQL into `buffer` — no database touched.

    Without the ini file on purpose: `fileConfig()` would switch off the loggers
    other tests listen to, the reason `test_quick_marks` builds it the same way.
    """
    config = Config(output_buffer=buffer)
    config.set_main_option("script_location", "alembic")
    return config


def _offline(step: str) -> str:
    """The SQL of one step of the chain, rendered from the revision file alone."""
    buffer = StringIO()
    config = _alembic_config(buffer)
    revision = ScriptDirectory.from_config(config).get_revision(LINK_REVISION)
    previous = revision.down_revision
    assert isinstance(previous, str)
    if step == "upgrade":
        command.upgrade(config, f"{previous}:{LINK_REVISION}", sql=True)
    else:
        command.downgrade(config, f"{LINK_REVISION}:{previous}", sql=True)
    return buffer.getvalue().lower()


def test_the_migration_adds_the_link_and_the_source() -> None:
    sql = _offline("upgrade")
    assert "add column category_id integer" in sql
    assert "add column field_id integer" in sql
    assert "add column target_value numeric(12, 3)" in sql
    assert "fk_plan_item_category_id" in sql
    assert "on delete set null" in sql
    assert "add column plan_item_id uuid" in sql
    # No foreign key from the entry to the line: a rewritten plan must not
    # cascade into history.
    assert "references plan_item" not in sql


def test_the_downgrade_takes_back_what_the_upgrade_added() -> None:
    sql = _offline("downgrade")
    for name in (
        "ix_entries_plan_item_id",
        "ix_plan_item_category_id",
        "fk_plan_item_field_id",
        "fk_plan_item_category_id",
    ):
        assert name in sql
    for column in ("plan_item_id", "target_value", "field_id", "category_id"):
        assert f"drop column {column}" in sql
