# [review:approved] PHASE-03/155
# summary: proves retry idempotency, unknown-app atomic rejection, and the 500 interval request limit
"""Acceptance tests for the first mac agent activity batch."""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import today_local
from app.crud import activity as activity_crud
from app.crud import role as role_crud
from app.models.activity import ActivityInterval, ModeSchedule, TrackedApp

AGENT_URL = "/api/v1/agent"
APP_BUNDLE = "com.example.editor"
ZONE = ZoneInfo(settings.APP_TIMEZONE)


@pytest.fixture(autouse=True)
async def seed_agent_dependencies(
    db_session: AsyncSession,
) -> AsyncGenerator[None, None]:
    await activity_crud.seed_settings(db_session)
    await role_crud.seed_roles(db_session)
    db_session.add(ModeSchedule(weekday=today_local().isoweekday() % 7, kind="work"))
    db_session.add(TrackedApp(bundle_id=APP_BUNDLE, display_name="Editor"))
    await db_session.commit()
    yield


def interval_payload(bundle_id: str = APP_BUNDLE, minute: int = 0) -> dict[str, object]:
    day = today_local()
    start = datetime(day.year, day.month, day.day, 10, tzinfo=ZONE) + timedelta(
        minutes=minute
    )
    return {
        "bundle_id": bundle_id,
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=1)).isoformat(),
        "local_date": day.isoformat(),
        "title": None,
        "title_source": "dropped",
    }


class TestActivityBatch:
    async def test_resending_the_same_batch_updates_one_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        batch = {"intervals": [interval_payload()]}

        first = await client.post(f"{AGENT_URL}/activity", json=batch)
        retry = await client.post(f"{AGENT_URL}/activity", json=batch)

        assert first.status_code == retry.status_code == 201
        count = await db_session.scalar(
            select(func.count()).select_from(ActivityInterval)
        )
        assert count == 1
        stored = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert stored.title is None
        assert stored.title_source == "dropped"

    async def test_unknown_app_rejects_the_whole_batch(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            f"{AGENT_URL}/activity",
            json={
                "intervals": [
                    interval_payload(),
                    interval_payload("com.unknown.app", 2),
                ]
            },
        )

        assert response.status_code == 422
        assert "com.unknown.app" in response.text
        count = await db_session.scalar(
            select(func.count()).select_from(ActivityInterval)
        )
        assert count == 0

    async def test_batch_over_five_hundred_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            f"{AGENT_URL}/activity",
            json={
                "intervals": [interval_payload(minute=index) for index in range(501)]
            },
        )

        assert response.status_code == 422

    async def test_batch_of_five_hundred_is_accepted_and_persisted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            f"{AGENT_URL}/activity",
            json={
                "intervals": [interval_payload(minute=index) for index in range(500)]
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["intervals_written"] == 500
        count = await db_session.scalar(
            select(func.count()).select_from(ActivityInterval)
        )
        assert count == 500
