# [review:need-review] PHASE-03/246
# summary: tests for the supplement directory and the intake mark — add/list/edit/archive/restore, one mark per supplement per logical day, Idempotency-Key replay, the 04:00 boundary, the client-clock check, and no supplement name in any log line
"""
Supplements: what the person takes, and the tick «принял».

The sentences the file is about. A mark belongs to the *logical* day the server
reads off its own clock, so a tap at 03:30 counts for yesterday. Marking is
idempotent twice over: the same `Idempotency-Key` returns the original row, and a
second tap on the same supplement in the same day creates nothing. A supplement
name is health data and never reaches a log line.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.crud import supplement as supplement_crud
from app.models.supplement import SupplementIntake, SupplementIntakeKey
from tests.conftest import test_engine

URL = "/api/v1/supplements"

# Tuesday 27 October 2026, 11:00 in Berlin (CET, +01:00) — logical day 27 October.
NOON = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 27)
# 03:30 in Berlin: still the night of 26 October.
NIGHT = datetime(2026, 10, 27, 2, 30, tzinfo=timezone.utc)
# 04:00 in Berlin: the new day starts.
DAWN = datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)
# 03:50 and 04:10 in Berlin: a tap and its retry on either side of the boundary.
BEFORE_DAWN = datetime(2026, 10, 27, 2, 50, tzinfo=timezone.utc)
AFTER_DAWN = datetime(2026, 10, 27, 3, 10, tzinfo=timezone.utc)
TOMORROW = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
KEY_MAX_LENGTH = 255

NAME = "Магний цитрат"

# The list reads the supplements and then the marks of the day: two statements.
LIST_STATEMENTS = 2


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daytime, "now_utc", lambda: NOON)


def pin(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(daytime, "now_utc", lambda: moment)


async def add(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": NAME,
        "dose": 200,
        "unit": "мг",
        "intake_time": "21:30:00",
    } | overrides
    response = await client.post(URL, json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def mark(
    client: AsyncClient,
    supplement_id: int,
    *,
    key: str | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"{URL}/{supplement_id}/intakes", json=body or {}, headers=headers
    )


async def intake_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(SupplementIntake))
    return int(result.scalar_one())


# --- the directory --------------------------------------------------------------


async def test_a_supplement_is_added_and_read_back(client: AsyncClient) -> None:
    created = await add(client)

    assert created["name"] == NAME
    assert (created["dose"], created["unit"]) == (200, "мг")
    assert created["intake_time"] == "21:30:00"
    assert created["is_active"] is True
    assert created["archived_at"] is None

    listed = (await client.get(URL)).json()
    assert [item["id"] for item in listed] == [created["id"]]
    assert listed[0]["taken_today"] is False


async def test_the_intake_time_is_optional(client: AsyncClient) -> None:
    created = await add(client, intake_time=None)

    assert created["intake_time"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "   "},
        {"name": "x" * 101},
        {"dose": 0},
        {"dose": -5},
        {"unit": ""},
        {"unit": "u" * 21},
    ],
)
async def test_a_malformed_supplement_is_422(
    client: AsyncClient, overrides: dict[str, Any]
) -> None:
    payload = {"name": NAME, "dose": 1, "unit": "мг"} | overrides

    assert (await client.post(URL, json=payload)).status_code == 422


async def test_a_supplement_is_edited_field_by_field(client: AsyncClient) -> None:
    created = await add(client)

    response = await client.patch(
        f"{URL}/{created['id']}", json={"dose": 400, "intake_time": None}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["dose"], body["intake_time"]) == (NAME, 400, None)


async def test_a_required_field_cannot_be_nulled(client: AsyncClient) -> None:
    created = await add(client)

    response = await client.patch(f"{URL}/{created['id']}", json={"name": None})

    assert response.status_code == 422


async def test_an_unknown_supplement_is_404_everywhere(client: AsyncClient) -> None:
    assert (await client.patch(f"{URL}/999", json={"dose": 1})).status_code == 404
    assert (await client.post(f"{URL}/999/archive")).status_code == 404
    assert (await client.post(f"{URL}/999/restore")).status_code == 404
    assert (await mark(client, 999)).status_code == 404


async def test_an_archived_supplement_leaves_the_list_and_comes_back(
    client: AsyncClient,
) -> None:
    created = await add(client)

    archived = await client.post(f"{URL}/{created['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert archived.json()["archived_at"] is not None
    assert (await client.get(URL)).json() == []
    with_archived = (await client.get(URL, params={"include_archived": True})).json()
    assert [item["id"] for item in with_archived] == [created["id"]]

    restored = await client.post(f"{URL}/{created['id']}/restore")
    assert restored.json()["is_active"] is True
    assert restored.json()["archived_at"] is None
    assert len((await client.get(URL)).json()) == 1


async def test_an_archived_supplement_cannot_be_marked(client: AsyncClient) -> None:
    created = await add(client)
    await client.post(f"{URL}/{created['id']}/archive")

    assert (await mark(client, created["id"])).status_code == 409


# --- the mark -------------------------------------------------------------------


async def test_a_mark_is_recorded_for_the_server_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    response = await mark(client, created["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["supplement_id"], body["intake_date"]) == (created["id"], "2026-10-27")
    assert await intake_count(db_session) == 1
    assert (await client.get(URL)).json()[0]["taken_today"] is True


async def test_a_replay_of_the_same_key_returns_the_original(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    first = await mark(client, created["id"], key="tap-1")
    second = await mark(client, created["id"], key="tap-1")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1


async def test_a_second_tap_in_the_same_day_creates_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    first = await mark(client, created["id"], key="tap-1")
    again = await mark(client, created["id"], key="tap-2")
    bare = await mark(client, created["id"])

    assert [again.status_code, bare.status_code] == [200, 200]
    assert again.json()["id"] == bare.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1


async def test_two_supplements_are_marked_independently(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    magnesium = await add(client)
    d3 = await add(client, name="D3", dose=2000, unit="МЕ")

    await mark(client, magnesium["id"])
    await mark(client, d3["id"])

    assert await intake_count(db_session) == 2


async def test_a_tap_at_half_past_three_belongs_to_yesterday(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, NIGHT)

    response = await mark(client, created["id"])

    assert response.json()["intake_date"] == "2026-10-26"


async def test_a_tap_at_four_belongs_to_the_new_day(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, DAWN)

    response = await mark(client, created["id"])

    assert response.json()["intake_date"] == "2026-10-27"


async def test_the_same_supplement_is_markable_again_the_next_day(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, NIGHT)
    await mark(client, created["id"])
    pin(monkeypatch, NOON)

    response = await mark(client, created["id"])

    assert response.status_code == 201
    assert await intake_count(db_session) == 2


async def test_taken_today_follows_the_logical_day(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, NIGHT)
    await mark(client, created["id"])

    # Same night: marked. After 04:00 the new day has no mark yet.
    assert (await client.get(URL)).json()[0]["taken_today"] is True
    pin(monkeypatch, DAWN)
    assert (await client.get(URL)).json()[0]["taken_today"] is False


async def test_the_list_costs_the_same_with_one_supplement_or_ten(
    client: AsyncClient,
) -> None:
    """The class of error: a query per supplement for `taken_today`."""

    async def statements_for_list() -> int:
        seen: list[str] = []

        def record(*args: Any) -> None:
            seen.append(str(args[2]))

        event.listen(test_engine.sync_engine, "before_cursor_execute", record)
        try:
            assert (await client.get(URL)).status_code == 200
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", record)
        return len(seen)

    first = await add(client)
    await mark(client, first["id"])
    small = await statements_for_list()

    for index in range(10):
        extra = await add(client, name=f"Добавка {index}")
        await mark(client, extra["id"])

    assert await statements_for_list() == small
    assert small <= LIST_STATEMENTS


async def test_a_client_that_names_another_day_is_409_not_a_silent_write(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    stale = await mark(client, created["id"], body={"intake_date": "2026-10-26"})
    right = await mark(client, created["id"], body={"intake_date": "2026-10-27"})

    assert stale.status_code == 409
    assert right.status_code == 201
    assert await intake_count(db_session) == 1


# --- idempotency keys -----------------------------------------------------------


async def test_a_retry_of_the_key_after_the_boundary_is_the_original_not_409(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    pin(monkeypatch, BEFORE_DAWN)
    first = await mark(
        client, created["id"], key="tap-1", body={"intake_date": "2026-10-26"}
    )
    pin(monkeypatch, AFTER_DAWN)

    # The client still says the 26th: its clock is the one of the first tap.
    retry = await mark(
        client, created["id"], key="tap-1", body={"intake_date": "2026-10-26"}
    )

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json() == first.json()
    assert await intake_count(db_session) == 1


async def test_a_retry_of_the_key_after_archiving_is_the_original_not_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)
    first = await mark(client, created["id"], key="tap-1")
    await client.post(f"{URL}/{created['id']}/archive")

    retry = await mark(client, created["id"], key="tap-1")

    assert retry.status_code == 200
    assert retry.json() == first.json()
    # A new key on the archived supplement is still refused.
    assert (await mark(client, created["id"], key="tap-2")).status_code == 409


async def test_a_key_of_another_supplement_is_409_and_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    magnesium = await add(client)
    zinc = await add(client, name="Цинк")
    await mark(client, magnesium["id"], key="tap-1")

    response = await mark(client, zinc["id"], key="tap-1")

    assert response.status_code == 409
    assert await intake_count(db_session) == 1


async def test_the_key_of_a_deduped_tap_still_means_the_days_mark_tomorrow(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    first = await mark(client, created["id"], key="tap-1")
    second = await mark(client, created["id"], key="tap-2")
    assert (first.status_code, second.status_code) == (201, 200)

    pin(monkeypatch, TOMORROW)
    retry_of_second = await mark(client, created["id"], key="tap-2")
    retry_of_first = await mark(client, created["id"], key="tap-1")

    assert retry_of_second.status_code == retry_of_first.status_code == 200
    assert (
        retry_of_second.json()["id"]
        == retry_of_first.json()["id"]
        == first.json()["id"]
    )
    assert await intake_count(db_session) == 1
    keys = (
        await db_session.execute(select(func.count()).select_from(SupplementIntakeKey))
    ).scalar_one()
    assert keys == 2


async def test_a_key_longer_than_the_column_is_422_not_500(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    ok = await mark(client, created["id"], key="k" * KEY_MAX_LENGTH)
    too_long = await mark(client, created["id"], key="k" * (KEY_MAX_LENGTH + 1))

    assert (ok.status_code, too_long.status_code) == (201, 422)
    assert await intake_count(db_session) == 1


def blind_once(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make the first call of a lookup miss, as if the twin had not committed yet."""
    real = getattr(supplement_crud, name)
    calls = 0

    async def lookup(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(supplement_crud, name, lookup)


async def key_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(SupplementIntakeKey))
    return int(result.scalar_one())


async def test_a_twin_that_wins_the_day_race_is_answered_with_its_mark(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    first = await mark(client, created["id"])
    blind_once(monkeypatch, "intake_on_day")

    response = await mark(client, created["id"], key="tap-2")

    assert response.status_code == 200
    assert response.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1
    assert await key_count(db_session) == 1

    pin(monkeypatch, TOMORROW)
    retry = await mark(client, created["id"], key="tap-2")
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1


async def test_the_key_of_a_loser_survives_a_twin_that_wrote_it_first(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alias write itself loses a race: the key is already there, answer with it."""
    created = await add(client)
    first = await mark(client, created["id"])
    blind_once(monkeypatch, "intake_on_day")
    real_alias = supplement_crud.alias_intake_key

    async def alias_then_collide(*args: Any, **kwargs: Any) -> None:
        await real_alias(*args, **kwargs)
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(supplement_crud, "alias_intake_key", alias_then_collide)

    response = await mark(client, created["id"], key="tap-2")

    assert response.status_code == 200
    assert response.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1
    assert await key_count(db_session) == 1


async def test_an_empty_idempotency_key_is_422_and_stores_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await add(client)

    response = await client.post(
        f"{URL}/{created['id']}/intakes", json={}, headers={"Idempotency-Key": ""}
    )

    assert response.status_code == 422
    assert await intake_count(db_session) == 0
    assert await key_count(db_session) == 0


async def test_a_twin_that_wins_the_key_race_is_answered_with_its_mark(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await add(client)
    first = await mark(client, created["id"], key="tap-1")
    blind_once(monkeypatch, "intake_by_idempotency_key")

    response = await mark(client, created["id"], key="tap-1")

    assert response.status_code == 200
    assert response.json()["id"] == first.json()["id"]
    assert await intake_count(db_session) == 1


# --- privacy --------------------------------------------------------------------


async def test_no_supplement_name_reaches_a_log_line(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret = "Секретная-добавка-42"

    created = await add(client, name=secret)
    await client.get(URL)
    await client.patch(f"{URL}/{created['id']}", json={"dose": 3})
    await mark(client, created["id"], key="tap-1")
    await mark(client, created["id"], key="tap-1")
    await client.post(f"{URL}/{created['id']}/archive")
    await mark(client, created["id"])

    assert secret not in caplog.text
