# [review:need-review] PHASE-03/162
# summary: tests of the day mode as data — a Tuesday with no row is work + nocode from the seed, a manual row overrides exactly one date and nothing around it, deleting the row returns the day to the schedule, nocode flips independently of kind, editing the schedule moves the days with no decision and leaves the decided ones alone, a bad kind or a schedule that is not seven distinct weekdays is a 422 that writes nothing, the agent config carries the manual mode (and its ETag moves), and a mode read costs a fixed number of queries
"""
Tests of `GET|PUT|DELETE /day-mode/{date}` and `GET|PUT /mode-schedule`.

The mode used to live in `~/.claude/nocode/config` as `days=2,4` plus
`override=YYYY-MM-DD:on|off`. Each case here is a way for the data version to be
quietly worse than the file: an override that leaks to the next Tuesday, a
schedule edit that rewrites a day somebody decided by hand, `nocode` welded to
`kind` so that a working Tuesday cannot exist.
"""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import activity as activity_crud
from app.models.activity import DayMode, ModeSchedule
from tests.conftest import test_engine

DAY_MODE_URL = "/api/v1/day-mode"
SCHEDULE_URL = "/api/v1/mode-schedule"
CONFIG_URL = "/api/v1/agent/config"

# The seed of migration 155, weekday 0 = Sunday … 6 = Saturday.
SEED: dict[int, tuple[str, bool]] = {
    0: ("dayoff", False),
    1: ("work", False),
    2: ("work", True),
    3: ("work", False),
    4: ("dayoff", True),
    5: ("work", False),
    6: ("work", False),
}

TUESDAY = date(2026, 10, 27)
NEXT_TUESDAY = TUESDAY + timedelta(days=7)
WEDNESDAY = TUESDAY + timedelta(days=1)
MODE_READ_MAX_QUERIES = 2


@pytest.fixture(autouse=True)
async def seeded_schedule(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    for weekday, (kind, nocode) in SEED.items():
        db_session.add(ModeSchedule(weekday=weekday, kind=kind, nocode=nocode))
    await activity_crud.seed_settings(db_session)
    await db_session.commit()
    yield


async def read_mode(client: AsyncClient, on: date) -> dict[str, Any]:
    response = await client.get(f"{DAY_MODE_URL}/{on.isoformat()}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def put_mode(
    client: AsyncClient,
    on: date,
    kind: str,
    nocode: bool,
    note: str | None = None,
) -> Any:
    return await client.put(
        f"{DAY_MODE_URL}/{on.isoformat()}",
        json={"kind": kind, "nocode": nocode, "note": note},
    )


def schedule_payload(**overrides: tuple[str, bool]) -> dict[str, Any]:
    """The whole week as the PUT wants it; `d2="vacation", True` rewrites weekday 2."""
    week = dict(SEED)
    for key, value in overrides.items():
        week[int(key.removeprefix("d"))] = value
    return {
        "days": [
            {"weekday": weekday, "kind": kind, "nocode": nocode}
            for weekday, (kind, nocode) in week.items()
        ]
    }


async def test_tuesday_without_a_row_is_work_and_nocode_from_the_schedule(
    client: AsyncClient,
) -> None:
    body = await read_mode(client, TUESDAY)

    assert body == {
        "date": TUESDAY.isoformat(),
        "kind": "work",
        "nocode": True,
        "source": "schedule",
    }


async def test_manual_mode_overrides_exactly_one_day(client: AsyncClient) -> None:
    response = await put_mode(client, TUESDAY, "vacation", True, note="отпуск")

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "manual"
    assert (await read_mode(client, TUESDAY))["kind"] == "vacation"
    assert (await read_mode(client, TUESDAY))["source"] == "manual"
    next_tuesday = await read_mode(client, NEXT_TUESDAY)
    assert (next_tuesday["kind"], next_tuesday["source"]) == ("work", "schedule")
    wednesday = await read_mode(client, WEDNESDAY)
    assert (wednesday["kind"], wednesday["source"]) == ("work", "schedule")


async def test_manual_mode_is_stored_with_decision_time_and_note(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await put_mode(client, TUESDAY, "sick", False, note="температура")

    row = await db_session.get(DayMode, TUESDAY)
    assert row is not None
    assert (row.kind, row.nocode, row.source, row.note) == (
        "sick",
        False,
        "manual",
        "температура",
    )
    assert row.decided_at is not None


async def test_second_put_replaces_the_decision_instead_of_adding_a_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await put_mode(client, TUESDAY, "sick", False)
    await put_mode(client, TUESDAY, "dayoff", True)

    count = await db_session.scalar(select(func.count()).select_from(DayMode))
    assert count == 1
    assert (await read_mode(client, TUESDAY))["kind"] == "dayoff"


async def test_delete_returns_the_day_to_the_schedule(client: AsyncClient) -> None:
    await put_mode(client, TUESDAY, "vacation", False)

    response = await client.delete(f"{DAY_MODE_URL}/{TUESDAY.isoformat()}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "date": TUESDAY.isoformat(),
        "kind": "work",
        "nocode": True,
        "source": "schedule",
    }
    assert (await read_mode(client, TUESDAY))["source"] == "schedule"


async def test_delete_of_a_day_nobody_decided_is_not_an_error(
    client: AsyncClient,
) -> None:
    response = await client.delete(f"{DAY_MODE_URL}/{TUESDAY.isoformat()}")

    assert response.status_code == 200
    assert response.json()["source"] == "schedule"


async def test_nocode_flips_without_touching_kind(client: AsyncClient) -> None:
    await put_mode(client, TUESDAY, "work", False)

    body = await read_mode(client, TUESDAY)
    assert (body["kind"], body["nocode"]) == ("work", False)

    await put_mode(client, WEDNESDAY, "work", True)
    body = await read_mode(client, WEDNESDAY)
    assert (body["kind"], body["nocode"]) == ("work", True)


async def test_unknown_kind_is_422_and_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await put_mode(client, TUESDAY, "holiday", False)

    assert response.status_code == 422
    count = await db_session.scalar(select(func.count()).select_from(DayMode))
    assert count == 0


async def test_schedule_is_read_as_seven_weekdays(client: AsyncClient) -> None:
    response = await client.get(SCHEDULE_URL)

    assert response.status_code == 200
    days = response.json()["days"]
    assert [d["weekday"] for d in days] == list(range(7))
    assert {d["weekday"]: (d["kind"], d["nocode"]) for d in days} == SEED


async def test_schedule_edit_moves_future_days_and_spares_decided_ones(
    client: AsyncClient,
) -> None:
    await put_mode(client, TUESDAY, "sick", False)

    response = await client.put(
        SCHEDULE_URL, json=schedule_payload(d2=("dayoff", False))
    )

    assert response.status_code == 200, response.text
    decided = await read_mode(client, TUESDAY)
    assert (decided["kind"], decided["source"]) == ("sick", "manual")
    moved = await read_mode(client, NEXT_TUESDAY)
    assert (moved["kind"], moved["nocode"], moved["source"]) == (
        "dayoff",
        False,
        "schedule",
    )


@pytest.mark.parametrize(
    "days",
    [
        pytest.param(
            [{"weekday": w, "kind": "work", "nocode": False} for w in range(6)],
            id="six-weekdays",
        ),
        pytest.param(
            [{"weekday": 1, "kind": "work", "nocode": False}] * 7, id="duplicates"
        ),
        pytest.param(
            [{"weekday": w, "kind": "work", "nocode": False} for w in range(1, 8)],
            id="weekday-out-of-range",
        ),
        pytest.param(
            [{"weekday": w, "kind": "holiday", "nocode": False} for w in range(7)],
            id="unknown-kind",
        ),
    ],
)
async def test_bad_schedule_is_422_and_leaves_the_old_one(
    client: AsyncClient, db_session: AsyncSession, days: list[dict[str, Any]]
) -> None:
    response = await client.put(SCHEDULE_URL, json={"days": days})

    assert response.status_code == 422
    assert (await read_mode(client, TUESDAY))["kind"] == "work"
    rows = (await db_session.execute(select(ModeSchedule))).scalars().all()
    assert {r.weekday: (r.kind, r.nocode) for r in rows} == SEED


async def test_agent_config_carries_the_manual_mode_and_its_etag_moves(
    client: AsyncClient,
) -> None:
    before = await client.get(CONFIG_URL)
    today_mode = before.json()["day_mode"]
    today = date.fromisoformat(today_mode["date"])

    await put_mode(client, today, "vacation", not today_mode["nocode"])
    after = await client.get(CONFIG_URL)

    assert after.json()["day_mode"]["kind"] == "vacation"
    assert after.json()["day_mode"]["source"] == "manual"
    assert after.headers["ETag"] != before.headers["ETag"]


async def test_mode_read_costs_a_fixed_number_of_queries(client: AsyncClient) -> None:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        await read_mode(client, TUESDAY)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)

    assert len(statements) <= MODE_READ_MAX_QUERIES
