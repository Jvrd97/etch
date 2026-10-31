# [review:need-review] PHASE-03/259
# summary: tests for the press moment of a supplement mark (`occurred_at`: own logical day, 5 minutes ahead / 7 days back window, replay before the window) and for the idempotent create (`Idempotency-Key` on POST /supplements, race, statement count)
"""
Supplements, round 259: the moment of the press and a create that survives a retry.

A mark queued offline and delivered after 04:00 still belongs to the day on which
the person pressed, exactly as a quick mark does (`#236`). A create whose answer
was lost to a timeout is retried under the same key and must not make a second
supplement.
"""

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.crud import supplement as supplement_crud
from app.models.supplement import Supplement, SupplementIntake
from tests.conftest import test_engine
from tests.test_supplements import (
    AFTER_DAWN,
    KEY_MAX_LENGTH,
    NAME,
    NIGHT,
    NOON,
    URL,
    add,
    intake_count,
    mark,
    pin,
)

LAST_DAY = date(2026, 10, 26)
WINDOW_AHEAD = timedelta(minutes=5)
WINDOW_BACK = timedelta(days=7)
ONE_SECOND = timedelta(seconds=1)


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daytime, "now_utc", lambda: NOON)


async def mark_at(
    client: AsyncClient,
    supplement_id: int,
    occurred_at: datetime | str,
    *,
    key: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Any:
    moment = occurred_at if isinstance(occurred_at, str) else occurred_at.isoformat()
    return await mark(
        client, supplement_id, key=key, body={"occurred_at": moment} | (extra or {})
    )


def moment_of(body: dict[str, Any]) -> datetime:
    """`taken_at` of an answer; the wire spells UTC as `Z`."""
    return datetime.fromisoformat(body["taken_at"].replace("Z", "+00:00"))


async def supplement_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(Supplement))
    return int(result.scalar_one())


async def statements_of(call: Any) -> int:
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    try:
        await call()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record)
    return len(seen)


# --- the day of a mark follows the press -----------------------------------------


async def test_a_press_before_four_delivered_after_four_lands_on_its_own_day(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, AFTER_DAWN)

    response = await mark_at(client, created["id"], NIGHT)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["intake_date"] == LAST_DAY.isoformat()
    assert moment_of(body) == NIGHT
    # The new day has no mark yet: the list still asks for it.
    assert (await client.get(URL)).json()[0]["taken_today"] is False
    # And the new day can be marked on its own.
    assert (await mark(client, created["id"])).status_code == 201
    assert await intake_count(db_session) == 2


async def test_without_the_field_the_mark_is_the_moment_of_the_request(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, AFTER_DAWN)

    body = (await mark(client, created["id"])).json()

    assert body["intake_date"] == "2026-10-27"
    assert moment_of(body) == AFTER_DAWN


async def test_the_offset_of_the_moment_is_read_not_assumed_to_be_utc(
    client: AsyncClient,
) -> None:
    created = await add(client)

    # 03:30 at +01:00 is 02:30 UTC and 03:30 in Berlin: the 26th.
    response = await mark_at(client, created["id"], "2026-10-27T03:30:00+01:00")

    assert response.status_code == 201
    assert response.json()["intake_date"] == LAST_DAY.isoformat()


async def test_a_second_press_of_the_same_past_day_creates_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)
    first = await mark_at(client, created["id"], NIGHT)

    second = await mark_at(client, created["id"], NIGHT - timedelta(hours=1))

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1


async def test_the_clock_check_runs_against_the_day_of_the_press(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    right = await mark_at(
        client, created["id"], NIGHT, extra={"intake_date": LAST_DAY.isoformat()}
    )
    wrong = await mark_at(
        client, created["id"], NIGHT, extra={"intake_date": "2026-10-27"}
    )

    # The first answer is a 201; the same press again is judged by the day it names.
    assert right.status_code == 201
    assert wrong.status_code == 409
    assert await intake_count(db_session) == 1


# --- the window of the moment ----------------------------------------------------


@pytest.mark.parametrize(
    ("shift", "expected"),
    [
        (WINDOW_AHEAD, 201),
        (WINDOW_AHEAD + ONE_SECOND, 422),
        (-WINDOW_BACK, 201),
        (-WINDOW_BACK - ONE_SECOND, 422),
        (timedelta(0), 201),
    ],
)
async def test_the_window_is_five_minutes_ahead_and_seven_days_back(
    client: AsyncClient,
    db_session: AsyncSession,
    shift: timedelta,
    expected: int,
) -> None:
    created = await add(client)

    response = await mark_at(client, created["id"], NOON + shift)

    assert response.status_code == expected, response.text
    assert await intake_count(db_session) == (1 if expected == 201 else 0)


async def test_a_moment_without_an_offset_is_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    response = await mark_at(client, created["id"], "2026-10-27T03:30:00")

    assert response.status_code == 422
    assert await intake_count(db_session) == 0


async def test_the_refusal_names_the_field(client: AsyncClient) -> None:
    created = await add(client)

    response = await mark_at(client, created["id"], NOON + timedelta(days=1))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "occurred_at"]


# --- a retry is the original -----------------------------------------------------


async def test_a_retry_after_the_timeout_is_the_first_mark(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, AFTER_DAWN)
    first = await mark_at(client, created["id"], NIGHT, key="tap-1")

    retry = await mark_at(client, created["id"], NIGHT, key="tap-1")

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json() == first.json()
    assert await intake_count(db_session) == 1


async def test_a_retry_whose_moment_has_left_the_window_is_still_the_first_mark(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pressed = NOON - timedelta(days=6)
    first = await mark_at(client, created["id"], pressed, key="tap-1")
    pin(monkeypatch, NOON + timedelta(days=2))

    retry = await mark_at(client, created["id"], pressed, key="tap-1")
    fresh = await mark_at(client, created["id"], pressed, key="tap-2")

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json() == first.json()
    # A key never seen before is judged by the window as any other request.
    assert fresh.status_code == 422
    assert await intake_count(db_session) == 1


async def test_the_press_moment_costs_no_extra_statement(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The class of error: the window or the day costing a query of its own."""
    first = await add(client)
    second = await add(client, name="Цинк")

    plain = await statements_of(lambda: mark(client, first["id"], key="a"))
    timed = await statements_of(lambda: mark_at(client, second["id"], NIGHT, key="b"))

    assert timed == plain


# --- the create under a key ------------------------------------------------------


async def create(client: AsyncClient, *, key: str | None, **overrides: Any) -> Any:
    payload = {"name": NAME, "dose": 200, "unit": "мг"} | overrides
    headers = {"Idempotency-Key": key} if key is not None else {}
    return await client.post(URL, json=payload, headers=headers)


async def test_a_retried_create_returns_the_same_supplement(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await create(client, key="create-1")
    retry = await create(client, key="create-1")

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json() == first.json()
    assert await supplement_count(db_session) == 1


async def test_the_replay_is_the_first_supplement_even_when_the_body_changed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await create(client, key="create-1")

    retry = await create(client, key="create-1", name="Цинк", dose=15)

    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert await supplement_count(db_session) == 1


async def test_the_replay_of_an_archived_supplement_does_not_revive_it(
    client: AsyncClient,
) -> None:
    first = (await create(client, key="create-1")).json()
    await client.post(f"{URL}/{first['id']}/archive")

    retry = await create(client, key="create-1")

    assert retry.status_code == 200
    assert retry.json()["id"] == first["id"]
    assert retry.json()["is_active"] is False


async def test_different_keys_and_no_key_make_separate_supplements(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create(client, key="create-1")
    await create(client, key="create-2")
    await create(client, key=None)
    await create(client, key=None)

    assert await supplement_count(db_session) == 4


@pytest.mark.parametrize("key", ["", "k" * (KEY_MAX_LENGTH + 1)])
async def test_a_bad_create_key_is_422_and_writes_nothing(
    client: AsyncClient, db_session: AsyncSession, key: str
) -> None:
    response = await create(client, key=key)

    assert response.status_code == 422
    assert await supplement_count(db_session) == 0


async def test_a_create_key_of_the_longest_length_is_accepted(
    client: AsyncClient,
) -> None:
    assert (await create(client, key="k" * KEY_MAX_LENGTH)).status_code == 201


async def test_a_twin_that_wins_the_create_race_is_answered_with_its_supplement(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await create(client, key="create-1")
    real = supplement_crud.supplement_by_idempotency_key
    calls = 0

    async def blind_first(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(supplement_crud, "supplement_by_idempotency_key", blind_first)

    retry = await create(client, key="create-1")

    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert await supplement_count(db_session) == 1


async def test_a_replay_costs_the_same_with_one_supplement_or_ten(
    client: AsyncClient,
) -> None:
    """The class of error: the lookup by key scanning or loading the whole directory."""
    await create(client, key="create-1")
    small = await statements_of(lambda: create(client, key="create-1"))

    for index in range(10):
        await create(client, key=f"other-{index}", name=f"Добавка {index}")

    assert await statements_of(lambda: create(client, key="create-1")) == small
    assert small == 1


async def test_a_replayed_create_does_not_touch_the_intakes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = (await create(client, key="create-1")).json()
    await mark(client, first["id"])

    await create(client, key="create-1")

    rows = (await db_session.execute(select(SupplementIntake))).scalars().all()
    assert len(rows) == 1
