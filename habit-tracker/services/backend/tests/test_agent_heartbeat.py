# [review:need-review] PHASE-03/164
# summary: tests of the agent heartbeat — a repeat of the same agent_id is one row, a second mac is a second row, silence is counted from the server's clock against one threshold, last_error is accepted only from a closed vocabulary (a path, a free sentence or anything over 200 characters is a 422 and writes nothing), an offline hour is visible afterwards, and the status read costs the same number of queries for one agent and for six
"""
Tests of `POST /agent/heartbeat` and `GET /agent/status`.

The heartbeat exists for the questions the database can no longer answer once the
queue lives on the mac: is the agent alive, may it read window titles, how far
behind is it. Each case here is a way for the answer to be quietly wrong — a
second row for the same machine, a silence measured by the agent's own clock, an
error field that carries a file path to a server nobody trusts with paths.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import agent as agent_api
from app.models.activity import AgentHeartbeat
from app.schemas.agent_heartbeat import (
    LAST_ERROR_MAX_LENGTH,
    AgentErrorCode,
)
from tests.conftest import test_engine

HEARTBEAT_URL = "/api/v1/agent/heartbeat"
STATUS_URL = "/api/v1/agent/status"

AGENT = "6f1b2c3d-0000-4000-8000-00000000a001"
SECOND_AGENT = "6f1b2c3d-0000-4000-8000-00000000a002"

NOON = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
SILENCE_MINUTES = 30
MANY_AGENTS = 6


def beat(agent_id: str = AGENT, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_version": "0.3.0",
        "accessibility_granted": True,
        "titles_enabled": True,
        "sampling_seconds": 5,
        "queue_depth": 0,
        "last_flush_at": NOON.isoformat(),
        "last_error": None,
    }
    body.update(overrides)
    return body


def at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """Make the server's clock read `moment` for the heartbeat and the status."""
    monkeypatch.setattr(agent_api, "now_utc", lambda: moment)


async def send(client: AsyncClient, body: dict[str, Any]) -> None:
    response = await client.post(HEARTBEAT_URL, json=body)
    assert response.status_code == 204, response.text


async def status(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(STATUS_URL)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def stored(db: AsyncSession) -> int:
    count = await db.scalar(select(func.count()).select_from(AgentHeartbeat))
    return int(count or 0)


@contextmanager
def counted_statements() -> Iterator[list[str]]:
    """Every SQL statement the engine sends while the block runs."""
    seen: list[str] = []

    def count(  # noqa: PLR0913 - the signature of the SQLAlchemy event
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        seen.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        yield seen
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)


class TestUpsert:
    async def test_the_first_heartbeat_makes_the_agent_known(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        assert (await status(client))["agents"] == []

        await send(client, beat(queue_depth=4, titles_enabled=False))

        agents = (await status(client))["agents"]
        assert len(agents) == 1
        agent = agents[0]
        assert agent["agent_id"] == AGENT
        assert agent["agent_version"] == "0.3.0"
        assert agent["queue_depth"] == 4
        assert agent["titles_enabled"] is False
        assert agent["accessibility_granted"] is True
        assert agent["sampling_seconds"] == 5
        assert agent["last_error"] is None
        assert agent["is_silent"] is False

    async def test_the_same_agent_twice_is_one_row_holding_the_last_word(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat(accessibility_granted=True, queue_depth=9))
        at(monkeypatch, NOON + timedelta(minutes=1))
        await send(client, beat(accessibility_granted=False, queue_depth=0))

        assert await stored(db_session) == 1
        (agent,) = (await status(client))["agents"]
        assert agent["accessibility_granted"] is False
        assert agent["queue_depth"] == 0

    async def test_a_second_mac_is_a_second_row_and_both_are_shown(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat(AGENT))
        await send(client, beat(SECOND_AGENT, agent_version="0.3.1"))

        agents = (await status(client))["agents"]
        assert {agent["agent_id"] for agent in agents} == {AGENT, SECOND_AGENT}

    async def test_an_offline_hour_is_visible_once_the_network_is_back(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat(queue_depth=60, last_flush_at=NOON.isoformat()))
        back = NOON + timedelta(hours=1)
        at(monkeypatch, back)
        await send(client, beat(queue_depth=0, last_flush_at=back.isoformat()))

        (agent,) = (await status(client))["agents"]
        assert agent["queue_depth"] == 0
        # `fromisoformat` of Python 3.10 does not read a trailing «Z».
        assert (
            datetime.fromisoformat(agent["last_flush_at"].replace("Z", "+00:00"))
            == back
        )

    async def test_a_heartbeat_with_no_flush_yet_is_accepted(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat(last_flush_at=None))

        (agent,) = (await status(client))["agents"]
        assert agent["last_flush_at"] is None


class TestSilence:
    """Silence is the server's clock against the moment the server heard the agent."""

    async def test_an_agent_heard_a_minute_ago_is_alive(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat())
        at(monkeypatch, NOON + timedelta(minutes=1))

        (agent,) = (await status(client))["agents"]
        assert agent["is_silent"] is False
        assert agent["silent_for_seconds"] == 60

    async def test_the_threshold_itself_is_still_alive_and_a_second_over_is_silent(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat())

        at(monkeypatch, NOON + timedelta(minutes=SILENCE_MINUTES))
        (on_the_line,) = (await status(client))["agents"]
        assert on_the_line["is_silent"] is False

        at(monkeypatch, NOON + timedelta(minutes=SILENCE_MINUTES, seconds=1))
        body = await status(client)
        assert body["agents"][0]["is_silent"] is True
        assert body["silence_threshold_seconds"] == SILENCE_MINUTES * 60

    async def test_three_hours_of_silence_are_reported_in_seconds(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat())
        at(monkeypatch, NOON + timedelta(hours=3))

        (agent,) = (await status(client))["agents"]
        assert agent["is_silent"] is True
        assert agent["silent_for_seconds"] == 3 * 3600

    async def test_the_agents_own_clock_decides_nothing(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mac with a wrong date cannot make itself look alive or dead."""
        at(monkeypatch, NOON)
        await send(client, beat(last_flush_at=(NOON - timedelta(days=30)).isoformat()))

        (agent,) = (await status(client))["agents"]
        assert agent["is_silent"] is False

    async def test_each_agent_is_judged_on_its_own(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat(AGENT))
        at(monkeypatch, NOON + timedelta(hours=2))
        await send(client, beat(SECOND_AGENT))

        agents = {a["agent_id"]: a for a in (await status(client))["agents"]}
        assert agents[AGENT]["is_silent"] is True
        assert agents[SECOND_AGENT]["is_silent"] is False


class TestLastError:
    """`last_error` is a code. A path must not get in even when somebody means it to."""

    @pytest.mark.parametrize("code", [code.value for code in AgentErrorCode])
    async def test_every_code_of_the_vocabulary_is_accepted(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, code: str
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat(last_error=code))

        (agent,) = (await status(client))["agents"]
        assert agent["last_error"] == code

    @pytest.mark.parametrize(
        "text",
        [
            "/Users/daniil/Documents/clients/patient-ivanov.docx",
            "NSCocoaErrorDomain 513: no permission for /Users/daniil/secret.txt",
            "Traceback (most recent call last):",
            "unknown_code",
            "NETWORK",
            "",
        ],
    )
    async def test_text_outside_the_vocabulary_is_refused_and_writes_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        text: str,
    ) -> None:
        at(monkeypatch, NOON)
        response = await client.post(HEARTBEAT_URL, json=beat(last_error=text))

        assert response.status_code == 422
        assert await stored(db_session) == 0

    async def test_more_than_200_characters_is_refused_whatever_it_says(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        at(monkeypatch, NOON)
        padded = AgentErrorCode.NETWORK.value + " " * LAST_ERROR_MAX_LENGTH
        for text in (padded, "x" * (LAST_ERROR_MAX_LENGTH + 1)):
            response = await client.post(HEARTBEAT_URL, json=beat(last_error=text))
            assert response.status_code == 422

        assert await stored(db_session) == 0

    async def test_every_code_fits_the_column(self) -> None:
        longest = max(len(code.value) for code in AgentErrorCode)
        assert longest <= LAST_ERROR_MAX_LENGTH

    async def test_a_field_the_schema_does_not_know_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            HEARTBEAT_URL, json=beat(last_error_message="/Users/daniil/x")
        )

        assert response.status_code == 422
        assert await stored(db_session) == 0


class TestShapeOfTheBody:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"agent_id": ""},
            {"agent_id": "a" * 65},
            {"agent_version": "1" * 21},
            {"queue_depth": -1},
            {"sampling_seconds": 0},
            {"accessibility_granted": None},
        ],
    )
    async def test_a_malformed_body_is_a_422(
        self, client: AsyncClient, overrides: dict[str, Any]
    ) -> None:
        response = await client.post(HEARTBEAT_URL, json=beat(**overrides))

        assert response.status_code == 422


class TestCost:
    """More agents do not mean more queries."""

    async def test_the_status_read_costs_the_same_for_one_agent_and_for_many(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        await send(client, beat("agent-0"))
        with counted_statements() as one:
            await status(client)

        for index in range(1, MANY_AGENTS):
            await send(client, beat(f"agent-{index}"))
        with counted_statements() as many:
            body = await status(client)

        assert len(body["agents"]) == MANY_AGENTS
        assert len(many) == len(one)

    async def test_a_repeat_heartbeat_costs_the_same_as_the_first(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at(monkeypatch, NOON)
        with counted_statements() as first:
            await send(client, beat())
        with counted_statements() as again:
            await send(client, beat())

        assert len(again) == len(first)
