# [review:need-review] PHASE-03/124
# summary: every acceptance case of undo — one action puts the day's sum back, a second undo of the same tap is 409, a value edited by hand refuses to be unwound and keeps the figure the person typed, only the last open tap is undoable, a retry under one Idempotency-Key leaves one event and one sum, a relapse undo takes its entry with it, and the source of every tap is recorded and readable as a distribution
"""
Tests for taking one tap back.

The rule under test is narrow on purpose, and each refusal is checked by its
consequence rather than by its wording: after a refused undo the stored value is
read again and has to be the one the person left there. A test that only
asserted the status code would pass on an implementation that answered 409 after
already subtracting.

Which day a tap belongs to is not re-derived here either. `test_daytime.py` owns
that question; this file asserts only that undo lands in the same day the tap
did, which is what keeps a second answer to "какое сегодня число" from
appearing under the undo path.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import quick_mark as quick_mark_crud
from app.models import Entry, EntryValue
from app.models.quick_mark import QuickMarkEvent

from tests.test_quick_marks import QUICK_MARKS_URL, make_mark, only_field, tap


async def undo(client: AsyncClient, event_id: int) -> tuple[int, dict[str, Any]]:
    """Take one tap back; returns the status code and the body."""
    response = await client.post(f"{QUICK_MARKS_URL}/events/{event_id}/undo")
    return response.status_code, response.json()


async def stored_total(db: AsyncSession, category_id: int, field_id: int) -> list[str]:
    """Every stored value of one field, as text, in id order."""
    result = await db.execute(
        select(EntryValue.value)
        .join(Entry, Entry.id == EntryValue.entry_id)
        .where(Entry.category_id == category_id, EntryValue.field_id == field_id)
        .order_by(EntryValue.id)
    )
    return [value for value in result.scalars().all() if value is not None]


async def rows(db: AsyncSession, table: Any, **where: Any) -> int:
    clauses = [getattr(table, name) == value for name, value in where.items()]
    result = await db.execute(select(func.count()).select_from(table).where(*clauses))
    return int(result.scalar_one())


# --- one action puts the sum back -------------------------------------------


@pytest.mark.asyncio
async def test_undo_returns_the_day_to_the_previous_sum(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Одно действие «Отменить» возвращает сумму дня к прежнему числу."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])
    await tap(client, mark["id"])
    _, third = await tap(client, mark["id"])
    assert third["today_total"] == 750

    status_code, body = await undo(client, third["event_id"])

    assert status_code == 200, body
    assert body["today_total"] == 500
    assert body["done"] is True
    assert await stored_total(db_session, water["id"], only_field(water)) == ["500"]


@pytest.mark.asyncio
async def test_undo_lands_in_the_day_the_tap_landed_in(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """День отмены — тот же, что у тапа: своей даты этот путь не считает."""
    mark = await make_mark(client, water)
    _, tapped = await tap(client, mark["id"])

    _, body = await undo(client, tapped["event_id"])

    assert body["entry_date"] == tapped["entry_date"]


@pytest.mark.asyncio
async def test_undoing_the_only_tap_leaves_the_day_at_zero(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Отмена единственного тапа — день не «выпил ноль», а не отмечен вовсе."""
    mark = await make_mark(client, water)
    _, tapped = await tap(client, mark["id"])

    _, body = await undo(client, tapped["event_id"])

    assert body["today_total"] == 0
    assert body["done"] is False


@pytest.mark.asyncio
async def test_a_tick_returns_to_where_it_stood(
    client: AsyncClient, vitamins: dict[str, Any]
) -> None:
    """Галка после отмены возвращается в снятое состояние."""
    mark = await make_mark(client, vitamins, kind="check", step=None, label="D3")
    _, ticked = await tap(client, mark["id"])
    assert ticked["done"] is True

    _, body = await undo(client, ticked["event_id"])

    assert body["done"] is False
    assert body["today_total"] is None


@pytest.mark.asyncio
async def test_set_value_undo_restores_the_figure_it_replaced(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """`set_value` после отмены возвращает то число, которое перезаписал."""
    mark = await make_mark(client, water, kind="set_value", step=1000)
    await tap(client, mark["id"], value=600)
    _, second = await tap(client, mark["id"], value=2000)
    assert second["today_total"] == 2000

    _, body = await undo(client, second["event_id"])

    assert body["today_total"] == 600


# --- the three refusals ------------------------------------------------------


@pytest.mark.asyncio
async def test_undoing_the_same_event_twice_is_refused(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Повторная отмена того же события — 409, и сумму она не трогает."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])
    _, second = await tap(client, mark["id"])
    assert (await undo(client, second["event_id"]))[0] == 200

    status_code, body = await undo(client, second["event_id"])

    assert status_code == 409
    assert "already undone" in body["detail"]
    assert await stored_total(db_session, water["id"], only_field(water)) == ["250"]


@pytest.mark.asyncio
async def test_only_the_last_open_tap_is_undoable(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Отмена не последнего события отвергается: только последний тап."""
    mark = await make_mark(client, water)
    _, first = await tap(client, mark["id"])
    await tap(client, mark["id"])

    status_code, body = await undo(client, first["event_id"])

    assert status_code == 409
    assert "last tap" in body["detail"]
    assert await stored_total(db_session, water["id"], only_field(water)) == ["500"]


@pytest.mark.asyncio
async def test_a_value_edited_by_hand_refuses_undo_and_is_left_alone(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """
    Правка руками, затем отмена тапа — 409, и значение остаётся тем, что поставил человек.

    Ручной ввод первичен: расхождение журнала и `entry_values` разрешено
    ADR-0018 сознательно, поэтому единственный честный ответ — отказ, а не
    вычитание из числа, которого журнал не писал.
    """
    mark = await make_mark(client, water)
    _, tapped = await tap(client, mark["id"])

    entry_id = tapped["entry_id"]
    edited = await client.patch(
        f"/api/v1/entries/{entry_id}",
        json={"values": [{"field_id": only_field(water), "value": "1337"}]},
    )
    assert edited.status_code == 200, edited.text

    status_code, body = await undo(client, tapped["event_id"])

    assert status_code == 409
    assert "outside the journal" in body["detail"]
    assert await stored_total(db_session, water["id"], only_field(water)) == ["1337"]


@pytest.mark.asyncio
async def test_undo_of_an_unknown_event_is_404(client: AsyncClient) -> None:
    """Несуществующее событие — 404, а не 409."""
    status_code, _body = await undo(client, 999999)
    assert status_code == 404


# --- the retry after a broken connection ------------------------------------


@pytest.mark.asyncio
async def test_a_retry_under_one_key_leaves_one_event_and_one_sum(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Повтор отправки после обрыва не удваивает сумму и даёт тот же `event_id`."""
    mark = await make_mark(client, water)

    first_status, first = await tap(client, mark["id"], idempotency_key="tap-1")
    second_status, second = await tap(client, mark["id"], idempotency_key="tap-1")

    assert (first_status, second_status) == (201, 200)
    assert first["event_id"] == second["event_id"]
    assert second["today_total"] == 250
    assert await rows(db_session, QuickMarkEvent, quick_mark_id=mark["id"]) == 1
    assert await stored_total(db_session, water["id"], only_field(water)) == ["250"]


@pytest.mark.asyncio
async def test_the_replayed_event_can_still_be_undone_once(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Отменяется ровно один раз то, что записалось ровно один раз."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"], idempotency_key="tap-1")
    _, replayed = await tap(client, mark["id"], idempotency_key="tap-1")

    assert (await undo(client, replayed["event_id"]))[0] == 200
    assert (await undo(client, replayed["event_id"]))[0] == 409
    assert await stored_total(db_session, water["id"], only_field(water)) == ["0"]


# --- the relapse takes its row with it --------------------------------------


@pytest.mark.asyncio
async def test_undoing_a_relapse_removes_the_row_it_appended(
    client: AsyncClient, db_session: AsyncSession, smoking: dict[str, Any]
) -> None:
    """Отмена `relapse` убирает созданную запись срыва, а не оставляет её висеть."""
    mark = await make_mark(
        client, smoking, kind="relapse", step=1, label="сорвался", unit_label=None
    )
    await tap(client, mark["id"])
    _, second = await tap(client, mark["id"])
    assert await rows(db_session, Entry, category_id=smoking["id"]) == 2

    _, body = await undo(client, second["event_id"])

    assert body["today_total"] == 1
    assert await rows(db_session, Entry, category_id=smoking["id"]) == 1


# --- the source of every tap -------------------------------------------------


@pytest.mark.asyncio
async def test_every_event_carries_its_source(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """У каждого события в журнале есть источник; веб по умолчанию шлёт `web`."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])
    await tap(client, mark["id"], source="agent")

    result = await db_session.execute(
        select(QuickMarkEvent.source)
        .where(QuickMarkEvent.quick_mark_id == mark["id"])
        .order_by(QuickMarkEvent.id)
    )
    assert list(result.scalars().all()) == ["web", "agent"]


@pytest.mark.asyncio
async def test_an_unknown_source_is_refused_rather_than_stored(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Неизвестный `source` отклоняется, а не пишется как есть."""
    mark = await make_mark(client, water)

    status_code, _body = await tap(client, mark["id"], source="telepathy")

    assert status_code == 422
    assert await rows(db_session, QuickMarkEvent, quick_mark_id=mark["id"]) == 0


@pytest.mark.asyncio
async def test_the_distribution_splits_taps_between_clients(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Запрос по `source` показывает распределение отметок между вебом и агентом."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])
    await tap(client, mark["id"], source="agent")
    _, last = await tap(client, mark["id"], source="agent")
    assert (await undo(client, last["event_id"]))[0] == 200

    response = await client.get(f"{QUICK_MARKS_URL}/events/sources")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"source": "agent", "events": 2, "undone": 1},
        {"source": "web", "events": 1, "undone": 0},
    ]


@pytest.mark.asyncio
async def test_the_distribution_answers_for_the_days_it_was_asked_about(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Период сужает выборку; клиент, ничего не писавший в нём, отсутствует."""
    mark = await make_mark(client, water)
    _, tapped = await tap(client, mark["id"])
    today = date.fromisoformat(tapped["entry_date"])
    yesterday = today - timedelta(days=1)

    db_session.add(
        QuickMarkEvent(
            quick_mark_id=mark["id"],
            entry_id=None,
            entry_date=yesterday,
            source="agent",
        )
    )
    await db_session.commit()

    usage = await quick_mark_crud.source_usage(db_session, since=today)

    assert [(row.source, row.events) for row in usage] == [("web", 1)]


# --- the log says nothing about what was tracked -----------------------------


def test_no_message_of_this_slice_carries_a_label() -> None:
    """
    Причины отказа строятся из id, а не из того, что человек назвал кнопкой.

    Заголовок кнопки человек может назвать диагнозом, поэтому текст отказа
    обязан состоять из идентификаторов. Проверяется грепом по исходнику, а не
    чтением одного сообщения: правило про весь модуль, не про одну строку.
    """
    source = (quick_mark_crud.__file__ or "").replace(".pyc", ".py")
    text = open(source, encoding="utf-8").read()
    undo_block = text[text.index("async def undo_event") :]
    assert "mark.label" not in undo_block
    assert "event.label" not in undo_block
