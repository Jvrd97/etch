# [review:need-review] PHASE-03/236, PHASE-03/256
# summary: PHASE-03/256 — a key found after a lost race leaves the day total of the asking button as it was, and a button deleted between the insert and the read-back is 404, not 500
# summary: PHASE-03/236 round 3 — a key of another button's tap is 409 also when it is found only after the insert lost the race on the unique key
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
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api import quick_marks as quick_marks_api
from app.crud import quick_mark as quick_mark_crud
from app.models.quick_mark import QuickMark, QuickMarkEvent
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


async def day_total(client: AsyncClient, mark_id: int) -> float | None:
    """The day total the directory shows next to the button, for the day of `NOW`."""
    response = await client.get(
        QUICK_MARKS_URL, params={"date": NOW.date().isoformat()}
    )
    assert response.status_code == 200, response.text
    (listed,) = [one for one in response.json() if one["id"] == mark_id]
    total = listed["today_total"]
    return None if total is None else float(total)


async def day_event_count(client: AsyncClient, category: dict[str, Any]) -> int:
    """How many taps the journal lists for the category on the day of `NOW`."""
    response = await client.get(
        f"{QUICK_MARKS_URL}/events",
        params={"category_id": category["id"], "date": NOW.date().isoformat()},
    )
    assert response.status_code == 200, response.text
    return len(response.json())


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

NOW = at_berlin(20, 8, 0)


@pytest.mark.parametrize(
    ("pressed", "lands_on"),
    [
        pytest.param(
            NOW + timedelta(minutes=5, seconds=1), "2026-10-20", id="5m01s-ahead"
        ),
        pytest.param(
            NOW - timedelta(days=7, seconds=1), "2026-10-13", id="7d1s-before"
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_moment_outside_the_window_is_422(
    client: AsyncClient,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    pressed: datetime,
    lands_on: str,
) -> None:
    """Дальше +5 минут и старше семи дней — 422 в списочной форме, в тот день ничего не легло."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, NOW)

    status_code, body = await tap(client, mark_id, occurred_at=wire(pressed))

    assert status_code == 422, body
    assert [problem["loc"] for problem in body["detail"]] == [["body", "occurred_at"]]
    events = await client.get(
        f"{QUICK_MARKS_URL}/events",
        params={"category_id": water["id"], "date": lands_on},
    )
    assert events.json() == []


@pytest.mark.parametrize(
    "pressed",
    [
        pytest.param(NOW + timedelta(minutes=5), id="exactly-5m-ahead"),
        pytest.param(NOW - timedelta(days=7), id="exactly-7d-before"),
    ],
)
@pytest.mark.asyncio
async def test_a_moment_on_the_edge_of_the_window_is_taken(
    client: AsyncClient,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    pressed: datetime,
) -> None:
    """Ровно +5 минут и ровно семь дней назад — ещё в окне."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, NOW)

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


@pytest.mark.asyncio
async def test_the_same_key_with_another_moment_answers_the_first_event(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ключ решает, а не момент: повтор с другим `occurred_at` — то же первое событие."""
    mark_id = await make_mark(client, water)
    serve_at(monkeypatch, NOW)
    _, first = await tap(
        client, mark_id, key="k-moment", occurred_at=wire(at_berlin(19, 22, 0))
    )

    status_code, again = await tap(
        client, mark_id, key="k-moment", occurred_at=wire(at_berlin(20, 7, 0))
    )

    assert status_code == 200, again
    assert again["event_id"] == first["event_id"]
    assert again["occurred_at"] == first["occurred_at"]


@pytest.mark.asyncio
async def test_a_key_of_another_buttons_tap_is_409(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ключ принадлежит нажатию кнопки A: тот же ключ на кнопке B — 409, а не событие A."""
    first_id = await make_mark(client, water)
    second_id = await make_mark(client, water)
    serve_at(monkeypatch, NOW)
    await tap(client, first_id, key="k-shared")

    status_code, body = await tap(client, second_id, key="k-shared")

    assert status_code == 409, body
    assert "another quick mark" in body["detail"]


@pytest.mark.parametrize(
    ("same_button", "expected_status"),
    [
        pytest.param(True, 200, id="same-button"),
        pytest.param(False, 409, id="other-button"),
    ],
)
@pytest.mark.asyncio
async def test_a_key_found_only_after_a_lost_race_answers_like_a_replay(
    client: AsyncClient,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    same_button: bool,
    expected_status: int,
) -> None:
    """
    Гонка: поиск по ключу ещё ничего не нашёл, вставка упала на уникальном ключе.

    Победитель — нажатие кнопки A. Спрашивала A — 200 с её событием; кнопка B — 409.
    """
    first_id = await make_mark(client, water)
    second_id = first_id if same_button else await make_mark(client, water)
    serve_at(monkeypatch, NOW)
    await tap(client, first_id, key="k-race")
    total_before = await day_total(client, second_id)
    assert total_before == 250, "the winner's tap is on the shared day"
    real_lookup = quick_mark_crud.event_by_idempotency_key
    calls = 0

    async def misses_once(db: AsyncSession, key: str) -> QuickMarkEvent | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real_lookup(db, key)

    monkeypatch.setattr(quick_mark_crud, "event_by_idempotency_key", misses_once)

    status_code, body = await tap(client, second_id, key="k-race")

    assert calls == 2, "the insert hit the unique key and the winner was read back"
    assert status_code == expected_status, body
    total_after = await day_total(client, second_id)
    assert total_after == total_before, "the rolled-back insert changed the day total"
    assert await day_event_count(client, water) == 1, "the loser left an event"
    if not same_button:
        assert "another quick mark" in body["detail"]


@pytest.mark.asyncio
async def test_a_button_deleted_after_a_lost_race_is_404_not_500(
    client: AsyncClient, water: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кнопку B удалили между упавшей вставкой и повторным чтением: 404, а не 500."""
    first_id = await make_mark(client, water)
    second_id = await make_mark(client, water)
    serve_at(monkeypatch, NOW)
    await tap(client, first_id, key="k-gone")
    real_lookup = quick_mark_crud.event_by_idempotency_key
    calls = 0

    async def deletes_the_button_after_the_loss(
        db: AsyncSession, key: str
    ) -> QuickMarkEvent | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        winner = await real_lookup(db, key)
        await db.execute(delete(QuickMark).where(QuickMark.id == second_id))
        await db.commit()
        return winner

    monkeypatch.setattr(
        quick_mark_crud, "event_by_idempotency_key", deletes_the_button_after_the_loss
    )

    status_code, body = await tap(client, second_id, key="k-gone")

    assert calls == 2, "the loss was reached: the winner was read back"
    assert status_code == 404, body


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
