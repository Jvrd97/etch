# [review:need-review] PHASE-03/160
# summary: tests of the two ADR scenarios — two hours in VS Code corrected to an hour and a half on task X give exactly 1.5 h in the day's roll-up with `is_corrected` set and `source` still `agent`, and a manual 10:00-12:00 laid over an automatic 10:30-11:00 on the same task gives two hours rather than two and a half; plus the idempotency of a manual record, two honest records starting at the same minute, and a correction that would put the end before the start

"""
Tests of the correction after the fact and of the union-of-ranges count.

The number the ticket exists for is «время по задаче». `SUM(duration_seconds)`
over the same rows is plausible and larger, because overlapping records are
allowed on purpose — a person may write «созвон» over an hour the agent charged
to Chrome. The tests below are written on overlapping data for exactly that
reason: they fail on a `SUM` implementation and pass on a union.
"""

from collections.abc import AsyncGenerator
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import today_local
from app.crud import activity as activity_crud
from app.crud import role as role_crud
from app.models.activity import (
    ACTIVITY_SOURCE_AGENT,
    ACTIVITY_SOURCE_MANUAL,
    ActivityInterval,
    ModeSchedule,
    TrackedApp,
)

AGENT_URL = "/api/v1/agent"
VSCODE = "com.microsoft.VSCode"
ZONE = ZoneInfo(settings.APP_TIMEZONE)

DAY = today_local()
TASK_X = 4242


@pytest.fixture(autouse=True)
async def seeded(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The settings row, the schedule for today and one application."""
    await activity_crud.seed_settings(db_session)
    await role_crud.seed_roles(db_session)
    db_session.add(ModeSchedule(weekday=DAY.isoweekday() % 7, kind="work"))
    db_session.add(TrackedApp(bundle_id=VSCODE, display_name="VS Code"))
    await db_session.commit()
    yield


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


async def send_auto(
    client: AsyncClient, start: datetime, end: datetime
) -> dict[str, Any]:
    """One automatic interval, and the stored row it became."""
    response = await client.post(
        f"{AGENT_URL}/activity",
        json={
            "intervals": [
                {
                    "bundle_id": VSCODE,
                    "started_at": start.isoformat(),
                    "ended_at": end.isoformat(),
                    "local_date": start.date().isoformat(),
                }
            ]
        },
    )
    assert response.status_code == 201, response.text
    day = await client.get(f"{AGENT_URL}/activity/{DAY.isoformat()}")
    return dict(day.json()["intervals"][-1])


async def send_manual(
    client: AsyncClient,
    start: datetime,
    end: datetime,
    *,
    key: str,
    task: int | None = TASK_X,
) -> Any:
    return await client.post(
        f"{AGENT_URL}/activity/manual",
        headers={"Idempotency-Key": key},
        json={
            "started_at": start.isoformat(),
            "ended_at": end.isoformat(),
            "local_date": start.date().isoformat(),
            "plan_task_id": task,
            "note": "созвон",
        },
    )


async def day_body(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{AGENT_URL}/activity/{DAY.isoformat()}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def task_minutes(body: dict[str, Any], task_id: int) -> int:
    for row in body["tasks"]:
        if row["plan_task_id"] == task_id:
            return int(row["minutes"])
    return 0


# --- два сценария ADR --------------------------------------------------------


class TestAdrScenarios:
    async def test_two_hours_corrected_to_an_hour_and_a_half_on_a_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        «Ручной ввод первичен» перестаёт быть декларацией.

        Авто-интервал 2 ч в VS Code правится на 1.5 ч и привязывается к задаче X:
        в свёртке дня по задаче ровно полтора часа, `is_corrected` стоит,
        `corrected_at` заполнен, `source` остался `agent`.
        """
        stored = await send_auto(client, at(10), at(12))
        response = await client.patch(
            f"{AGENT_URL}/activity/{stored['id']}",
            json={"ended_at": at(11, 30).isoformat(), "plan_task_id": TASK_X},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == ACTIVITY_SOURCE_AGENT
        assert body["duration_seconds"] == 90 * 60
        assert body["corrected_at"] is not None

        row = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert row.is_corrected is True

        assert task_minutes(await day_body(client), TASK_X) == 90

    async def test_a_manual_record_over_an_automatic_one_does_not_double(
        self, client: AsyncClient
    ) -> None:
        """
        Ручная запись 10:00-12:00 поверх авто 10:30-11:00 по той же задаче — 2 ч.

        `SUM(duration_seconds)` дал бы 2.5 ч: правдоподобное и завышенное число.
        Именно поэтому время по задаче считается длиной объединения диапазонов.
        """
        auto = await send_auto(client, at(10, 30), at(11))
        patched = await client.patch(
            f"{AGENT_URL}/activity/{auto['id']}", json={"plan_task_id": TASK_X}
        )
        assert patched.status_code == 200, patched.text

        created = await send_manual(client, at(10), at(12), key="call-1")
        assert created.status_code == 201, created.text

        assert task_minutes(await day_body(client), TASK_X) == 120


# --- идемпотентность ручной записи ------------------------------------------


class TestManualRecord:
    async def test_the_same_key_twice_makes_one_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        first = await send_manual(client, at(10), at(11), key="call-1")
        second = await send_manual(client, at(10), at(11), key="call-1")
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

        rows = (await db_session.execute(select(ActivityInterval))).scalars().all()
        assert len(list(rows)) == 1

    async def test_two_records_at_the_same_minute_coexist(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Естественный ключ ручную запись не ловит, и это правильно.

        Человек вправе записать два дела в одно окно времени; схлопывать их
        значило бы решать за него, что одно из них не было.
        """
        first = await send_manual(client, at(10), at(11), key="call-1")
        second = await send_manual(client, at(10), at(11), key="call-2")
        assert first.json()["id"] != second.json()["id"]

        rows = (await db_session.execute(select(ActivityInterval))).scalars().all()
        assert len(list(rows)) == 2

    async def test_the_same_key_with_other_bounds_is_a_conflict(
        self, client: AsyncClient
    ) -> None:
        """Молча отдать чужую строку значило бы потерять ту, что писали."""
        await send_manual(client, at(10), at(11), key="call-1")
        clash = await send_manual(client, at(14), at(15), key="call-1")
        assert clash.status_code == 409

    async def test_a_manual_record_names_no_application(
        self, client: AsyncClient
    ) -> None:
        """«Созвон» — не приложение перед окном, и в свёртке по приложениям его нет."""
        await send_manual(client, at(10), at(11), key="call-1")
        created = (await send_manual(client, at(10), at(11), key="call-1")).json()
        assert created["app_id"] is None
        assert created["source"] == ACTIVITY_SOURCE_MANUAL

    async def test_a_backwards_manual_record_is_refused(
        self, client: AsyncClient
    ) -> None:
        response = await send_manual(client, at(12), at(10), key="call-1")
        assert response.status_code == 422


# --- правка не ломает строку -------------------------------------------------


class TestCorrection:
    async def test_an_end_before_the_start_is_refused_and_nothing_changes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        stored = await send_auto(client, at(10), at(12))
        response = await client.patch(
            f"{AGENT_URL}/activity/{stored['id']}",
            json={"ended_at": at(9).isoformat()},
        )
        assert response.status_code == 422

        row = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert row.ended_at == at(12)
        assert row.is_corrected is False

    async def test_an_unknown_interval_is_a_404(self, client: AsyncClient) -> None:
        response = await client.patch(
            f"{AGENT_URL}/activity/999999", json={"plan_task_id": TASK_X}
        )
        assert response.status_code == 404

    async def test_unlinking_a_task_is_not_the_same_as_not_touching_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        `null` в теле — «убрать привязку», отсутствие ключа — «не трогать».

        Склеить их значило бы стирать привязку на каждой правке заметки.
        """
        stored = await send_auto(client, at(10), at(11))
        await client.patch(
            f"{AGENT_URL}/activity/{stored['id']}", json={"plan_task_id": TASK_X}
        )
        await client.patch(
            f"{AGENT_URL}/activity/{stored['id']}", json={"note": "рефакторинг"}
        )
        row = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert row.plan_task_id == TASK_X

        await client.patch(
            f"{AGENT_URL}/activity/{stored['id']}", json={"plan_task_id": None}
        )
        await db_session.refresh(row)
        assert row.plan_task_id is None

    async def test_correcting_the_bounds_restates_the_role_minutes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Правка живёт не только на экране активности.

        Границы двинулись — минуты ролей за этот день пересчитаны, иначе `/roles`
        продолжал бы показывать два часа там, где человек написал полтора.
        """
        stored = await send_auto(client, at(10), at(12))
        blocks = await role_crud.day_time_blocks(db_session, DAY)
        assert [block.minutes for block in blocks] == [120]

        await client.patch(
            f"{AGENT_URL}/activity/{stored['id']}",
            json={"ended_at": at(11, 30).isoformat()},
        )
        db_session.expire_all()
        blocks = await role_crud.day_time_blocks(db_session, DAY)
        assert [block.minutes for block in blocks] == [90]


# --- «без задачи» ------------------------------------------------------------


class TestUntasked:
    async def test_work_outside_the_plan_is_its_own_number(
        self, client: AsyncClient
    ) -> None:
        """
        Сценарий Payment-сервиса 28.08: работа сверх плана видна в тот же час.
        """
        auto = await send_auto(client, at(10), at(11))
        await client.patch(
            f"{AGENT_URL}/activity/{auto['id']}", json={"plan_task_id": TASK_X}
        )
        await send_auto(client, at(14), at(16))

        body = await day_body(client)
        assert task_minutes(body, TASK_X) == 60
        assert body["untasked_minutes"] == 120

    async def test_a_day_where_everything_is_linked_shows_zero(
        self, client: AsyncClient
    ) -> None:
        auto = await send_auto(client, at(10), at(11))
        await client.patch(
            f"{AGENT_URL}/activity/{auto['id']}", json={"plan_task_id": TASK_X}
        )
        body = await day_body(client)
        assert body["untasked_minutes"] == 0


# --- никакого SUM ------------------------------------------------------------


async def test_no_endpoint_answers_task_time_with_a_plain_sum(
    client: AsyncClient,
) -> None:
    """
    Проверяется на пересекающихся данных, а не чтением кода.

    Три записи по одной и той же задаче, перекрывающие друг друга: сумма
    длительностей — 5 часов, объединение — 3. Реализация на `SUM` эту проверку
    не проходит.
    """
    first = await send_auto(client, at(9), at(12))
    await client.patch(
        f"{AGENT_URL}/activity/{first['id']}", json={"plan_task_id": TASK_X}
    )
    await send_manual(client, at(10), at(11), key="call-1")
    await send_manual(client, at(11), at(12), key="call-2")

    body = await day_body(client)
    assert task_minutes(body, TASK_X) == 180

    total_duration = sum(row["duration_seconds"] for row in body["intervals"])
    assert total_duration == 5 * 60 * 60
