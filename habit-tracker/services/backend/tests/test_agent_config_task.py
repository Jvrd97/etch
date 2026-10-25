# [review:need-review] PHASE-03/159
# summary: tests of what the floating panel polls — GET /agent/config names the task the day is on right now (the one whose window holds the moment, else the next one, never a marked or a passed one), carries the path of the day page with the same date the panel shows, and answers 304 without a body to a poll whose ETag still matches
"""
Tests of the task and the day page that `GET /agent/config` hands to the panel.

The window on the mac shows one task and one date, and both come from this
response. The cases are about the moments a wrong answer is cheapest to miss:
the second a window opens, a task someone already ticked, an evening with
nothing left, and a poll that has nothing new to hear.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import agent as agent_api
from app.core.config import settings
from app.core.daytime import today_local
from app.crud import activity as activity_crud
from app.crud import day as day_crud
from app.models.activity import ModeSchedule

AGENT_URL = "/api/v1/agent"
CONFIG_URL = f"{AGENT_URL}/config"
DAY_URL = "/api/v1/day"

ZONE = ZoneInfo(settings.APP_TIMEZONE)
TODAY = today_local()
PLAN_URL = f"{DAY_URL}/{TODAY.isoformat()}/plan"


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The settings row, today's schedule line, the day rules and the goal tasks name."""
    await activity_crud.seed_settings(db_session)
    db_session.add(ModeSchedule(weekday=TODAY.isoweekday() % 7, kind="work"))
    await day_crud.seed_rules(db_session)
    await db_session.commit()
    yield


def freeze(monkeypatch: pytest.MonkeyPatch, hour: int, minute: int = 0) -> datetime:
    """Make the config see `hour:minute` of today on the wall clock."""
    moment = datetime.combine(TODAY, time(hour, minute), tzinfo=ZONE)
    monkeypatch.setattr(agent_api, "now_utc", lambda: moment)
    return moment


def task(code: str, window: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "готово",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


async def post_plan(client: AsyncClient, *items: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        PLAN_URL,
        json={
            "title": "План",
            "sections": [{"kind": "work", "title": "Работа", "items": list(items)}],
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def item_id(plan: dict[str, Any], code: str) -> str:
    for section in plan["sections"]:
        for item in section["items"]:
            if item["code"] == code:
                return str(item["id"])
    raise AssertionError(f"no item {code}")


async def mark(
    client: AsyncClient, plan: dict[str, Any], code: str, state: str
) -> None:
    response = await client.put(
        f"{DAY_URL}/{TODAY.isoformat()}/marks/{item_id(plan, code)}",
        json={"state": state},
    )
    assert response.status_code == 200, response.text


def instant(value: str) -> datetime:
    """An ISO moment as the API prints it; `fromisoformat` of 3.10 refuses a `Z`."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def config(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(CONFIG_URL)
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestCurrentTask:
    async def test_a_day_without_a_plan_has_no_current_task(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        freeze(monkeypatch, 9)
        assert (await config(client))["current_task"] is None

    async def test_the_task_whose_window_holds_the_moment_is_current(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = await post_plan(
            client, task("W1", "08:00-09:00"), task("W2", "09:00-11:00")
        )
        freeze(monkeypatch, 9, 30)

        current = (await config(client))["current_task"]

        assert current["id"] == item_id(plan, "W2")
        assert current["title"] == "Задача W2"

    async def test_the_window_opens_at_its_first_minute_and_closes_at_its_last(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Half-open: at 09:00 the 08:00-09:00 task is behind, the 09:00 one is on."""
        plan = await post_plan(
            client, task("W1", "08:00-09:00"), task("W2", "09:00-10:00")
        )
        freeze(monkeypatch, 9)

        assert (await config(client))["current_task"]["id"] == item_id(plan, "W2")

    async def test_between_windows_the_next_task_is_current(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = await post_plan(
            client, task("W1", "08:00-09:00"), task("W2", "14:00-15:00")
        )
        freeze(monkeypatch, 12)

        assert (await config(client))["current_task"]["id"] == item_id(plan, "W2")

    async def test_a_marked_task_is_not_current_any_more(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ticking the running task hands the window to the one after it."""
        plan = await post_plan(
            client, task("W1", "09:00-11:00"), task("W2", "13:00-14:00")
        )
        freeze(monkeypatch, 10)
        assert (await config(client))["current_task"]["id"] == item_id(plan, "W1")

        await mark(client, plan, "W1", "done")

        assert (await config(client))["current_task"]["id"] == item_id(plan, "W2")

    async def test_a_skipped_task_is_not_current_either(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = await post_plan(client, task("W1", "09:00-11:00"))
        await mark(client, plan, "W1", "skipped")
        freeze(monkeypatch, 10)

        assert (await config(client))["current_task"] is None

    async def test_when_every_window_is_behind_there_is_no_current_task(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await post_plan(client, task("W1", "08:00-09:00"))
        freeze(monkeypatch, 20)

        assert (await config(client))["current_task"] is None

    async def test_only_tasks_count_not_the_other_kinds_of_item(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await post_plan(
            client,
            {"kind": "bullet", "text_md": "купить воду", "window": "09:00-10:00"},
        )
        freeze(monkeypatch, 9, 30)

        assert (await config(client))["current_task"] is None

    async def test_the_window_of_the_task_travels_with_it(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await post_plan(client, task("W1", "09:00-10:30"))
        freeze(monkeypatch, 9, 30)

        current = (await config(client))["current_task"]

        assert instant(current["starts_at"]) == datetime.combine(
            TODAY, time(9), tzinfo=ZONE
        )
        assert instant(current["ends_at"]) == datetime.combine(
            TODAY, time(10, 30), tzinfo=ZONE
        )


class TestDayPage:
    async def test_the_path_of_the_page_names_the_date_the_window_shows(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One date for the label and for the button, from one response."""
        freeze(monkeypatch, 9)

        body = await config(client)

        assert body["day_path"] == f"/day/{body['day_mode']['date']}"
        assert body["day_mode"]["date"] == TODAY.isoformat()

    async def test_the_date_follows_the_day_boundary_not_the_calendar(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """At 02:00 the day is still yesterday's: the page the button opens is too."""
        moment = datetime.combine(TODAY, time(2), tzinfo=ZONE)
        monkeypatch.setattr(agent_api, "now_utc", lambda: moment)

        body = await config(client)

        assert body["day_mode"]["date"] == body["day_path"].removeprefix("/day/")
        assert body["day_mode"]["date"] != TODAY.isoformat()


class TestETag:
    async def test_the_answer_carries_an_etag(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        freeze(monkeypatch, 9)
        response = await client.get(CONFIG_URL)
        assert response.headers["ETag"].startswith('"')

    async def test_a_poll_with_the_same_tag_gets_no_body(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        freeze(monkeypatch, 9)
        tag = (await client.get(CONFIG_URL)).headers["ETag"]

        again = await client.get(CONFIG_URL, headers={"If-None-Match": tag})

        assert again.status_code == 304
        assert again.content == b""
        assert again.headers["ETag"] == tag

    async def test_a_changed_task_changes_the_tag(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The window must hear about a tick done in the browser, not 304 over it."""
        plan = await post_plan(
            client, task("W1", "09:00-11:00"), task("W2", "13:00-14:00")
        )
        freeze(monkeypatch, 10)
        tag = (await client.get(CONFIG_URL)).headers["ETag"]

        await mark(client, plan, "W1", "done")
        again = await client.get(CONFIG_URL, headers={"If-None-Match": tag})

        assert again.status_code == 200
        assert again.headers["ETag"] != tag
        assert again.json()["current_task"]["id"] == item_id(plan, "W2")

    async def test_a_changed_setting_changes_the_tag(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        freeze(monkeypatch, 9)
        tag = (await client.get(CONFIG_URL)).headers["ETag"]

        await client.put(f"{AGENT_URL}/settings", json={"sampling_seconds": 17})
        again = await client.get(CONFIG_URL, headers={"If-None-Match": tag})

        assert again.status_code == 200
        assert again.json()["sampling_seconds"] == 17
