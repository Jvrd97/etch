# [review:need-review] 312
# summary: the class of error «parallel presses of one button lose each other» — N presses (2, 4, 10) sent at once, each through its own session and transaction on the real Postgres, add N steps; the same key adds one; a tick, a relapse and `PUT /entries/checklist` leave one day row (a relapse — one per press); an undo racing presses takes back only its own step
"""
Presses of one button that arrive at the same time.

The client queues a press and shows it at once, so nothing stops two presses of
`+250` from reaching the server together — the iOS outbox and the agent window
send them in parallel. Each request here runs in its own session, as `get_db`
gives it in production, and the requests are started together with
`asyncio.gather`: their statements interleave on separate Postgres connections,
which is the race. Sequential calls on one session would pass with the bug in
place.

What is asserted is the sum and the number of day rows, read back through a
fresh session after every request has committed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.core.database import get_db
from app.crud import entry as entry_crud
from app.main import app
from app.models import Entry, EntryValue
from app.models.quick_mark import QuickMarkEvent
from tests.conftest import TestSessionLocal

QUICK_MARKS_URL = "/api/v1/quick-marks"
CHECKLIST_URL = "/api/v1/entries/checklist"

STEP = 250
PARALLEL = [2, 4, 10]


@asynccontextmanager
async def session_per_request() -> AsyncIterator[None]:
    """Give every request its own session and transaction, as production `get_db` does."""

    async def own_session() -> AsyncGenerator[AsyncSession, None]:
        async with TestSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = own_session
    try:
        yield
    finally:
        if previous is None:
            del app.dependency_overrides[get_db]
        else:
            app.dependency_overrides[get_db] = previous


async def make_mark(
    client: AsyncClient, category: dict[str, Any], **overrides: Any
) -> int:
    payload: dict[str, Any] = {
        "label": "+250 мл",
        "category_id": category["id"],
        "field_id": category["fields"][0]["id"],
        "kind": "increment",
        "step": STEP,
    }
    payload.update(overrides)
    response = await client.post(QUICK_MARKS_URL, json=payload)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def press(client: AsyncClient, mark_id: int, key: str) -> Response:
    return await client.post(
        f"{QUICK_MARKS_URL}/{mark_id}/events",
        json={},
        headers={"Idempotency-Key": key},
    )


async def press_at_once(
    client: AsyncClient, db_session: AsyncSession, mark_id: int, keys: list[str]
) -> list[Response]:
    """Commit the setup, then send one press per key, all of them together."""
    await db_session.commit()
    async with session_per_request():
        return list(await asyncio.gather(*(press(client, mark_id, k) for k in keys)))


async def day_rows(category_id: int, on: date) -> list[list[str | None]]:
    """The values of every entry of the category on that day, one list per entry."""
    async with TestSessionLocal() as check:
        entries = (
            await check.execute(
                select(Entry.id)
                .where(Entry.category_id == category_id, Entry.entry_date == on)
                .order_by(Entry.id)
            )
        ).scalars()
        rows: list[list[str | None]] = []
        for entry_id in list(entries):
            values = await check.execute(
                select(EntryValue.value).where(EntryValue.entry_id == entry_id)
            )
            rows.append(list(values.scalars()))
        return rows


async def open_events(mark_id: int) -> int:
    async with TestSessionLocal() as check:
        result = await check.execute(
            select(func.count())
            .select_from(QuickMarkEvent)
            .where(
                QuickMarkEvent.quick_mark_id == mark_id,
                QuickMarkEvent.undone_at.is_(None),
            )
        )
        return int(result.scalar_one())


# --- increment ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
@pytest.mark.parametrize("day_started", [False, True], ids=["new-day", "started"])
async def test_parallel_presses_add_every_step(
    client: AsyncClient,
    db_session: AsyncSession,
    water: dict[str, Any],
    presses: int,
    day_started: bool,
) -> None:
    """N presses with N keys move the day by N steps, into one row of the day."""
    mark_id = await make_mark(client, water)
    before = 0
    if day_started:
        first = await press(client, mark_id, "first")
        assert first.status_code == 201, first.text
        before = STEP

    responses = await press_at_once(
        client, db_session, mark_id, [f"press-{i}" for i in range(presses)]
    )

    assert [r.status_code for r in responses] == [201] * presses
    assert await day_rows(water["id"], today_local()) == [
        [str(before + presses * STEP)]
    ]
    assert await open_events(mark_id) == presses + (1 if day_started else 0)


@pytest.mark.asyncio
async def test_two_buttons_on_one_field_add_both(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """`+250` and `+500` on the same field pressed together both land."""
    small = await make_mark(client, water)
    big = await make_mark(client, water, label="+500 мл", step=500)
    await db_session.commit()

    async with session_per_request():
        responses = await asyncio.gather(
            *(press(client, small, f"small-{i}") for i in range(3)),
            *(press(client, big, f"big-{i}") for i in range(3)),
        )

    assert [r.status_code for r in responses] == [201] * 6
    assert await day_rows(water["id"], today_local()) == [[str(3 * 250 + 3 * 500)]]


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
async def test_parallel_retries_of_one_key_add_one_step(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any], presses: int
) -> None:
    """One press retried N times at once is one press: one 201, the rest replay it."""
    mark_id = await make_mark(client, water)

    responses = await press_at_once(client, db_session, mark_id, ["same"] * presses)

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] * (presses - 1) + [201]
    assert {r.json()["event_id"] for r in responses} == {
        responses[0].json()["event_id"]
    }
    assert await day_rows(water["id"], today_local()) == [[str(STEP)]]
    assert await open_events(mark_id) == 1


# --- tick, relapse, checklist ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
async def test_parallel_ticks_leave_one_row_of_the_day(
    client: AsyncClient,
    db_session: AsyncSession,
    vitamins: dict[str, Any],
    presses: int,
) -> None:
    mark_id = await make_mark(client, vitamins, label="D3", kind="check", step=None)

    responses = await press_at_once(
        client, db_session, mark_id, [f"tick-{i}" for i in range(presses)]
    )

    assert [r.status_code for r in responses] == [201] * presses
    assert await day_rows(vitamins["id"], today_local()) == [["true"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
async def test_parallel_relapses_append_one_row_each(
    client: AsyncClient, db_session: AsyncSession, smoking: dict[str, Any], presses: int
) -> None:
    """A relapse is the one press that appends — N at once are N rows, none lost."""
    mark_id = await make_mark(client, smoking, label="Сорвался", kind="relapse", step=1)

    responses = await press_at_once(
        client, db_session, mark_id, [f"relapse-{i}" for i in range(presses)]
    )

    assert [r.status_code for r in responses] == [201] * presses
    assert await day_rows(smoking["id"], today_local()) == [["1"]] * presses
    assert await open_events(mark_id) == presses


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
async def test_parallel_checklist_puts_leave_one_row_of_the_day(
    client: AsyncClient,
    db_session: AsyncSession,
    vitamins: dict[str, Any],
    presses: int,
) -> None:
    """A double tap on a checklist box is one row of the day, not two."""
    on = today_local()
    payload = {
        "category_id": vitamins["id"],
        "entry_date": on.isoformat(),
        "values": {str(vitamins["fields"][0]["id"]): True},
    }
    await db_session.commit()

    async with session_per_request():
        responses = await asyncio.gather(
            *(client.put(CHECKLIST_URL, json=payload) for _ in range(presses))
        )

    assert [r.status_code for r in responses] == [200] * presses
    assert await day_rows(vitamins["id"], on) == [["true"]]


# --- undo --------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
async def test_undo_racing_presses_takes_back_only_its_own_step(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any], presses: int
) -> None:
    """
    Undo of the first press while N more arrive: its step leaves, theirs stay.

    The undo either runs before the presses and succeeds, or after one of them
    and is refused as no longer the last — both are honest. What is not allowed
    is a sum that lost a press or a step taken back twice.
    """
    mark_id = await make_mark(client, water)
    first = await press(client, mark_id, "first")
    assert first.status_code == 201, first.text
    await db_session.commit()

    async with session_per_request():
        undo, *pressed = await asyncio.gather(
            client.post(f"{QUICK_MARKS_URL}/events/{first.json()['event_id']}/undo"),
            *(press(client, mark_id, f"press-{i}") for i in range(presses)),
        )

    assert undo.status_code in (200, 409), undo.text
    assert [r.status_code for r in pressed] == [201] * presses
    kept = presses + (0 if undo.status_code == 200 else 1)
    assert await day_rows(water["id"], today_local()) == [[str(kept * STEP)]]
    assert await open_events(mark_id) == kept


@pytest.mark.asyncio
@pytest.mark.parametrize("undos", PARALLEL)
async def test_parallel_undos_of_one_press_take_it_back_once(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any], undos: int
) -> None:
    """The same undo sent N times at once: one 200, the rest refused, one step gone."""
    mark_id = await make_mark(client, water)
    for key in ("kept", "taken-back"):
        response = await press(client, mark_id, key)
        assert response.status_code == 201, response.text
    url = f"{QUICK_MARKS_URL}/events/{response.json()['event_id']}/undo"
    await db_session.commit()

    async with session_per_request():
        responses = await asyncio.gather(*(client.post(url) for _ in range(undos)))

    assert sorted(r.status_code for r in responses) == [200] + [409] * (undos - 1)
    assert await day_rows(water["id"], today_local()) == [[str(STEP)]]
    assert await open_events(mark_id) == 1


# --- the day-summary apply ---------------------------------------------------


SUMMARY_URL = "/api/v1/daily-summary/apply"


async def make_category(
    client: AsyncClient, name: str, fields: list[tuple[str, str]]
) -> dict[str, Any]:
    """A checklist category with the named fields, in that order."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "display_mode": "checklist",
            "fields": [
                {"name": field, "field_type": kind, "order": order}
                for order, (field, kind) in enumerate(fields, start=1)
            ],
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def check_op(category: dict[str, Any], field: int = 0) -> dict[str, Any]:
    return {
        "op": "check",
        "category_id": category["id"],
        "field_id": category["fields"][field]["id"],
        "source_text": "выпил",
    }


async def day_values(category_id: int, on: date) -> list[dict[int, str | None]]:
    """`{field_id: value}` of every entry of the category on that day."""
    async with TestSessionLocal() as check:
        result = await check.execute(
            select(EntryValue.entry_id, EntryValue.field_id, EntryValue.value)
            .join(Entry, Entry.id == EntryValue.entry_id)
            .where(Entry.category_id == category_id, Entry.entry_date == on)
            .order_by(EntryValue.entry_id)
        )
        by_entry: dict[int, dict[int, str | None]] = {}
        for entry_id, field_id, value in result.all():
            by_entry.setdefault(entry_id, {})[field_id] = value
        return list(by_entry.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("applies", PARALLEL)
async def test_parallel_applies_in_any_category_order_all_land(
    client: AsyncClient, db_session: AsyncSession, applies: int
) -> None:
    """
    Applies of one day naming the same categories in opposite orders: no deadlock.

    Each apply takes the day of several categories in one transaction. Taken in
    the order of the request, `[A, B]` and `[B, A]` would wait for each other.
    """
    categories = [
        await make_category(client, f"Чек {i}", [("x", "boolean")]) for i in range(6)
    ]
    on = today_local()
    await db_session.commit()

    bodies = [
        {
            "entry_date": on.isoformat(),
            "checklist": [
                check_op(c) for c in (categories if i % 2 else categories[::-1])
            ],
        }
        for i in range(applies)
    ]
    async with session_per_request():
        responses = await asyncio.gather(
            *(client.post(SUMMARY_URL, json=body) for body in bodies)
        )

    assert [r.status_code for r in responses] == [201] * applies
    for category in categories:
        assert await day_rows(category["id"], on) == [["true"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("presses", PARALLEL)
async def test_apply_racing_presses_of_its_category_loses_nothing(
    client: AsyncClient, db_session: AsyncSession, presses: int
) -> None:
    """
    An apply and the buttons of the same category at once: no deadlock, no lost press.

    The apply writes the number the buttons count (a replace, by design) and
    ticks one box; the buttons add to the number and tick another box that
    already says `false`. Every press after the apply has to stay in the sum, and
    the button's tick must not be overwritten by the `false` the apply read
    before it.
    """
    pills = await make_category(
        client,
        "Добавки",
        [("D3", "boolean"), ("Магний", "boolean"), ("Глотки", "number")],
    )
    d3, magnesium, sips = (f["id"] for f in pills["fields"])
    counter = await make_mark(client, pills, field_id=sips)
    tick = await make_mark(
        client, pills, label="Магний", kind="check", step=None, field_id=magnesium
    )
    on = today_local()
    started = await client.put(
        CHECKLIST_URL,
        json={
            "category_id": pills["id"],
            "entry_date": on.isoformat(),
            "values": {str(magnesium): False},
        },
    )
    assert started.status_code == 200, started.text
    await db_session.commit()

    summary = {
        "entry_date": on.isoformat(),
        "metrics": [
            {
                "op": "log_metric",
                "category_id": pills["id"],
                "field_id": sips,
                "value": 1000,
                "source_text": "выпил литр",
            }
        ],
        "checklist": [check_op(pills, field=0)],
    }
    async with session_per_request():
        applied, ticked, *pressed = await asyncio.gather(
            client.post(SUMMARY_URL, json=summary),
            press(client, tick, "tick"),
            *(press(client, counter, f"sip-{i}") for i in range(presses)),
        )

    assert applied.status_code == 201, applied.text
    assert ticked.status_code == 201, ticked.text
    assert [r.status_code for r in pressed] == [201] * presses
    [day] = await day_values(pills["id"], on)
    assert day[d3] == "true"
    assert day[magnesium] == "true"
    assert day[sips] in {str(1000 + STEP * after) for after in range(presses + 1)}


async def wait_for_a_waiter(timeout: float = 5.0) -> None:
    """Return once some transaction is queued on an advisory lock."""
    deadline = asyncio.get_running_loop().time() + timeout
    async with TestSessionLocal() as probe:
        while True:
            waiting = await probe.execute(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype = 'advisory' AND NOT granted"
                )
            )
            if int(waiting.scalar_one()) > 0:
                return
            assert asyncio.get_running_loop().time() < deadline, "nobody waited"
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_an_apply_reads_the_day_only_after_it_holds_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    A press holds the day; the apply queued behind it must see what the press wrote.

    The press creates the day's row and ticks a box while the apply waits. Read
    before the wait, the apply would add a second row for its number and write
    the box back to what it saw — a day split in two and a lost tick.
    """
    pills = await make_category(
        client,
        "Добавки",
        [("D3", "boolean"), ("Магний", "boolean"), ("Глотки", "number")],
    )
    d3, magnesium, sips = (f["id"] for f in pills["fields"])
    on = today_local()
    await db_session.commit()
    summary = {
        "entry_date": on.isoformat(),
        "metrics": [
            {
                "op": "log_metric",
                "category_id": pills["id"],
                "field_id": sips,
                "value": 1000,
                "source_text": "выпил литр",
            }
        ],
        "checklist": [check_op(pills, field=0)],
    }

    async with session_per_request(), TestSessionLocal() as holder:
        await entry_crud.lock_day(holder, pills["id"], on)
        applying = asyncio.create_task(client.post(SUMMARY_URL, json=summary))
        await wait_for_a_waiter()
        await entry_crud.upsert_checklist_values(
            holder, pills["id"], on, {magnesium: True}
        )
        await holder.commit()
        applied = await applying

    assert applied.status_code == 201, applied.text
    assert await day_values(pills["id"], on) == [
        {magnesium: "true", d3: "true", sips: "1000"}
    ]
