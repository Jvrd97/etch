"""
Tests for recording a relapse on a chosen day: «drank last Friday and Thursday».
"""

# [review:need-review] PHASE-03/294
# summary: POST /categories/{id}/relapses takes an optional entry_date — the relapse lands on that day, the streak and the last relapse date are recomputed from it, a future day is refused, the repeat window is per day, and a recorded relapse moves to another day by PATCH /entries/{id}

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.models import Entry


async def _create_avoid(client: AsyncClient) -> int:
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Алкоголь",
            "streak_mode": "avoid",
            "fields": [{"name": "Пил", "field_type": "boolean", "order": 0}],
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def _day(days_ago: int) -> str:
    return (today_local() - timedelta(days=days_ago)).isoformat()


@pytest.mark.asyncio
class TestRelapseOnDate:
    async def test_relapse_lands_on_the_chosen_day_and_moves_the_streak(
        self, client: AsyncClient
    ) -> None:
        category_id = await _create_avoid(client)

        response = await client.post(
            f"/api/v1/categories/{category_id}/relapses",
            json={"entry_date": _day(3)},
        )

        assert response.status_code == 201
        assert response.json()["entry_date"] == _day(3)
        assert response.json()["created"] is True
        streak = (await client.get(f"/api/v1/categories/{category_id}/streak")).json()
        assert streak["last_relapse_date"] == _day(3)
        assert streak["current_streak"] == 3

    async def test_two_past_relapses_keep_the_later_one_as_the_last(
        self, client: AsyncClient
    ) -> None:
        category_id = await _create_avoid(client)

        for days_ago in (7, 6):
            response = await client.post(
                f"/api/v1/categories/{category_id}/relapses",
                json={"entry_date": _day(days_ago)},
            )
            assert response.status_code == 201

        history = (
            await client.get(f"/api/v1/categories/{category_id}/relapses")
        ).json()
        assert history["relapse_dates"] == [_day(7), _day(6)]
        assert history["last_relapse_date"] == _day(6)
        assert history["current_streak"] == 6

    async def test_today_as_an_explicit_day_is_the_same_as_no_body(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id = await _create_avoid(client)

        first = await client.post(
            f"/api/v1/categories/{category_id}/relapses",
            json={"entry_date": today_local().isoformat()},
        )
        second = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        count = await db_session.execute(
            select(func.count())
            .select_from(Entry)
            .where(Entry.category_id == category_id)
        )
        assert count.scalar_one() == 1

    async def test_a_future_day_is_refused(self, client: AsyncClient) -> None:
        category_id = await _create_avoid(client)

        response = await client.post(
            f"/api/v1/categories/{category_id}/relapses",
            json={"entry_date": (today_local() + timedelta(days=1)).isoformat()},
        )

        assert response.status_code == 422
        streak = (await client.get(f"/api/v1/categories/{category_id}/streak")).json()
        assert streak["last_relapse_date"] is None

    async def test_the_repeat_window_is_per_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id = await _create_avoid(client)
        url = f"/api/v1/categories/{category_id}/relapses"

        thursday = await client.post(url, json={"entry_date": _day(5)})
        friday = await client.post(url, json={"entry_date": _day(4)})
        thursday_again = await client.post(url, json={"entry_date": _day(5)})

        assert (thursday.status_code, friday.status_code) == (201, 201)
        assert thursday.json()["id"] != friday.json()["id"]
        assert thursday_again.status_code == 200
        assert thursday_again.json()["id"] == thursday.json()["id"]
        assert thursday_again.json()["created"] is False

    async def test_a_replayed_key_returns_the_first_relapse(
        self, client: AsyncClient
    ) -> None:
        category_id = await _create_avoid(client)
        url = f"/api/v1/categories/{category_id}/relapses"
        headers = {"Idempotency-Key": "relapse-on-date-1"}

        first = await client.post(url, json={"entry_date": _day(2)}, headers=headers)
        replay = await client.post(url, json={"entry_date": _day(2)}, headers=headers)

        assert first.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]

    async def test_a_recorded_relapse_moves_to_another_day(
        self, client: AsyncClient
    ) -> None:
        category_id = await _create_avoid(client)
        recorded = await client.post(f"/api/v1/categories/{category_id}/relapses")
        entry_id = recorded.json()["id"]

        moved = await client.patch(
            f"/api/v1/entries/{entry_id}", json={"entry_date": _day(4)}
        )

        assert moved.status_code == 200
        streak = (await client.get(f"/api/v1/categories/{category_id}/streak")).json()
        assert streak["last_relapse_date"] == _day(4)
        assert streak["current_streak"] == 4
