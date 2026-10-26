# [review:need-review] PHASE-03/165
# summary: proves the Claude Code session aggregates upsert on session_uid (a session appended to later updates one row), the batch cap, that the schema has nowhere to put message text, the day listing, and that a stale resend never rolls a session back
"""Acceptance tests for `POST/GET /agent/claude-sessions`."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import today_local
from app.models.activity import ClaudeSession
from app.schemas.claude_session import MAX_CLAUDE_SESSIONS_BATCH

URL = "/api/v1/agent/claude-sessions"
ZONE = ZoneInfo(settings.APP_TIMEZONE)

# Columns that carry a number or an identifier. Anything else on the table would
# be a place for content, and the test below names every column on purpose: a new
# one has to be added here by someone who read why.
EXPECTED_COLUMNS = {
    "id",
    "session_uid",
    "cwd",
    "git_branch",
    "local_date",
    "started_at",
    "ended_at",
    "assistant_turns",
    "user_turns",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "models",
    "goal_title",
    "cli_version",
    "updated_at",
}


def session_payload(
    uid: str = "11111111-aaaa-bbbb-cccc-000000000001",
    *,
    turns: int = 3,
    ended_minutes: int = 30,
    cwd: str = "/Users/me/Projects/talvior",
    branch: str | None = "main",
    goal: str | None = None,
) -> dict[str, object]:
    day = today_local()
    start = datetime(day.year, day.month, day.day, 10, tzinfo=ZONE)
    return {
        "session_uid": uid,
        "cwd": cwd,
        "git_branch": branch,
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=ended_minutes)).isoformat(),
        "assistant_turns": turns,
        "user_turns": 1,
        "input_tokens": 100 * turns,
        "output_tokens": 50 * turns,
        "cache_read_tokens": 1000 * turns,
        "cache_creation_tokens": 10 * turns,
        "models": "claude-sonnet-5-5",
        "goal_title": goal,
        "cli_version": "2.1.309",
    }


async def stored(db: AsyncSession) -> list[ClaudeSession]:
    db.expire_all()
    return list((await db.execute(select(ClaudeSession))).scalars())


class TestClaudeSessionUpsert:
    async def test_a_session_appended_to_later_updates_the_same_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        first = await client.post(
            URL, json={"sessions": [session_payload(turns=3, ended_minutes=30)]}
        )
        later = await client.post(
            URL, json={"sessions": [session_payload(turns=8, ended_minutes=90)]}
        )

        assert first.status_code == later.status_code == 201
        rows = await stored(db_session)
        assert len(rows) == 1
        assert rows[0].assistant_turns == 8
        assert rows[0].output_tokens == 400
        assert rows[0].local_date == today_local()

    async def test_resending_the_same_batch_adds_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        batch = {"sessions": [session_payload("uid-a"), session_payload("uid-b")]}

        await client.post(URL, json=batch)
        await client.post(URL, json=batch)

        count = await db_session.scalar(select(func.count()).select_from(ClaudeSession))
        assert count == 2

    async def test_a_stale_resend_does_not_roll_the_session_back(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await client.post(
            URL, json={"sessions": [session_payload(turns=8, ended_minutes=90)]}
        )
        await client.post(
            URL, json={"sessions": [session_payload(turns=3, ended_minutes=30)]}
        )

        assert (await stored(db_session))[0].assistant_turns == 8

    async def test_the_goal_title_is_restated_with_the_session(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await client.post(URL, json={"sessions": [session_payload()]})
        await client.post(
            URL, json={"sessions": [session_payload(goal="Метрики Claude Code")]}
        )

        assert (await stored(db_session))[0].goal_title == "Метрики Claude Code"

    async def test_an_oversized_batch_is_refused_whole(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        batch = {
            "sessions": [
                session_payload(f"uid-{i}")
                for i in range(MAX_CLAUDE_SESSIONS_BATCH + 1)
            ]
        }

        response = await client.post(URL, json=batch)

        assert response.status_code == 422
        assert await stored(db_session) == []

    async def test_a_session_that_ends_before_it_starts_is_refused(
        self, client: AsyncClient
    ) -> None:
        payload = session_payload()
        payload["ended_at"] = "2000-01-01T00:00:00+00:00"

        response = await client.post(URL, json={"sessions": [payload]})

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("field", "too_big"),
        [
            ("assistant_turns", 2**31),
            ("user_turns", 2**31),
            ("input_tokens", 2**63),
            ("output_tokens", 2**63),
            ("cache_read_tokens", 2**63),
            ("cache_creation_tokens", 2**63),
        ],
    )
    async def test_a_counter_beyond_its_column_is_refused_not_a_500(
        self, client: AsyncClient, db_session: AsyncSession, field: str, too_big: int
    ) -> None:
        payload = {**session_payload(), field: too_big}

        response = await client.post(URL, json={"sessions": [payload]})

        assert response.status_code == 422
        assert await stored(db_session) == []

    async def test_counters_at_the_column_limits_are_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        payload = {
            **session_payload(),
            "assistant_turns": 2**31 - 1,
            "cache_read_tokens": 2**63 - 1,
        }

        response = await client.post(URL, json={"sessions": [payload]})

        assert response.status_code == 201
        assert (await stored(db_session))[0].cache_read_tokens == 2**63 - 1


class TestNoMessageText:
    async def test_a_field_for_content_is_refused_not_ignored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        payload = {**session_payload(), "text": "the transcript line"}

        response = await client.post(URL, json={"sessions": [payload]})

        assert response.status_code == 422
        assert await stored(db_session) == []

    def test_the_table_has_no_column_that_could_hold_content(self) -> None:
        columns = {column.name for column in ClaudeSession.__table__.columns}

        assert columns == EXPECTED_COLUMNS


class TestClaudeSessionList:
    async def test_the_day_lists_projects_branches_and_goal(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            URL,
            json={
                "sessions": [
                    session_payload("uid-a", cwd="/p/talvior", branch="main"),
                    session_payload(
                        "uid-b", cwd="/p/habit", branch="swarm/165", goal="Метрики"
                    ),
                ]
            },
        )

        day = today_local().isoformat()
        response = await client.get(URL, params={"date_from": day, "date_to": day})

        assert response.status_code == 200
        rows = {row["session_uid"]: row for row in response.json()["sessions"]}
        assert rows["uid-a"]["cwd"] == "/p/talvior"
        assert rows["uid-b"]["git_branch"] == "swarm/165"
        assert rows["uid-b"]["goal_title"] == "Метрики"
        assert rows["uid-b"]["output_tokens"] == 150

    async def test_another_day_is_not_listed(self, client: AsyncClient) -> None:
        await client.post(URL, json={"sessions": [session_payload()]})

        other = (today_local() - timedelta(days=3)).isoformat()
        response = await client.get(URL, params={"date_from": other, "date_to": other})

        assert response.json()["sessions"] == []

    async def test_a_backwards_range_is_refused(self, client: AsyncClient) -> None:
        day = today_local()
        response = await client.get(
            URL,
            params={
                "date_from": day.isoformat(),
                "date_to": (day - timedelta(days=1)).isoformat(),
            },
        )

        assert response.status_code == 422


USAGE_URL = "/api/v1/agent/claude-usage"


class TestClaudeUsageOfTheDay:
    """The day block reads totals; it never needs the list of sessions."""

    async def test_the_day_sums_sessions_turns_and_tokens(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            URL,
            json={
                "sessions": [
                    session_payload("uid-a", turns=3),
                    session_payload("uid-b", turns=5),
                ]
            },
        )

        day = today_local().isoformat()
        body = (await client.get(f"{USAGE_URL}/{day}")).json()

        assert body["date"] == day
        assert body["sessions"] == 2
        assert body["assistant_turns"] == 8
        assert body["input_tokens"] == 800
        assert body["output_tokens"] == 400
        assert body["cache_read_tokens"] == 8000
        assert body["cache_creation_tokens"] == 80

    async def test_the_answer_names_the_servers_today(
        self, client: AsyncClient
    ) -> None:
        other = (today_local() - timedelta(days=3)).isoformat()

        body = (await client.get(f"{USAGE_URL}/{other}")).json()

        assert body["today"] == today_local().isoformat()
        assert body["sessions"] == 0
        assert body["assistant_turns"] == 0
        assert body["input_tokens"] == 0

    async def test_another_day_is_not_counted(self, client: AsyncClient) -> None:
        await client.post(URL, json={"sessions": [session_payload()]})

        other = (today_local() - timedelta(days=1)).isoformat()
        body = (await client.get(f"{USAGE_URL}/{other}")).json()

        assert body["sessions"] == 0

    async def test_a_session_across_the_boundary_stays_whole_on_its_start_day(
        self, client: AsyncClient
    ) -> None:
        # Ends 25 hours after 10:00 — on the next logical day under any boundary hour.
        await client.post(
            URL,
            json={
                "sessions": [
                    session_payload("uid-long", turns=4, ended_minutes=25 * 60),
                    session_payload("uid-short", turns=2),
                ]
            },
        )

        day = today_local().isoformat()
        body = (await client.get(f"{USAGE_URL}/{day}")).json()
        next_day = (today_local() + timedelta(days=1)).isoformat()
        after = (await client.get(f"{USAGE_URL}/{next_day}")).json()

        assert body["sessions"] == 2
        assert body["assistant_turns"] == 6
        assert body["sessions_past_boundary"] == 1
        assert after["sessions"] == 0

    async def test_the_answer_has_counters_and_no_text(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            URL, json={"sessions": [session_payload(cwd="/p/secret", goal="Секрет")]}
        )

        day = today_local().isoformat()
        response = await client.get(f"{USAGE_URL}/{day}")

        assert "/p/secret" not in response.text
        assert "Секрет" not in response.text

    async def test_the_answer_has_exactly_these_keys(self, client: AsyncClient) -> None:
        # A new field has to be added here by someone who asked what it can leak.
        day = today_local().isoformat()
        body = (await client.get(f"{USAGE_URL}/{day}")).json()

        assert set(body) == {
            "date",
            "today",
            "sessions",
            "assistant_turns",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "sessions_past_boundary",
        }

    async def test_a_malformed_day_is_refused(self, client: AsyncClient) -> None:
        response = await client.get(f"{USAGE_URL}/not-a-day")

        assert response.status_code == 422
