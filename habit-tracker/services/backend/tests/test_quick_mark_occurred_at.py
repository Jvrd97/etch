# [review:need-review] PHASE-03/236
# summary: the moment of a press in the body of a quick-mark tap — a press delivered after the day turned lands on the day it was made (calendar midnight and the 04:00 boundary), no field keeps the old behaviour, the future and anything older than the window are 422, a replayed key answers 200 even after the day or the window moved on, and the statements of a tap do not grow with the field
"""
`occurred_at` — когда нажали, а не когда запрос дошёл.

Телефон без сети копит нажатия и отправляет их позже. Без момента нажатия
сервер кладёт отметку в день доставки: вода, выпитая в 23:50 и доставленная в
00:10, попадает в следующий день. С моментом день считает тот же `local_date()`,
только от момента нажатия.

Граница суток здесь задаётся явно (`use_boundary`): тест про 23:50 и 00:10
имеет смысл только при границе в полночь, тест про 04:00 — при границе в 04:00.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api import quick_marks as quick_marks_api
from app.core import daytime
from app.core.daytime import DayBoundary

QUICK_MARKS_URL = "/api/v1/quick-marks"
BERLIN = ZoneInfo("Europe/Berlin")


def at_berlin(day: int, hour: int, minute: int = 0) -> datetime:
    """A wall-clock moment of October 2026 in Berlin."""
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


def wire(moment: datetime) -> str:
    """The moment as the phone sends it: UTC with `Z`."""
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def serve_at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """The server's clock reads `moment` when the request arrives."""
    monkeypatch.setattr(
        quick_marks_api, "now_utc", lambda: moment.astimezone(timezone.utc)
    )


async def make_mark(client: AsyncClient, category: dict[str, Any]) -> int:
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "+250 мл",
            "category_id": category["id"],
            "field_id": int(category["fields"][0]["id"]),
            "kind": "increment",
            "step": 250,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def tap(
    client: AsyncClient, mark_id: int, *, key: str | None = None, **body: Any
) -> tuple[int, dict[str, Any]]:
    headers = {"Idempotency-Key": key} if key is not None else {}
    response = await client.post(
        f"{QUICK_MARKS_URL}/{mark_id}/events", json=body, headers=headers
    )
    return response.status_code, response.json()


@contextmanager
def statements_of(db: AsyncSession) -> Iterator[list[str]]:
    """Every SQL statement the session runs inside the block."""
    seen: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        seen.append(statement)

    assert isinstance(db.bind, AsyncEngine)
    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


# --- the day of a press -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_press_at_2350_delivered_at_0010_lands_on_yesterday(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Граница в полночь: нажали 23:50, дошло в 00:10 — отметка во вчерашнем дне."""
    daytime.use_boundary(DayBoundary(timezone="Europe/Berlin", day_start_hour=0))
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 0, 10))

    status_code, body = await tap(
        client, mark_id, occurred_at=wire(at_berlin(19, 23, 50))
    )

    assert status_code == 201, body
    assert body["entry_date"] == "2026-10-19"
    assert body["occurred_at"] == wire(at_berlin(19, 23, 50))


@pytest.mark.asyncio
async def test_without_the_moment_the_press_lands_on_the_day_of_delivery(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без поля — прежнее поведение: веб и мак-агент ничего не меняют."""
    daytime.use_boundary(DayBoundary(timezone="Europe/Berlin", day_start_hour=0))
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 0, 10))

    status_code, body = await tap(client, mark_id)

    assert status_code == 201, body
    assert body["entry_date"] == "2026-10-20"


@pytest.mark.parametrize(
    ("pressed", "expected_day"),
    [
        (at_berlin(20, 3, 50), "2026-10-19"),
        (at_berlin(20, 4, 0), "2026-10-20"),
    ],
)
@pytest.mark.asyncio
async def test_the_0400_boundary_decides_the_day_of_the_press(
    client: AsyncClient,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    pressed: datetime,
    expected_day: str,
) -> None:
    """Граница 04:00: 03:50 — ещё вчера, 04:00 — уже сегодня, где бы ни был сервер."""
    daytime.use_boundary(DayBoundary(timezone="Europe/Berlin", day_start_hour=4))
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 8, 0))

    status_code, body = await tap(client, mark_id, occurred_at=wire(pressed))

    assert status_code == 201, body
    assert body["entry_date"] == expected_day


@pytest.mark.asyncio
async def test_the_client_day_is_checked_against_the_day_of_the_press(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`entry_date` рядом с моментом сверяется с днём нажатия, а не доставки."""
    daytime.use_boundary(DayBoundary(timezone="Europe/Berlin", day_start_hour=4))
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 8, 0))

    status_code, body = await tap(
        client,
        mark_id,
        occurred_at=wire(at_berlin(20, 1, 0)),
        entry_date="2026-10-19",
    )

    assert status_code == 201, body
    assert body["entry_date"] == "2026-10-19"


# --- the window -------------------------------------------------------------


@pytest.mark.parametrize(
    "pressed",
    [
        pytest.param(at_berlin(20, 9, 0), id="an-hour-ahead"),
        pytest.param(at_berlin(12, 7, 59), id="older-than-seven-days"),
    ],
)
@pytest.mark.asyncio
async def test_a_moment_outside_the_window_is_422(
    client: AsyncClient,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    pressed: datetime,
) -> None:
    """Будущее и старше семи дней — 422, ничего не записано."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 8, 0))

    status_code, body = await tap(client, mark_id, occurred_at=wire(pressed))

    assert status_code == 422, body
    events = await client.get(
        f"{QUICK_MARKS_URL}/events",
        params={"category_id": water["id"], "date": "2026-10-20"},
    )
    assert events.json() == []


@pytest.mark.parametrize(
    "pressed",
    [
        pytest.param(at_berlin(20, 8, 1), id="clock-a-minute-ahead"),
        pytest.param(at_berlin(13, 8, 1), id="just-inside-seven-days"),
    ],
)
@pytest.mark.asyncio
async def test_a_moment_inside_the_window_is_taken(
    client: AsyncClient,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    pressed: datetime,
) -> None:
    """Часы телефона на минуту впереди и нажатие шестидневной давности принимаются."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 8, 0))

    status_code, body = await tap(client, mark_id, occurred_at=wire(pressed))

    assert status_code == 201, body


@pytest.mark.asyncio
async def test_a_moment_without_an_offset_is_422(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Голое время без смещения не читается как UTC молча."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 8, 0))

    status_code, body = await tap(client, mark_id, occurred_at="2026-10-20T06:00:00")

    assert status_code == 422, body


# --- idempotency ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_replay_with_the_same_moment_is_the_same_event(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тот же ключ и тот же момент — 200, то же событие, сумма не удвоилась."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 8, 0))
    pressed = wire(at_berlin(19, 22, 0))

    first_status, first = await tap(client, mark_id, key="k-1", occurred_at=pressed)
    second_status, second = await tap(client, mark_id, key="k-1", occurred_at=pressed)

    assert (first_status, second_status) == (201, 200)
    assert second["event_id"] == first["event_id"]
    assert second["today_total"] == first["today_total"] == 250


@pytest.mark.asyncio
async def test_a_replay_after_the_window_closed_still_answers_the_recorded_event(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Записанное нажатие — ответ на свой ключ, даже когда окно уже закрылось."""
    mark_id = await make_mark(client, water)
    pressed = wire(at_berlin(19, 22, 0))
    serve_at(monkeypatch, at_berlin(20, 8, 0))
    _, first = await tap(client, mark_id, key="k-late", occurred_at=pressed)

    serve_at(monkeypatch, at_berlin(28, 8, 0))
    status_code, again = await tap(client, mark_id, key="k-late", occurred_at=pressed)

    assert status_code == 200, again
    assert again["event_id"] == first["event_id"]


@pytest.mark.asyncio
async def test_a_replay_after_the_day_turned_is_not_refused(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ответ потерялся, день сменился: повтор того же ключа — 200, а не 409."""
    daytime.use_boundary(DayBoundary(timezone="Europe/Berlin", day_start_hour=4))
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(19, 23, 0))
    _, first = await tap(client, mark_id, key="k-day", entry_date="2026-10-19")

    serve_at(monkeypatch, at_berlin(20, 5, 0))
    status_code, again = await tap(
        client, mark_id, key="k-day", entry_date="2026-10-19"
    )

    assert status_code == 200, again
    assert again["event_id"] == first["event_id"]


# --- cost -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_moment_does_not_add_statements(
    client: AsyncClient,
    db_session: AsyncSession,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нажатие с моментом стоит столько же SQL, сколько без него, и не дороже от давности."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, at_berlin(20, 12, 0))
    await tap(client, mark_id)

    with statements_of(db_session) as plain:
        await tap(client, mark_id, key="plain")
    with statements_of(db_session) as recent:
        await tap(client, mark_id, key="recent", occurred_at=wire(at_berlin(20, 11, 0)))
    with statements_of(db_session) as older:
        await tap(client, mark_id, key="older", occurred_at=wire(at_berlin(20, 5, 0)))

    assert len(recent) == len(plain)
    assert len(older) == len(plain)
