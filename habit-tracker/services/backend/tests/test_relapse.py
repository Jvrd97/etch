"""
Tests for the one-tap relapse of an avoid category and its relapse history.
"""

# [review:need-review] PHASE-01/207
# summary: POST /categories/{id}/relapses breaks the streak whatever fields the category has and says whether this tap wrote the entry, a repeated tap within a minute stays one relapse, an entry with no values (the old form's relapse) and a quick-mark relapse break the streak too, GET /categories/{id}/relapses returns the relapse days with the server's today, and the bulk streak read keeps a constant number of SQL statements

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.daytime import today_local
from app.models import Entry

# Every field set the ticket names: what one tap has to break, and the value the
# server is expected to write for it (None — the entry itself is the relapse).
FIELD_SETS: dict[str, tuple[list[dict[str, Any]], dict[str, str]]] = {
    "boolean": (
        [{"name": "Курил", "field_type": "boolean", "order": 0}],
        {"Курил": "true"},
    ),
    "boolean+text": (
        [
            {"name": "Что курил", "field_type": "text", "order": 0},
            {"name": "Курил", "field_type": "boolean", "order": 1},
        ],
        {"Курил": "true"},
    ),
    "two booleans": (
        [
            {"name": "Пиво", "field_type": "boolean", "order": 0},
            {"name": "Вино", "field_type": "boolean", "order": 1},
        ],
        {"Пиво": "true"},
    ),
    "number": (
        [{"name": "Сигареты", "field_type": "number", "order": 0}],
        {"Сигареты": "1"},
    ),
    "number+boolean": (
        [
            {"name": "Сигареты", "field_type": "number", "order": 0},
            {"name": "Курил", "field_type": "boolean", "order": 1},
        ],
        {"Курил": "true"},
    ),
    "text-only": (
        [{"name": "Что случилось", "field_type": "text", "order": 0}],
        {},
    ),
    "select-only": (
        [
            {
                "name": "Напиток",
                "field_type": "select",
                "options": "пиво,вино",
                "order": 0,
            }
        ],
        {},
    ),
    # No made-up «1 second»: the entry itself is the relapse, the time is a detail.
    "duration": (
        [{"name": "Соцсети", "field_type": "duration", "order": 0}],
        {},
    ),
    "no fields": ([], {}),
}


async def _create_avoid(
    client: AsyncClient, fields: list[dict[str, Any]], name: str = "Не курить"
) -> tuple[int, dict[str, int]]:
    response = await client.post(
        "/api/v1/categories",
        json={"name": name, "streak_mode": "avoid", "fields": fields},
    )
    assert response.status_code == 201
    data = response.json()
    return int(data["id"]), {f["name"]: int(f["id"]) for f in data["fields"]}


async def _add_entry(
    client: AsyncClient, category_id: int, day: str, values: dict[int, str]
) -> None:
    response = await client.post(
        "/api/v1/entries",
        json={
            "category_id": category_id,
            "entry_date": day,
            "values": [{"field_id": f, "value": v} for f, v in values.items()],
        },
    )
    assert response.status_code == 201


# What a category writes for a day that went clean: an unticked box, a zero.
CLEAN_VALUES: dict[str, str] = {"boolean": "", "number": "0", "duration": "0"}


def _clean_day(
    fields: list[dict[str, Any]], field_ids: dict[str, int]
) -> dict[int, str]:
    return {
        field_ids[f["name"]]: CLEAN_VALUES[f["field_type"]]
        for f in fields
        if f["field_type"] in CLEAN_VALUES
    }


async def _entry_count(db: AsyncSession, category_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(Entry).where(Entry.category_id == category_id)
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
class TestRecordRelapse:
    """One tap breaks the streak of any avoid category, whatever it is made of."""

    @pytest.mark.parametrize("field_set", list(FIELD_SETS))
    async def test_one_tap_breaks_the_streak(
        self, client: AsyncClient, field_set: str
    ) -> None:
        fields, expected = FIELD_SETS[field_set]
        category_id, field_ids = await _create_avoid(client, fields)
        clean = _clean_day(fields, field_ids)
        if clean:
            # A clean day a week ago, so the streak has something to lose.
            week_ago = (today_local() - timedelta(days=7)).isoformat()
            await _add_entry(client, category_id, week_ago, clean)
            before = await client.get(f"/api/v1/categories/{category_id}/streak")
            assert before.json()["current_streak"] == 8

        response = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 201
        entry = response.json()
        assert entry["created"] is True
        assert entry["category_id"] == category_id
        assert entry["entry_date"] == today_local().isoformat()
        written = {value["field_id"]: value["value"] for value in entry["values"]}
        assert written == {field_ids[name]: value for name, value in expected.items()}

        streak = await client.get(f"/api/v1/categories/{category_id}/streak")
        assert streak.status_code == 200
        assert streak.json()["current_streak"] == 0
        assert streak.json()["last_relapse_date"] == today_local().isoformat()

    async def test_the_primary_field_wins_over_field_order(
        self, client: AsyncClient
    ) -> None:
        category_id, field_ids = await _create_avoid(
            client, FIELD_SETS["two booleans"][0]
        )
        patched = await client.patch(
            f"/api/v1/categories/{category_id}",
            json={"primary_field_id": field_ids["Вино"]},
        )
        assert patched.status_code == 200

        response = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 201
        assert [(v["field_id"], v["value"]) for v in response.json()["values"]] == [
            (field_ids["Вино"], "true")
        ]

    async def test_a_second_tap_within_a_minute_is_the_same_relapse(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, _ = await _create_avoid(client, FIELD_SETS["number"][0])

        first = await client.post(f"/api/v1/categories/{category_id}/relapses")
        second = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        # The second tap wrote nothing: undoing it must not delete the first.
        assert second.json()["created"] is False
        assert await _entry_count(db_session, category_id) == 1

    async def test_a_tap_landing_on_a_quick_mark_relapse_does_not_own_it(
        self, client: AsyncClient
    ) -> None:
        """A Happened right after a quick-mark relapse is the same relapse, not this tap's."""
        category_id, field_ids = await _create_avoid(client, FIELD_SETS["number"][0])
        mark = await client.post(
            "/api/v1/quick-marks",
            json={
                "label": "Сигарета",
                "category_id": category_id,
                "field_id": field_ids["Сигареты"],
                "kind": "relapse",
            },
        )
        assert mark.status_code == 201
        tapped = await client.post(
            f"/api/v1/quick-marks/{mark.json()['id']}/events", json={}
        )
        assert tapped.status_code == 201

        response = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 200
        assert response.json()["id"] == tapped.json()["entry_id"]
        assert response.json()["created"] is False

    async def test_a_replayed_key_returns_the_original_relapse(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, _ = await _create_avoid(client, FIELD_SETS["boolean"][0])
        headers = {"Idempotency-Key": "tap-replayed"}

        first = await client.post(
            f"/api/v1/categories/{category_id}/relapses", headers=headers
        )
        await db_session.execute(
            update(Entry)
            .where(Entry.id == first.json()["id"])
            .values(created_at=func.now() - timedelta(minutes=10))
        )
        await db_session.commit()
        replay = await client.post(
            f"/api/v1/categories/{category_id}/relapses", headers=headers
        )

        assert first.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]
        # The same request again: the entry is still this tap's to undo.
        assert replay.json()["created"] is True
        assert await _entry_count(db_session, category_id) == 1

    async def test_a_relapse_after_the_window_is_a_new_one(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, _ = await _create_avoid(client, FIELD_SETS["boolean"][0])
        first = await client.post(f"/api/v1/categories/{category_id}/relapses")
        await db_session.execute(
            update(Entry)
            .where(Entry.id == first.json()["id"])
            .values(created_at=func.now() - timedelta(minutes=2))
        )
        await db_session.commit()

        second = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert second.status_code == 201
        assert second.json()["id"] != first.json()["id"]
        assert await _entry_count(db_session, category_id) == 2

    async def test_a_clean_entry_a_moment_ago_does_not_swallow_the_tap(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Only a relapse within the window counts as the same tap, not any entry."""
        category_id, field_ids = await _create_avoid(client, FIELD_SETS["number"][0])
        await _add_entry(
            client, category_id, today_local().isoformat(), {field_ids["Сигареты"]: "0"}
        )

        response = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 201
        assert await _entry_count(db_session, category_id) == 2

    async def test_a_past_relapse_written_a_moment_ago_does_not_swallow_the_tap(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The window is for today's taps; a record of last week is another fact."""
        category_id, _ = await _create_avoid(client, FIELD_SETS["text-only"][0])
        week_ago = (today_local() - timedelta(days=7)).isoformat()
        await _add_entry(client, category_id, week_ago, {})

        response = await client.post(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 201
        assert await _entry_count(db_session, category_id) == 2

    async def test_a_build_category_has_no_relapse(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/categories", json={"name": "Вода", "streak_mode": "build"}
        )

        response = await client.post(
            f"/api/v1/categories/{created.json()['id']}/relapses"
        )

        assert response.status_code == 409

    async def test_an_unknown_category_is_404(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/categories/9999/relapses")

        assert response.status_code == 404


@pytest.mark.asyncio
class TestRelapseRuleOverEntries:
    """The rule reads what an entry holds, so every writer is judged the same way."""

    async def test_any_entry_of_a_category_that_cannot_say_no_is_a_relapse(
        self, client: AsyncClient
    ) -> None:
        category_id, field_ids = await _create_avoid(client, FIELD_SETS["text-only"][0])
        today = today_local().isoformat()
        await _add_entry(
            client, category_id, today, {field_ids["Что случилось"]: "пиво"}
        )

        streak = await client.get(f"/api/v1/categories/{category_id}/streak")

        assert streak.json()["current_streak"] == 0

    async def test_an_entry_without_values_is_a_relapse_even_if_the_category_can_say_no(
        self, client: AsyncClient
    ) -> None:
        """
        The old Today form sent `values: []` for «Случилось»: that was a relapse.

        Every other writer sends a value per field (the entry form sends '' for
        an untouched one), so an entry with no values at all says nothing but
        «это случилось».
        """
        category_id, field_ids = await _create_avoid(
            client, FIELD_SETS["boolean+text"][0]
        )
        today = today_local()
        await _add_entry(
            client,
            category_id,
            (today - timedelta(days=10)).isoformat(),
            {field_ids["Курил"]: ""},
        )
        legacy_day = (today - timedelta(days=3)).isoformat()
        await _add_entry(client, category_id, legacy_day, {})

        history = await client.get(f"/api/v1/categories/{category_id}/relapses")

        assert history.json()["relapse_dates"] == [legacy_day]
        assert history.json()["current_streak"] == 3

    @pytest.mark.parametrize(
        ("fields", "field_name"),
        [
            (FIELD_SETS["boolean"][0], "Курил"),
            (FIELD_SETS["number"][0], "Сигареты"),
            (FIELD_SETS["duration"][0], "Соцсети"),
            (FIELD_SETS["text-only"][0], "Что случилось"),
        ],
    )
    async def test_a_quick_mark_relapse_breaks_the_streak(
        self, client: AsyncClient, fields: list[dict[str, Any]], field_name: str
    ) -> None:
        category_id, field_ids = await _create_avoid(client, fields)
        clean = _clean_day(fields, field_ids)
        if clean:
            week_ago = (today_local() - timedelta(days=7)).isoformat()
            await _add_entry(client, category_id, week_ago, clean)
        mark = await client.post(
            "/api/v1/quick-marks",
            json={
                "label": "Сорвался",
                "category_id": category_id,
                "field_id": field_ids[field_name],
                "kind": "relapse",
            },
        )
        assert mark.status_code == 201, mark.text

        tapped = await client.post(
            f"/api/v1/quick-marks/{mark.json()['id']}/events", json={}
        )

        assert tapped.status_code == 201
        streak = await client.get(f"/api/v1/categories/{category_id}/streak")
        assert streak.json()["current_streak"] == 0

    async def test_an_unticked_box_still_says_no(self, client: AsyncClient) -> None:
        """The entry form sends '' for an unticked box: that is a clean day, as before."""
        category_id, field_ids = await _create_avoid(
            client, FIELD_SETS["boolean+text"][0]
        )
        three_days_ago = (today_local() - timedelta(days=3)).isoformat()
        await _add_entry(
            client,
            category_id,
            three_days_ago,
            {field_ids["Курил"]: "", field_ids["Что курил"]: "держусь"},
        )

        streak = await client.get(f"/api/v1/categories/{category_id}/streak")

        assert streak.json()["current_streak"] == 4
        assert streak.json()["last_relapse_date"] is None

    async def test_positive_duration_is_a_relapse_and_zero_is_not(
        self, client: AsyncClient
    ) -> None:
        category_id, field_ids = await _create_avoid(client, FIELD_SETS["duration"][0])
        today = today_local()
        await _add_entry(
            client,
            category_id,
            (today - timedelta(days=5)).isoformat(),
            {field_ids["Соцсети"]: "0"},
        )
        await _add_entry(
            client,
            category_id,
            (today - timedelta(days=2)).isoformat(),
            {field_ids["Соцсети"]: "1800"},
        )

        streak = await client.get(f"/api/v1/categories/{category_id}/streak")

        assert streak.json()["current_streak"] == 2
        assert streak.json()["best_streak"] == 3


@pytest.mark.asyncio
class TestRelapseHistory:
    """GET /categories/{id}/relapses — the days the streak broke on."""

    async def test_lists_relapse_days_in_order_with_the_streak(
        self, client: AsyncClient
    ) -> None:
        category_id, field_ids = await _create_avoid(
            client, FIELD_SETS["number+boolean"][0]
        )
        today = today_local()
        days = {n: (today - timedelta(days=n)).isoformat() for n in (1, 4, 9, 12)}
        await _add_entry(client, category_id, days[12], {field_ids["Сигареты"]: "0"})
        await _add_entry(client, category_id, days[4], {field_ids["Курил"]: "true"})
        await _add_entry(client, category_id, days[9], {field_ids["Сигареты"]: "3"})
        # Two relapses on one day are one relapse day.
        await _add_entry(client, category_id, days[1], {field_ids["Сигареты"]: "1"})
        await _add_entry(client, category_id, days[1], {field_ids["Сигареты"]: "2"})

        response = await client.get(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 200
        data = response.json()
        assert data["relapse_dates"] == [days[9], days[4], days[1]]
        assert data["tracked_since"] == days[12]
        # The page counts its windows from the server's day, not the browser's
        # midnight: the day rule may end the day at 04:00.
        assert data["today"] == today.isoformat()
        streak = await client.get(f"/api/v1/categories/{category_id}/streak")
        for key, value in streak.json().items():
            assert data[key] == value

    async def test_a_category_without_entries_has_no_history(
        self, client: AsyncClient
    ) -> None:
        category_id, _ = await _create_avoid(client, FIELD_SETS["boolean"][0])

        response = await client.get(f"/api/v1/categories/{category_id}/relapses")

        assert response.status_code == 200
        assert response.json()["relapse_dates"] == []
        assert response.json()["tracked_since"] is None

    async def test_an_unknown_category_is_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/categories/9999/relapses")

        assert response.status_code == 404


@contextmanager
def _count_statements(db: AsyncSession) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(
        _conn: Connection,
        _cursor: object,
        statement: str,
        *_args: object,
    ) -> None:
        statements.append(statement)

    assert isinstance(db.bind, AsyncEngine)
    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.mark.asyncio
class TestBulkStreakQueryCount:
    """The extra «can this category say no» answer must not cost a query per category."""

    async def _seed(self, client: AsyncClient, count: int, prefix: str) -> None:
        for n in range(count):
            fields = FIELD_SETS["text-only" if n % 2 else "boolean"][0]
            category_id, _ = await _create_avoid(client, fields, name=f"{prefix}{n}")
            await client.post(f"/api/v1/categories/{category_id}/relapses")

    async def test_statements_do_not_grow_with_categories(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await self._seed(client, 2, "a")
        with _count_statements(db_session) as few:
            response = await client.get("/api/v1/streaks?streak_mode=avoid")
        assert response.status_code == 200
        assert len(response.json()) == 2

        await self._seed(client, 6, "b")
        with _count_statements(db_session) as many:
            response = await client.get("/api/v1/streaks?streak_mode=avoid")
        assert len(response.json()) == 8

        assert len(many) == len(few)
