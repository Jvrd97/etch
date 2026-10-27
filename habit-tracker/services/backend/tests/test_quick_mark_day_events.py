# [review:need-review] PHASE-03/228
# summary: the undo-offer test pins its moment to 01:30 Berlin on a 01:00 boundary (UTC date and server day differ) and reads the day the rule names, so it no longer depends on the hour of the run
# [review:need-review] PHASE-01/206
# summary: the read of one category's quick-mark taps for a day — every set as its own row in time order, a taken-back tap flagged and kept, undo offered only where the undo endpoint would accept it, the day decided by the shared boundary, other days and other categories left out
"""
Tests for `GET /quick-marks/events`: the sets of one category on one day.

An increment folds five taps into one stored number, so the only place the five
sets still exist as sets is the journal. These tests read that journal back
through the wire, and the day it is read for is asked of `today_local()` like
every other read of Today — the boundary itself is `test_daytime.py`'s question.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.core.daytime import DayBoundary
from app.crud import quick_mark as quick_mark_crud

from tests.test_quick_mark_undo import undo
from tests.test_quick_marks import QUICK_MARKS_URL, make_mark, tap

DAY_EVENTS_URL = f"{QUICK_MARKS_URL}/events"
BERLIN = ZoneInfo("Europe/Berlin")


async def day_events(
    client: AsyncClient, category_id: int, **params: Any
) -> list[dict[str, Any]]:
    """The sets of one category on one day, as the wire carries them."""
    response = await client.get(
        DAY_EVENTS_URL, params={"category_id": category_id, **params}
    )
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


@pytest.mark.asyncio
async def test_each_tap_is_its_own_row_in_the_order_it_was_made(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Пять нажатий — пять строк, а не одна сумма; порядок — как нажимали."""
    mark = await make_mark(client, water)
    tapped = [(await tap(client, mark["id"]))[1]["event_id"] for _ in range(5)]

    events = await day_events(client, water["id"])

    assert [one["event_id"] for one in events] == tapped
    assert [one["delta"] for one in events] == [250] * 5
    first = events[0]
    assert first["quick_mark_id"] == mark["id"]
    assert first["label"] == "+250 мл"
    assert first["unit_label"] == "мл"
    assert first["kind"] == "increment"
    assert first["undone_at"] is None


@pytest.mark.asyncio
async def test_a_day_without_taps_is_an_empty_list(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Нет подходов — пустой список, а не 404."""
    await make_mark(client, water)

    assert await day_events(client, water["id"]) == []


@pytest.mark.asyncio
async def test_a_taken_back_tap_stays_in_the_list_flagged(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Отменённый подход остаётся в списке с отметкой — иначе итог не объяснить."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])
    _, second = await tap(client, mark["id"])
    status_code, _ = await undo(client, second["event_id"])
    assert status_code == 200

    events = await day_events(client, water["id"])

    assert len(events) == 2
    assert events[0]["undone_at"] is None
    assert events[1]["undone_at"] is not None


@pytest.mark.asyncio
async def test_only_the_last_open_tap_of_a_button_is_offered_for_undo(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """`undoable` повторяет правило ручки отмены: только последний открытый тап."""
    mark = await make_mark(client, water)
    for _ in range(3):
        await tap(client, mark["id"])

    events = await day_events(client, water["id"])

    assert [one["undoable"] for one in events] == [False, False, True]


@pytest.mark.asyncio
async def test_the_previous_tap_becomes_undoable_once_the_last_is_taken_back(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Размотать подходы можно по одному: после отмены последнего открывается предыдущий."""
    mark = await make_mark(client, water)
    for _ in range(3):
        await tap(client, mark["id"])
    before = await day_events(client, water["id"])
    await undo(client, before[2]["event_id"])

    after = await day_events(client, water["id"])

    assert [one["undoable"] for one in after] == [False, True, False]


@pytest.mark.asyncio
async def test_every_button_of_the_category_is_listed_with_its_own_last_tap(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Две кнопки на одной категории: строки обеих, и у каждой свой последний тап."""
    small = await make_mark(client, water, label="+250 мл")
    large = await make_mark(client, water, label="+500 мл", step=500)
    await tap(client, small["id"])
    await tap(client, large["id"])
    await tap(client, small["id"])

    events = await day_events(client, water["id"])

    assert [one["label"] for one in events] == ["+250 мл", "+500 мл", "+250 мл"]
    assert [one["undoable"] for one in events] == [False, True, True]


@pytest.mark.asyncio
async def test_other_categories_do_not_leak_into_the_list(
    client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
) -> None:
    """Подходы чужой категории в список не попадают."""
    drink = await make_mark(client, water)
    pill = await make_mark(client, vitamins, kind="check", step=None, label="D3")
    await tap(client, drink["id"])
    await tap(client, pill["id"])

    events = await day_events(client, water["id"])

    assert [one["quick_mark_id"] for one in events] == [drink["id"]]


@pytest.mark.asyncio
async def test_a_tick_reports_the_box_it_set(
    client: AsyncClient, vitamins: dict[str, Any]
) -> None:
    """Галка не количество: в строке `bool_value`, а `delta` пуст."""
    mark = await make_mark(client, vitamins, kind="check", step=None, label="D3")
    await tap(client, mark["id"])

    (event,) = await day_events(client, vitamins["id"])

    assert event["bool_value"] is True
    assert event["delta"] is None


@pytest.mark.asyncio
async def test_a_relapse_is_listed_like_any_other_tap(
    client: AsyncClient, smoking: dict[str, Any]
) -> None:
    """Срыв — тоже отметка дня со своим временем."""
    mark = await make_mark(
        client, smoking, kind="relapse", step=1, label="Сигарета", unit_label=None
    )
    await tap(client, mark["id"])

    (event,) = await day_events(client, smoking["id"])

    assert event["kind"] == "relapse"
    assert event["delta"] == 1
    assert event["undoable"] is True


@pytest.mark.asyncio
async def test_the_day_is_the_one_the_shared_boundary_gives(
    client: AsyncClient,
    db_session: AsyncSession,
    water: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Подход в 00:30 при границе дня 01:00 принадлежит предыдущему дню.

    Ответ сверяется с тем днём, который назвала запись, а не с календарём: чтение
    и запись обязаны ответить на «какое сегодня число» одинаково.
    """
    boundary = DayBoundary(timezone="Europe/Berlin", day_start_hour=1)
    daytime.use_boundary(boundary)
    created = await make_mark(client, water)
    mark = await quick_mark_crud.get_quick_mark(db_session, created["id"])
    assert mark is not None
    late = datetime(2026, 8, 29, 0, 30, tzinfo=BERLIN)
    morning = datetime(2026, 8, 29, 9, 0, tzinfo=BERLIN)
    await quick_mark_crud.record_event(db_session, mark, at=late, source="web")
    await quick_mark_crud.record_event(db_session, mark, at=morning, source="web")

    night_day = await day_events(client, water["id"], date="2026-08-28")
    next_day = await day_events(client, water["id"], date="2026-08-29")

    assert [one["entry_date"] for one in night_day] == ["2026-08-28"]
    assert [one["entry_date"] for one in next_day] == ["2026-08-29"]

    monkeypatch.setattr(
        daytime,
        "now_utc",
        lambda: morning.astimezone(timezone.utc) + timedelta(hours=1),
    )
    default_day = await day_events(client, water["id"])
    assert [one["entry_date"] for one in default_day] == ["2026-08-29"]


@pytest.mark.asyncio
async def test_another_day_is_left_out(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Подходы вчерашнего дня в сегодняшний список не попадают."""
    created = await make_mark(client, water)
    mark = await quick_mark_crud.get_quick_mark(db_session, created["id"])
    assert mark is not None
    now = datetime.now(timezone.utc)
    await quick_mark_crud.record_event(
        db_session, mark, at=now - timedelta(days=3), source="web"
    )
    await tap(client, created["id"])

    today = await day_events(client, water["id"])

    assert len(today) == 1
    assert today[0]["entry_date"] != (now - timedelta(days=3)).date().isoformat()


@pytest.mark.asyncio
async def test_an_old_day_offers_no_undo_for_taps_that_are_no_longer_last(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """
    Подход прошлого дня не последний у кнопки, если после него были другие.

    Момент подхода закреплён за границей дня, где календарная дата UTC и день
    сервера расходятся: 01:30 по Берлину при границе 01:00 — это 23:30 UTC
    предыдущего числа. Запрашивается день, который назвало правило, а не
    `.date()` от UTC, поэтому результат не зависит от времени суток прогона.
    """
    daytime.use_boundary(DayBoundary(timezone="Europe/Berlin", day_start_hour=1))
    created = await make_mark(client, water)
    mark = await quick_mark_crud.get_quick_mark(db_session, created["id"])
    assert mark is not None
    old = datetime(2026, 8, 29, 1, 30, tzinfo=BERLIN)
    assert old.astimezone(timezone.utc).date().isoformat() == "2026-08-28"
    await quick_mark_crud.record_event(db_session, mark, at=old, source="web")
    await tap(client, created["id"])

    past = await day_events(
        client, water["id"], date=daytime.local_date(old).isoformat()
    )

    assert [one["undoable"] for one in past] == [False]


@pytest.mark.asyncio
async def test_the_category_is_required(client: AsyncClient) -> None:
    """Без категории список не имеет смысла — 422, а не все подходы подряд."""
    response = await client.get(DAY_EVENTS_URL)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_read_does_not_change_the_day(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Только чтение: сумма дня после запроса списка прежняя."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])
    await tap(client, mark["id"])
    before = (await client.get(QUICK_MARKS_URL)).json()[0]["today_total"]

    await day_events(client, water["id"])

    after = (await client.get(QUICK_MARKS_URL)).json()[0]["today_total"]
    assert before == after == 500
