"""
Tests for the day endpoints: GET /api/v1/day and GET /api/v1/day/{date}.
"""

# [review:need-review] PHASE-03/86
# summary: API tests — a day is created lazily with kind/is_nocode frozen, opened_at stays null, a plan-less day answers instead of 404ing, and the route needs the API key like every other
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import day as day_crud
from app.day.rules import KIND_OFF, KIND_WORK
from app.main import app

DAY_URL = "/api/v1/day"

# A Sunday, and the day this vertical was written.
SUNDAY = date(2026, 8, 30)
# A Friday under the legacy canon.
LEGACY_FRIDAY = date(2026, 8, 14)
# A Tuesday, which the seeded rule calls a no-code day.
NOCODE_TUESDAY = date(2026, 9, 1)


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it.

    The test database is built by `create_all`, which never runs the migration's
    seed, so without this every day request would 404 on a canon that describes
    no date at all.
    """
    await day_crud.seed_rules(db_session)
    yield


async def test_a_day_answers_with_its_date_kind_and_rule(client: AsyncClient) -> None:
    """The acceptance case: the phone opens /day/2026-08-30 and sees all three."""
    response = await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["day"]["date"] == SUNDAY.isoformat()
    assert body["day"]["kind"] == KIND_OFF
    assert body["rule"]["work_cap_min"] == 480
    assert body["rule"]["valid_from"] == "2026-08-17"


async def test_a_historic_day_is_answered_by_the_legacy_rule(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{DAY_URL}/{LEGACY_FRIDAY.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["day"]["kind"] == KIND_WORK
    assert body["rule"]["work_cap_min"] == 600
    assert body["rule"]["tasks_required_ratio"] == "0.80"


async def test_a_nocode_day_says_so(client: AsyncClient) -> None:
    response = await client.get(f"{DAY_URL}/{NOCODE_TUESDAY.isoformat()}")

    assert response.status_code == 200
    assert response.json()["day"]["is_nocode"] is True


async def test_a_day_nobody_opened_reports_no_opening_time(
    client: AsyncClient,
) -> None:
    """
    Reading a day is not the same event as opening it, and the difference is the
    reason the column exists: "nobody came" has to stay distinguishable from
    "came and did nothing".
    """
    response = await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")

    body = response.json()
    assert body["day"]["opened_at"] is None
    assert body["day"]["last_touched_at"] is None


async def test_a_day_without_a_plan_answers_instead_of_404ing(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["has_plan"] is False


async def test_the_bare_route_answers_today(client: AsyncClient) -> None:
    """`/day` is the entry point; which day "today" is comes from `local_date()`."""
    response = await client.get(DAY_URL)

    assert response.status_code == 200
    assert response.json()["day"]["date"] is not None


async def test_a_date_no_rule_covers_is_a_404(client: AsyncClient) -> None:
    response = await client.get(f"{DAY_URL}/1999-01-01")

    assert response.status_code == 404
    assert "1999-01-01" in response.json()["detail"]


async def test_a_malformed_date_is_refused(client: AsyncClient) -> None:
    response = await client.get(f"{DAY_URL}/not-a-date")

    assert response.status_code == 422


async def test_the_day_route_requires_the_api_key(db_session: AsyncSession) -> None:
    """Ручки дня закрыты наравне с остальными (`API_ROUTERS` в app/main.py)."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        app=app, base_url="http://test", follow_redirects=True
    ) as bare:
        response = await bare.get(f"{DAY_URL}/{SUNDAY.isoformat()}")
    app.dependency_overrides.clear()

    assert response.status_code == 401


async def test_the_day_is_created_once_and_reread_afterwards(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")
    first = await day_crud.get_day(db_session, SUNDAY)
    assert first is not None
    created_at = first.created_at

    await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")
    second = await day_crud.get_day(db_session, SUNDAY)
    assert second is not None
    assert second.created_at == created_at


async def test_a_new_week_schedule_does_not_relabel_days_already_created(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The acceptance case for materialisation: the Sunday stays a day off after a
    rule that calls Sunday a working day is inserted. A derived answer would
    rewrite it.
    """
    await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")
    assert (await day_crud.get_day(db_session, SUNDAY)) is not None

    rules = await day_crud.list_rules(db_session)
    current = max(rules, key=lambda rule: rule.valid_from)
    current.valid_to = date(2026, 9, 1)
    await day_crud.seed_rules(db_session)  # keeps the seeded rows untouched
    db_session.add(
        type(current)(
            valid_from=date(2026, 9, 1),
            valid_to=None,
            timezone=current.timezone,
            day_start_hour=current.day_start_hour,
            work_cap_min=current.work_cap_min,
            work_hard_cap_min=current.work_hard_cap_min,
            work_stop_at=current.work_stop_at,
            max_work_tasks=current.max_work_tasks,
            tasks_required_ratio=current.tasks_required_ratio,
            overtime_disqualifies=current.overtime_disqualifies,
            workdays=[1, 2, 3, 4, 5, 6, 7],
            nocode_days=[],
            required_anchors=list(current.required_anchors),
            note_md="каждый день рабочий",
        )
    )
    await db_session.flush()

    response = await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")
    assert response.json()["day"]["kind"] == KIND_OFF
