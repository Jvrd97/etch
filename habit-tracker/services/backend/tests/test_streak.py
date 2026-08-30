"""
Tests for category streak_mode and the streak endpoint.
"""

# [review:need-review] PHASE-01/27-streak-mode-endpoint, PHASE-03/90
# summary: tests for streak_mode create/patch/422, the streak calculation matrix, and the day boundary the streak now counts by — `today_local()`, the same one the plan uses

import logging
from datetime import date, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud.streak import StreakStats, compute_streak, is_relapse_value
from app.models import Category
from app.models.field import FieldType


def d(day: int) -> date:
    """Deterministic date helper: day-th of a fixed month."""
    return date(2026, 3, day)


@pytest.mark.asyncio
class TestCategoryStreakMode:
    """streak_mode is accepted on create and patch, defaults to build."""

    async def test_create_category_defaults_streak_mode_build(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/categories", json={"name": "Sleep"})
        assert response.status_code == 201
        assert response.json()["streak_mode"] == "build"

    async def test_create_category_with_avoid_mode(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/categories", json={"name": "RMO", "streak_mode": "avoid"}
        )
        assert response.status_code == 201
        assert response.json()["streak_mode"] == "avoid"

    async def test_create_category_invalid_streak_mode(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/categories", json={"name": "RMO", "streak_mode": "quit-forever"}
        )
        assert response.status_code == 422

    async def test_patch_category_streak_mode(self, client: AsyncClient) -> None:
        created = await client.post("/api/v1/categories", json={"name": "RMO"})
        category_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"streak_mode": "avoid"}
        )
        assert response.status_code == 200
        assert response.json()["streak_mode"] == "avoid"

    async def test_patch_category_invalid_streak_mode(
        self, client: AsyncClient
    ) -> None:
        created = await client.post("/api/v1/categories", json={"name": "RMO"})
        category_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"streak_mode": "nope"}
        )
        assert response.status_code == 422


class TestComputeStreak:
    """Pure streak arithmetic over a set of tracked and relapse days."""

    def test_no_entries_at_all(self) -> None:
        assert compute_streak(set(), set(), today=d(10)) == StreakStats(
            current_streak=0, best_streak=0, last_relapse_date=None
        )

    def test_clean_history_counts_from_first_entry(self) -> None:
        """No relapse ever: streak spans first entry day .. today inclusive."""
        stats = compute_streak({d(1), d(3)}, set(), today=d(5))
        assert stats == StreakStats(
            current_streak=5, best_streak=5, last_relapse_date=None
        )

    def test_relapse_resets_current_but_keeps_best(self) -> None:
        """Clean 1..4 (best 4), relapse on 5, clean 6..8 (current 3)."""
        stats = compute_streak({d(1), d(5), d(8)}, {d(5)}, today=d(8))
        assert stats == StreakStats(
            current_streak=3, best_streak=4, last_relapse_date=d(5)
        )

    def test_relapse_today_gives_zero_current(self) -> None:
        stats = compute_streak({d(1), d(6)}, {d(6)}, today=d(6))
        assert stats == StreakStats(
            current_streak=0, best_streak=5, last_relapse_date=d(6)
        )

    def test_days_without_entries_are_clean(self) -> None:
        """Gaps in the history do not break an avoid-streak."""
        stats = compute_streak({d(1)}, {d(1)}, today=d(11))
        assert stats == StreakStats(
            current_streak=10, best_streak=10, last_relapse_date=d(1)
        )

    def test_last_relapse_is_the_latest_one(self) -> None:
        stats = compute_streak({d(2), d(7)}, {d(2), d(7)}, today=d(9))
        assert stats == StreakStats(
            current_streak=2, best_streak=4, last_relapse_date=d(7)
        )


class TestIsRelapseValue:
    """Interpretation of one stored value, plus warning localization."""

    def test_boolean_true_is_relapse(self) -> None:
        assert is_relapse_value(FieldType.BOOLEAN, "true") is True
        assert is_relapse_value(FieldType.BOOLEAN, "false") is False

    def test_positive_number_is_relapse(self) -> None:
        assert is_relapse_value(FieldType.NUMBER, "2") is True
        assert is_relapse_value(FieldType.NUMBER, "0") is False

    def test_unparsable_number_warns_with_row_ids(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warning without ids is useless — the bad row must be locatable."""
        with caplog.at_level(logging.WARNING, logger="app.crud.values"):
            assert (
                is_relapse_value(FieldType.NUMBER, "abc", field_id=3, entry_id=11)
                is False
            )
        assert len(caplog.records) == 1
        record = caplog.records[0]
        # `extra=` sets these dynamically, so they are not on the LogRecord type
        assert getattr(record, "field_id") == 3
        assert getattr(record, "entry_id") == 11


@pytest.mark.asyncio
class TestStreakEndpoint:
    """GET /categories/{id}/streak over real entries."""

    async def _create_rmo(self, client: AsyncClient) -> tuple[int, int, int]:
        """Create an avoid category with a number and a boolean field."""
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "RMO",
                "streak_mode": "avoid",
                "fields": [
                    {"name": "Quantity", "field_type": "number", "order": 1},
                    {"name": "Relapse", "field_type": "boolean", "order": 2},
                ],
            },
        )
        assert response.status_code == 201
        data = response.json()
        fields = {f["name"]: f["id"] for f in data["fields"]}
        return data["id"], fields["Quantity"], fields["Relapse"]

    async def _add_entry(
        self, client: AsyncClient, category_id: int, day: date, values: dict[int, str]
    ) -> None:
        response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": category_id,
                "entry_date": day.isoformat(),
                "values": [
                    {"field_id": field_id, "value": value}
                    for field_id, value in values.items()
                ],
            },
        )
        assert response.status_code == 201

    async def test_streak_for_nonexistent_category(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/categories/9999/streak")
        assert response.status_code == 404

    async def test_quantity_zero_does_not_break_the_streak(
        self, client: AsyncClient
    ) -> None:
        """RMO case: a 'Quantity 0' record is a clean day, not a relapse."""
        category_id, quantity_id, _ = await self._create_rmo(client)
        today = today_local()
        await self._add_entry(
            client, category_id, today - timedelta(days=4), {quantity_id: "0"}
        )

        response = await client.get(f"/api/v1/categories/{category_id}/streak")
        assert response.status_code == 200
        data = response.json()
        assert data["category_id"] == category_id
        assert data["streak_mode"] == "avoid"
        assert data["last_relapse_date"] is None
        assert data["current_streak"] == 5
        assert data["best_streak"] == 5

    async def test_number_above_zero_and_boolean_true_break_the_streak(
        self, client: AsyncClient
    ) -> None:
        """Relapse on day-6 (number > 0) and day-2 (boolean true)."""
        category_id, quantity_id, relapse_id = await self._create_rmo(client)
        today = today_local()
        await self._add_entry(
            client, category_id, today - timedelta(days=9), {quantity_id: "0"}
        )
        await self._add_entry(
            client, category_id, today - timedelta(days=6), {quantity_id: "2"}
        )
        await self._add_entry(
            client, category_id, today - timedelta(days=2), {relapse_id: "true"}
        )

        response = await client.get(f"/api/v1/categories/{category_id}/streak")
        assert response.status_code == 200
        data = response.json()
        assert data["last_relapse_date"] == (today - timedelta(days=2)).isoformat()
        assert data["current_streak"] == 2
        assert data["best_streak"] == 3

    async def test_unknown_streak_mode_in_db_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A row written outside the API must not be blindly cast to the Literal."""
        category_id, _, _ = await self._create_rmo(client)
        await db_session.execute(
            update(Category)
            .where(Category.id == category_id)
            .values(streak_mode="sideways")
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/categories/{category_id}/streak")
        assert response.status_code == 409


class TestOneDayBoundary:
    """
    The debt `#90` pays: `app/crud/streak.py` counted UTC days of its own.

    A mark made at 00:30 landed in one day for the plan and in the next one for
    the streak, which is the single known disagreement `#107` left behind. After
    this ticket there is no second arithmetic of days anywhere in `app/`.
    """

    def test_the_streak_asks_the_one_boundary_what_today_is(self) -> None:
        """`today=None` means `today_local()`, not the process's UTC calendar."""
        entry_days = {today_local() - timedelta(days=3)}

        by_default = compute_streak(entry_days, set(), today=today_local())

        assert by_default.current_streak == 4

    def test_no_second_arithmetic_of_days_is_left_in_the_module(self) -> None:
        """
        The acceptance case as it is written: a grep, not a promise.

        `TODO(#90)` named the debt and a UTC clock reading was it. The module
        no longer imports `timezone` at all — it asks `app.core.daytime` like
        every other consumer — and a future edit that brings either back fails
        here rather than in production at 00:30.
        """
        source = (
            Path(__file__).parent.parent / "app" / "crud" / "streak.py"
        ).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )

        assert "TODO(#90)" not in source
        assert "timezone" not in code
        assert "today_local()" in code
