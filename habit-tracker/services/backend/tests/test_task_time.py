# [review:need-review] PHASE-03/166
# summary: tests of `GET /day/{date}/task-time` — time per task of the day as a union of ranges, the «done with no trace» detector (a done mark, no interval and no commit), work outside the plan longer than half an hour, the share of untasked intervals over thirty days with an honest count of the days observed, a task delete that leaves its intervals standing, and a statement count that does not grow with the plan
"""
The closing of the day reads the time the agent measured against the plan.

The cases are the ways the numbers lie quietly: a task counted twice because two
records overlap, a task ticked as done with nothing behind it that nobody
notices, work outside the plan hidden in an evening notebook, and a share over
«thirty days» that is really over three.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import day_bounds, local_date, today_local
from app.crud import activity as activity_crud
from app.crud import day as day_crud
from app.crud import role as role_crud
from app.models.activity import ActivityInterval, ModeSchedule
from app.models.plan import PlanItem
from tests.conftest import test_engine

AGENT_URL = "/api/v1/agent"
MANUAL_URL = f"{AGENT_URL}/activity/manual"
DAY_URL = "/api/v1/day"

ZONE = ZoneInfo(settings.APP_TIMEZONE)
TODAY = today_local()
WINDOW_DAYS = 30


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
    when = day or TODAY
    return datetime(when.year, when.month, when.day, hour, minute, tzinfo=ZONE)


def task(code: str) -> dict[str, Any]:
    return {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": "09:00-18:00",
        "done_criterion": "готово",
        "quarter_goal_id": 1,
    }


async def store_plan(client: AsyncClient, *codes: str) -> dict[str, str]:
    """Store a plan of today with one task per code; returns `{code: uuid}`."""
    response = await client.post(
        f"{DAY_URL}/{TODAY.isoformat()}/plan",
        json={
            "title": "План",
            "sections": [
                {
                    "kind": "work",
                    "title": "Работа",
                    "items": [task(code) for code in codes],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    items = response.json()["sections"][0]["items"]
    return {item["code"]: str(item["id"]) for item in items}


async def spend(
    client: AsyncClient,
    start: datetime,
    end: datetime,
    item: str | None = None,
) -> int:
    body: dict[str, Any] = {
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "local_date": TODAY.isoformat(),
    }
    if item is not None:
        body["plan_item_id"] = item
    response = await client.post(
        MANUAL_URL, json=body, headers={"Idempotency-Key": uuid.uuid4().hex}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def mark(client: AsyncClient, item: str, state: str | None) -> None:
    response = await client.put(
        f"{DAY_URL}/{TODAY.isoformat()}/marks/{item}", json={"state": state}
    )
    assert response.status_code == 200, response.text


async def task_time(
    client: AsyncClient,
    committed: list[str] | None = None,
    *,
    on: date | None = None,
    commits_checked: bool | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"committed_item_id": committed or []}
    if commits_checked is not None:
        params["commits_checked"] = commits_checked
    response = await client.get(
        f"{DAY_URL}/{(on or TODAY).isoformat()}/task-time", params=params
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def row_of(
    start: datetime,
    end: datetime,
    *,
    item: uuid.UUID | None = None,
    plan_task_id: int | None = None,
    clickup_task_id: str | None = None,
) -> ActivityInterval:
    """An interval written straight to the table, for the shapes the API refuses to make."""
    return ActivityInterval(
        source="manual",
        started_at=start,
        ended_at=end,
        local_date=local_date(start),
        plan_item_id=item,
        plan_task_id=plan_task_id,
        clickup_task_id=clickup_task_id,
    )


def traceless_ids(body: dict[str, Any]) -> set[str]:
    return {row["plan_item_id"] for row in body["done_without_traces"]}


class TestTimePerTask:
    async def test_overlapping_records_of_one_task_count_the_union(
        self, client: AsyncClient
    ) -> None:
        """10:00-11:00 and 10:30-11:30 are 90 minutes of the task, not 120."""
        items = await store_plan(client, "A")
        await spend(client, at(10), at(11), items["A"])
        await spend(client, at(10, 30), at(11, 30), items["A"])

        body = await task_time(client)

        assert [(row["plan_item_id"], row["minutes"]) for row in body["tasks"]] == [
            (items["A"], 90)
        ]

    async def test_each_task_is_told_from_the_others(self, client: AsyncClient) -> None:
        items = await store_plan(client, "A", "B")
        await spend(client, at(10), at(11), items["A"])
        await spend(client, at(12), at(12, 20), items["B"])

        body = await task_time(client)

        assert {row["plan_item_id"]: row["minutes"] for row in body["tasks"]} == {
            items["A"]: 60,
            items["B"]: 20,
        }


class TestDoneWithoutTraces:
    async def test_a_done_task_with_no_interval_and_no_commit_is_listed(
        self, client: AsyncClient
    ) -> None:
        items = await store_plan(client, "A", "B")
        await mark(client, items["A"], "done")
        await mark(client, items["B"], "done")
        await spend(client, at(10), at(11), items["B"])

        body = await task_time(client)

        assert traceless_ids(body) == {items["A"]}
        assert body["done_without_traces"][0]["title"].startswith("Задача A")

    async def test_a_commit_is_a_trace(self, client: AsyncClient) -> None:
        items = await store_plan(client, "A")
        await mark(client, items["A"], "done")

        body = await task_time(client, committed=[items["A"]])

        assert body["done_without_traces"] == []
        assert body["commits_checked"] is True

    async def test_checked_commits_with_none_found_is_not_the_same_as_not_looking(
        self, client: AsyncClient
    ) -> None:
        items = await store_plan(client, "A")
        await mark(client, items["A"], "done")

        body = await task_time(client, commits_checked=True)

        assert body["commits_checked"] is True
        assert traceless_ids(body) == {items["A"]}

    async def test_without_a_commit_list_the_answer_says_commits_were_not_looked_at(
        self, client: AsyncClient
    ) -> None:
        items = await store_plan(client, "A")
        await mark(client, items["A"], "done")

        body = await task_time(client)

        assert body["commits_checked"] is False

    async def test_only_a_done_mark_counts(self, client: AsyncClient) -> None:
        """Failed, skipped and unmarked tasks are not «done», so they leave no gap."""
        items = await store_plan(client, "A", "B", "C")
        await mark(client, items["A"], "failed")
        await mark(client, items["B"], "skipped")

        body = await task_time(client)

        assert body["done_without_traces"] == []

    async def test_unticking_removes_the_task_from_the_list(
        self, client: AsyncClient
    ) -> None:
        items = await store_plan(client, "A")
        await mark(client, items["A"], "done")
        assert traceless_ids(await task_time(client)) == {items["A"]}

        await mark(client, items["A"], None)

        assert (await task_time(client))["done_without_traces"] == []


class TestDayBoundary:
    async def test_an_interval_across_midnight_is_split_between_the_two_days(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One hour before the boundary and one after are 60 and 60, never 120 and 120."""
        boundary = day_bounds(TODAY)[0]
        db_session.add(
            row_of(boundary - timedelta(hours=1), boundary + timedelta(hours=1))
        )
        await db_session.commit()

        today = await task_time(client)
        yesterday = await task_time(client, on=TODAY - timedelta(days=1))

        assert today["untasked_minutes"] == 60
        assert yesterday["untasked_minutes"] == 60
        assert [row["minutes"] for row in today["long_untasked"]] == [60]
        assert [row["minutes"] for row in yesterday["long_untasked"]] == [60]

    async def test_a_piece_under_half_an_hour_after_the_cut_is_not_work_outside_the_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        boundary = day_bounds(TODAY)[0]
        db_session.add(
            row_of(boundary - timedelta(hours=1), boundary + timedelta(minutes=10))
        )
        await db_session.commit()

        body = await task_time(client)

        assert body["untasked_minutes"] == 10
        assert body["long_untasked"] == []

    async def test_the_agent_day_roll_up_cuts_the_same_way(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        boundary = day_bounds(TODAY)[0]
        db_session.add(
            row_of(boundary - timedelta(hours=1), boundary + timedelta(hours=1))
        )
        await db_session.commit()

        response = await client.get(f"{AGENT_URL}/activity/{TODAY.isoformat()}")

        assert response.json()["untasked_minutes"] == 60


class TestOneTaskInManyGroups:
    async def test_the_same_task_with_and_without_a_clickup_id_is_one_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """10:00-11:00 on X and 10:30-11:30 on X with a ClickUp id are 90 minutes of X."""
        items = await store_plan(client, "A")
        item = uuid.UUID(items["A"])
        db_session.add(row_of(at(10), at(11), item=item))
        db_session.add(
            row_of(at(10, 30), at(11, 30), item=item, clickup_task_id="86abc")
        )
        await db_session.commit()

        body = await task_time(client)

        assert [(row["plan_item_id"], row["minutes"]) for row in body["tasks"]] == [
            (items["A"], 90)
        ]
        assert body["other_linked_minutes"] == 0


class TestOtherLinks:
    async def test_time_tied_only_by_a_numeric_or_clickup_id_is_not_lost(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The editor of `#160` writes `plan_task_id`; that hour belongs to no plan item and no gap."""
        items = await store_plan(client, "A")
        db_session.add(row_of(at(9), at(10), item=uuid.UUID(items["A"])))
        db_session.add(row_of(at(11), at(12), plan_task_id=5))
        db_session.add(row_of(at(13), at(13, 30), clickup_task_id="86abc"))
        db_session.add(row_of(at(15), at(15, 20)))
        await db_session.commit()

        body = await task_time(client)

        assert body["other_linked_minutes"] == 90
        assert body["untasked_minutes"] == 20
        assert [row["minutes"] for row in body["tasks"]] == [60]
        assert body["long_untasked"] == []

    async def test_the_three_figures_add_up_to_the_time_measured(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        items = await store_plan(client, "A", "B")
        boundary = day_bounds(TODAY)[0]
        db_session.add(row_of(at(9), at(10), item=uuid.UUID(items["A"])))
        db_session.add(row_of(at(10, 30), at(11), item=uuid.UUID(items["B"])))
        db_session.add(row_of(at(12), at(12, 45), plan_task_id=7))
        db_session.add(row_of(at(14), at(14, 40)))
        db_session.add(
            row_of(boundary - timedelta(minutes=30), boundary + timedelta(minutes=30))
        )
        await db_session.commit()
        body = await task_time(client)

        total = (
            sum(row["minutes"] for row in body["tasks"])
            + body["untasked_minutes"]
            + body["other_linked_minutes"]
        )
        # 60 + 30 on the two tasks, 45 on a numeric id, 40 on nothing, and the
        # 30 minutes of the overnight record that fall after the cut.
        assert total == 60 + 30 + 45 + 40 + 30


class TestOverlappingKinds:
    async def test_the_three_figures_add_up_when_records_of_different_kinds_overlap(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Task X 10:00-11:30, a numeric id 11:00-12:00, ClickUp 11:30-12:30 and
        nothing 12:00-12:40: 160 minutes measured, not 220.
        """
        items = await store_plan(client, "A")
        db_session.add(row_of(at(10), at(11, 30), item=uuid.UUID(items["A"])))
        db_session.add(row_of(at(11), at(12), plan_task_id=5))
        db_session.add(row_of(at(11, 30), at(12, 30), clickup_task_id="86abc"))
        db_session.add(row_of(at(12), at(12, 40)))
        await db_session.commit()

        body = await task_time(client)

        assert [row["minutes"] for row in body["tasks"]] == [90]
        assert (
            body["other_linked_minutes"] == 60
        )  # 11:30-12:30 minus nothing; 11:00-11:30 is X's
        assert body["untasked_minutes"] == 10  # 12:30-12:40 only
        assert (
            sum(row["minutes"] for row in body["tasks"])
            + body["untasked_minutes"]
            + body["other_linked_minutes"]
        ) == 160

    async def test_an_agent_interval_under_a_task_timer_is_the_tasks_time_not_work_outside_the_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The panel's timer links 10:00-11:00 to A; the agent measured Safari 10:00-10:50 unlinked."""
        items = await store_plan(client, "A")
        db_session.add(row_of(at(10), at(11), item=uuid.UUID(items["A"])))
        db_session.add(row_of(at(10), at(10, 50)))
        await db_session.commit()

        body = await task_time(client)

        assert [row["minutes"] for row in body["tasks"]] == [60]
        assert body["untasked_minutes"] == 0
        assert body["long_untasked"] == []

    async def test_work_outside_the_plan_is_only_the_part_no_task_covers(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An agent interval 10:00-11:30 with a timer on 10:00-10:40 leaves 10:40-11:30 outside the plan."""
        items = await store_plan(client, "A")
        db_session.add(row_of(at(10), at(10, 40), item=uuid.UUID(items["A"])))
        agent = row_of(at(10), at(11, 30))
        db_session.add(agent)
        await db_session.commit()

        body = await task_time(client)

        assert body["untasked_minutes"] == 50
        assert [
            (row["interval_id"], row["minutes"]) for row in body["long_untasked"]
        ] == [(agent.id, 50)]
        piece_start = body["long_untasked"][0]["started_at"].replace("Z", "+00:00")
        assert datetime.fromisoformat(piece_start) == at(10, 40)


class TestWorkOutsideThePlan:
    async def test_an_untasked_interval_over_half_an_hour_is_listed(
        self, client: AsyncClient
    ) -> None:
        long_id = await spend(client, at(14), at(14, 45))
        await spend(client, at(16), at(16, 20))

        body = await task_time(client)

        assert [row["interval_id"] for row in body["long_untasked"]] == [long_id]
        assert body["long_untasked"][0]["minutes"] == 45
        assert body["untasked_minutes"] == 65

    async def test_exactly_half_an_hour_is_listed_and_a_task_hour_is_not(
        self, client: AsyncClient
    ) -> None:
        items = await store_plan(client, "A")
        half = await spend(client, at(14), at(14, 30))
        await spend(client, at(10), at(11), items["A"])

        body = await task_time(client)

        assert [row["interval_id"] for row in body["long_untasked"]] == [half]


class TestUntaskedShare:
    async def seed_days(self, db_session: AsyncSession, days: list[int]) -> None:
        """One untasked and one tasked interval on each of `days` ago."""
        items = await store_plan_item(db_session)
        for ago in days:
            day = TODAY - timedelta(days=ago)
            for hour, linked in ((9, None), (10, items)):
                db_session.add(
                    ActivityInterval(
                        source="manual",
                        started_at=at(hour, day=day),
                        ended_at=at(hour, 10, day=day),
                        local_date=day,
                        plan_item_id=linked,
                    )
                )
        await db_session.commit()

    async def test_the_share_counts_intervals_without_a_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await store_plan(client, "A")
        await self.seed_days(db_session, [0, 1, 2])

        share = (await task_time(client))["untasked_share"]

        assert (share["intervals"], share["untasked"]) == (6, 3)
        assert share["share"] == pytest.approx(0.5)

    async def test_a_short_history_says_how_many_days_it_has(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Data from 3 days ago is 4 days observed, never «30 дней»."""
        await store_plan(client, "A")
        await self.seed_days(db_session, [3, 0])

        share = (await task_time(client))["untasked_share"]

        assert share["window_days"] == WINDOW_DAYS
        assert share["observed_days"] == 4

    async def test_a_full_window_reports_thirty_days_and_ignores_older_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await store_plan(client, "A")
        await self.seed_days(db_session, [WINDOW_DAYS + 5, WINDOW_DAYS - 1, 0])

        share = (await task_time(client))["untasked_share"]

        assert share["observed_days"] == WINDOW_DAYS
        assert share["intervals"] == 4

    async def test_no_intervals_has_no_share(self, client: AsyncClient) -> None:
        share = (await task_time(client))["untasked_share"]

        assert share["share"] is None
        assert share["observed_days"] == 0


async def store_plan_item(db_session: AsyncSession) -> uuid.UUID:
    """The uuid of any task stored by `store_plan` in this test."""
    found = (
        await db_session.execute(select(PlanItem.id).where(PlanItem.kind == "task"))
    ).scalars()
    return next(iter(found))


class TestDeletingATask:
    async def test_the_intervals_stay_with_no_link(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        items = await store_plan(client, "A")
        await spend(client, at(10), at(11), items["A"])
        await mark(client, items["A"], "done")

        await db_session.delete(await db_session.get(PlanItem, uuid.UUID(items["A"])))
        await db_session.commit()

        row = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert row.plan_item_id is None
        assert row.plan_task_id is None
        assert row.duration_seconds == 3600
        body = await task_time(client)
        assert body["tasks"] == []
        assert body["untasked_minutes"] == 60


class TestStatementCount:
    async def count_statements(self, client: AsyncClient) -> int:
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(str(args[2]))

        event.listen(test_engine.sync_engine, "before_cursor_execute", count)
        try:
            await task_time(client)
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", count)
        return len(statements)

    async def test_reading_costs_the_same_with_one_task_or_four(
        self, client: AsyncClient
    ) -> None:
        """The class of error: a query per task for its time or its marks."""
        items = await store_plan(client, "A")
        await mark(client, items["A"], "done")
        await spend(client, at(10), at(11), items["A"])
        small = await self.count_statements(client)

        more = await store_plan(client, "A", "B", "C", "D")
        for index, code in enumerate("ABCD"):
            await mark(client, more[code], "done")
            await spend(client, at(12 + index), at(12 + index, 20), more[code])
        large = await self.count_statements(client)

        assert large == small
