# [review:need-review] PHASE-03/159
# summary: tests of the link between a timed interval and the plan item it was spent on — a manual record names the item by uuid, the day's time per task counts it (once, as the union of ranges) instead of calling it work outside the plan, an unknown item is a 422 and not a 500, a correction can move or remove the link, and deleting the item leaves the interval standing with no link
"""
Intervals linked to a plan item by uuid.

`plan_task_id` is a number and `plan_item.id` is a uuid, so the floating panel's
timer could not say which task it timed. `plan_item_id` is the column that can.
The cases are the ways a link goes wrong in silence: an interval that has a task
but is counted as work outside the plan, the same hour counted twice because two
records named the same task, and a link that points at nothing.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import today_local
from app.crud import activity as activity_crud
from app.crud import day as day_crud
from app.crud import role as role_crud
from app.models.activity import ActivityInterval, ModeSchedule
from app.models.plan import PlanItem

AGENT_URL = "/api/v1/agent"
MANUAL_URL = f"{AGENT_URL}/activity/manual"
DAY_URL = "/api/v1/day"

ZONE = ZoneInfo(settings.APP_TIMEZONE)
TODAY = today_local()


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    await activity_crud.seed_settings(db_session)
    db_session.add(ModeSchedule(weekday=TODAY.isoweekday() % 7, kind="work"))
    await day_crud.seed_rules(db_session)
    await role_crud.seed_roles(db_session)
    await db_session.commit()
    yield


def at(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    return datetime(
        (day or TODAY).year,
        (day or TODAY).month,
        (day or TODAY).day,
        hour,
        minute,
        tzinfo=ZONE,
    )


async def plan_item_id(client: AsyncClient, code: str = "W1") -> str:
    """Store a one-task plan for today and return the task's uuid."""
    response = await client.post(
        f"{DAY_URL}/{TODAY.isoformat()}/plan",
        json={
            "title": "План",
            "sections": [
                {
                    "kind": "work",
                    "title": "Работа",
                    "items": [
                        {
                            "kind": "task",
                            "code": code,
                            "text_md": f"Задача {code}",
                            "window": "09:00-18:00",
                            "done_criterion": "готово",
                            "quarter_goal_id": 1,
                        }
                    ],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["sections"][0]["items"][0]["id"])


def manual_body(start: datetime, end: datetime, **extra: Any) -> dict[str, Any]:
    return {
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "local_date": TODAY.isoformat(),
        **extra,
    }


async def post_manual(
    client: AsyncClient, body: dict[str, Any], key: str | None = None
) -> Any:
    return await client.post(
        MANUAL_URL, json=body, headers={"Idempotency-Key": key or uuid.uuid4().hex}
    )


async def day(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{AGENT_URL}/activity/{TODAY.isoformat()}")
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestLink:
    async def test_a_manual_record_names_the_item_it_was_spent_on(
        self, client: AsyncClient
    ) -> None:
        item = await plan_item_id(client)

        response = await post_manual(
            client,
            manual_body(at(10), at(11), plan_item_id=item, note="Задача W1"),
        )

        assert response.status_code == 201, response.text
        assert response.json()["plan_item_id"] == item

    async def test_a_record_without_a_link_reads_null(
        self, client: AsyncClient
    ) -> None:
        response = await post_manual(client, manual_body(at(10), at(11)))
        assert response.json()["plan_item_id"] is None

    async def test_an_item_that_is_not_in_any_plan_is_a_422_not_a_500(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await post_manual(
            client, manual_body(at(10), at(11), plan_item_id=str(uuid.uuid4()))
        )

        assert response.status_code == 422
        assert "plan_item_id" in response.text
        assert (await db_session.execute(select(ActivityInterval))).first() is None

    async def test_a_correction_moves_the_link_and_null_removes_it(
        self, client: AsyncClient
    ) -> None:
        first = await plan_item_id(client, "W1")
        created = (
            await post_manual(client, manual_body(at(10), at(11), plan_item_id=first))
        ).json()

        cleared = await client.patch(
            f"{AGENT_URL}/activity/{created['id']}", json={"plan_item_id": None}
        )
        assert cleared.json()["plan_item_id"] is None

        restored = await client.patch(
            f"{AGENT_URL}/activity/{created['id']}", json={"plan_item_id": first}
        )
        assert restored.json()["plan_item_id"] == first

    async def test_a_correction_to_an_unknown_item_is_a_422(
        self, client: AsyncClient
    ) -> None:
        created = (await post_manual(client, manual_body(at(10), at(11)))).json()

        response = await client.patch(
            f"{AGENT_URL}/activity/{created['id']}",
            json={"plan_item_id": str(uuid.uuid4())},
        )

        assert response.status_code == 422

    async def test_deleting_the_item_leaves_the_interval_without_a_link(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The hour was worked whatever happened to the plan after."""
        item = await plan_item_id(client)
        await post_manual(client, manual_body(at(10), at(11), plan_item_id=item))

        await db_session.delete(await db_session.get(PlanItem, uuid.UUID(item)))
        await db_session.commit()

        row = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert row.plan_item_id is None
        assert row.duration_seconds == 3600


class TestTimePerTask:
    async def test_time_on_a_linked_item_is_a_task_not_work_outside_the_plan(
        self, client: AsyncClient
    ) -> None:
        item = await plan_item_id(client)
        await post_manual(client, manual_body(at(10), at(11), plan_item_id=item))

        body = await day(client)

        assert body["untasked_minutes"] == 0
        assert [(row["plan_item_id"], row["minutes"]) for row in body["tasks"]] == [
            (item, 60)
        ]

    async def test_two_records_of_one_item_overlapping_count_the_union(
        self, client: AsyncClient
    ) -> None:
        """10:00-11:00 and 10:30-11:30 on one task are 90 minutes, not 120."""
        item = await plan_item_id(client)
        await post_manual(client, manual_body(at(10), at(11), plan_item_id=item))
        await post_manual(
            client, manual_body(at(10, 30), at(11, 30), plan_item_id=item)
        )

        body = await day(client)

        assert [row["minutes"] for row in body["tasks"]] == [90]

    async def test_a_linked_and_an_unlinked_record_are_told_apart(
        self, client: AsyncClient
    ) -> None:
        item = await plan_item_id(client)
        await post_manual(client, manual_body(at(10), at(11), plan_item_id=item))
        await post_manual(client, manual_body(at(14), at(14) + timedelta(minutes=30)))

        body = await day(client)

        assert [row["minutes"] for row in body["tasks"]] == [60]
        assert body["untasked_minutes"] == 30
