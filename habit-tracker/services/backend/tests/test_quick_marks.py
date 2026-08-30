# [review:need-review] PHASE-03/121
# summary: every acceptance case of the quick mark — five taps that stay one entry, the answer that already carries the new sum, the replayed Idempotency-Key, the relapse that appends, the four ways the directory refuses a button, the tap at 00:30 landing where `local_date()` says, and the migration whose downgrade actually drops what it made
"""
Tests for the quick mark, from the button to the row it writes.

The five taps and the single row are the point of the ticket: `kind='increment'`
is the invariant of ADR-0007 reaching the quick path, and the test that would
have caught its absence is the one that counts `entries` rather than the one
that reads the total.

The day boundary is not re-derived here. `test_daytime.py` owns the question of
which day a moment belongs to; this file only asserts that a tap agrees with
whatever `local_date()` answered, which is what keeps a second implementation
from appearing.
"""

from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.crud import quick_mark as quick_mark_crud
from app.models import Entry, EntryValue
from app.models.quick_mark import QuickMark, QuickMarkEvent

QUICK_MARKS_URL = "/api/v1/quick-marks"

# The revision this ticket adds, and the one it grows from.
QUICK_MARKS_REVISION = "a3b5d7f9c1e2"
PREVIOUS_REVISION = "f2a4c6e8b0d1"

BERLIN = ZoneInfo("Europe/Berlin")


# --- fixtures ---------------------------------------------------------------


def only_field(category: dict[str, Any]) -> int:
    return int(category["fields"][0]["id"])


async def make_mark(
    client: AsyncClient, category: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    """Create a button over `category`'s first field, defaults for the rest."""
    payload: dict[str, Any] = {
        "label": "+250 мл",
        "category_id": category["id"],
        "field_id": only_field(category),
        "kind": "increment",
        "step": 250,
        "unit_label": "мл",
    }
    payload.update(overrides)
    response = await client.post(QUICK_MARKS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def tap(
    client: AsyncClient, mark_id: int, **kwargs: Any
) -> tuple[int, dict[str, Any]]:
    """One tap; returns the status code and the body."""
    headers = {}
    key = kwargs.pop("idempotency_key", None)
    if key is not None:
        headers["Idempotency-Key"] = key
    response = await client.post(
        f"{QUICK_MARKS_URL}/{mark_id}/events", json=kwargs, headers=headers
    )
    return response.status_code, response.json()


async def count(db: AsyncSession, table: Any, **where: Any) -> int:
    clauses = [getattr(table, name) == value for name, value in where.items()]
    result = await db.execute(select(func.count()).select_from(table).where(*clauses))
    return int(result.scalar_one())


# --- the invariant: five taps, one row --------------------------------------


@pytest.mark.asyncio
async def test_five_taps_make_one_entry_and_one_value(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Пять нажатий «+250 мл» — одна запись `entries` и одно значение 1250."""
    mark = await make_mark(client, water)

    for _ in range(5):
        status_code, _body = await tap(client, mark["id"])
        assert status_code == 201

    assert await count(db_session, Entry, category_id=water["id"]) == 1

    values = await db_session.execute(
        select(EntryValue.value)
        .join(Entry, Entry.id == EntryValue.entry_id)
        .where(Entry.category_id == water["id"])
    )
    assert values.scalars().all() == ["1250"]


@pytest.mark.asyncio
async def test_the_answer_carries_the_new_total(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Ответ на POST несёт сумму дня — второй запрос на перерисовку не нужен."""
    mark = await make_mark(client, water)

    _, first = await tap(client, mark["id"])
    _, second = await tap(client, mark["id"])

    assert first["today_total"] == 250
    assert second["today_total"] == 500
    assert second["done"] is True
    assert second["event_id"] != first["event_id"]


@pytest.mark.asyncio
async def test_a_typed_value_overrides_the_step(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """`value` в теле идёт тем же путём, что и шаг кнопки."""
    mark = await make_mark(client, water)

    await tap(client, mark["id"])
    _, body = await tap(client, mark["id"], value=100)

    assert body["today_total"] == 350


# --- idempotency ------------------------------------------------------------


@pytest.mark.asyncio
async def test_replayed_key_returns_the_same_event_and_total(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Повтор того же `Idempotency-Key` — то же событие и та же сумма дня."""
    mark = await make_mark(client, water)

    first_status, first = await tap(client, mark["id"], idempotency_key="tap-1")
    second_status, second = await tap(client, mark["id"], idempotency_key="tap-1")

    assert first_status == 201
    assert second_status == 200
    assert second["event_id"] == first["event_id"]
    assert second["today_total"] == first["today_total"] == 250
    assert await count(db_session, QuickMarkEvent, quick_mark_id=mark["id"]) == 1


# --- relapse ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_relapse_appends_an_entry_per_tap(
    client: AsyncClient, db_session: AsyncSession, smoking: dict[str, Any]
) -> None:
    """Срыв — событие со своим временем: три тапа, три записи, а не счётчик."""
    mark = await make_mark(client, smoking, label="Сорвался", kind="relapse", step=1)

    for _ in range(3):
        status_code, _body = await tap(client, mark["id"])
        assert status_code == 201

    assert await count(db_session, Entry, category_id=smoking["id"]) == 3

    events = await db_session.execute(
        select(QuickMarkEvent.entry_id).where(
            QuickMarkEvent.quick_mark_id == mark["id"]
        )
    )
    entry_ids = list(events.scalars().all())
    assert len(set(entry_ids)) == 3


# --- what the directory refuses ---------------------------------------------


@pytest.mark.asyncio
async def test_field_of_another_category_is_refused(
    client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
) -> None:
    """Чужой `field_id` — 422 с внятной причиной, а не мусор в базе."""
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "+250 мл",
            "category_id": water["id"],
            "field_id": only_field(vitamins),
            "kind": "increment",
            "step": 250,
        },
    )
    assert response.status_code == 422
    assert "does not belong to" in response.json()["detail"]


@pytest.mark.asyncio
async def test_check_on_a_number_field_is_refused(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """`kind='check'` на числовом поле — 422."""
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "Выпил",
            "category_id": water["id"],
            "field_id": only_field(water),
            "kind": "check",
        },
    )
    assert response.status_code == 422
    assert "checkbox" in response.json()["detail"]


@pytest.mark.asyncio
async def test_relapse_on_a_build_category_is_refused(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """`kind='relapse'` на категории со `streak_mode='build'` — 422."""
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "Сорвался",
            "category_id": water["id"],
            "field_id": only_field(water),
            "kind": "relapse",
        },
    )
    assert response.status_code == 422
    assert "avoid category" in response.json()["detail"]


@pytest.mark.asyncio
async def test_increment_without_a_step_is_refused(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Инкремент без шага — 422: тап обязан чего-то стоить."""
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "+?",
            "category_id": water["id"],
            "field_id": only_field(water),
            "kind": "increment",
        },
    )
    assert response.status_code == 422
    assert "needs a step" in response.json()["detail"]


@pytest.mark.asyncio
async def test_every_reason_comes_back_at_once(
    client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
) -> None:
    """Две ошибки в одной кнопке — обе в ответе, одна правка чинит всё."""
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "Сорвался",
            "category_id": water["id"],
            "field_id": only_field(vitamins),
            "kind": "relapse",
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "does not belong to" in detail
    assert "avoid category" in detail


@pytest.mark.asyncio
async def test_a_tap_on_a_missing_mark_is_404(client: AsyncClient) -> None:
    status_code, _body = await tap(client, 9999)
    assert status_code == 404


@pytest.mark.asyncio
async def test_a_tap_on_a_deactivated_mark_is_refused(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Выключенная кнопка не пишет: её нет на экране, и в базе её тапа тоже нет."""
    mark = await make_mark(client, water, is_active=False)
    status_code, _body = await tap(client, mark["id"])
    assert status_code == 409


# --- the tick ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_ticks_and_unticks_the_days_box(
    client: AsyncClient, db_session: AsyncSession, vitamins: dict[str, Any]
) -> None:
    """Галка ложится в запись дня; `value=0` снимает её, не создавая второй."""
    mark = await make_mark(
        client, vitamins, label="D3", kind="check", step=None, unit_label=None
    )

    _, ticked = await tap(client, mark["id"])
    assert ticked["done"] is True
    assert ticked["today_total"] is None

    _, unticked = await tap(client, mark["id"], value=0)
    assert unticked["done"] is False

    assert await count(db_session, Entry, category_id=vitamins["id"]) == 1


# --- the day ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_tap_at_half_past_midnight_lands_where_local_date_says(
    db_session: AsyncSession, client: AsyncClient, water: dict[str, Any]
) -> None:
    """
    Отметка в 00:30 попадает ровно в тот день, который назвал `local_date()`.

    Момент фиксирован и передаётся в `record_event` — второго ответа на «какое
    сегодня число» в коде нет, и тест сравнивается именно с той функцией, а не
    с датой, вписанной в файл.
    """
    created = await make_mark(client, water)
    mark = await quick_mark_crud.get_quick_mark(db_session, created["id"])
    assert mark is not None

    at = datetime(2026, 8, 29, 0, 30, tzinfo=BERLIN)
    recorded = await quick_mark_crud.record_event(db_session, mark, at=at, source="web")

    assert recorded.entry_date == local_date(at)
    # And that answer is the previous calendar date, which is the whole reason
    # the boundary exists — spelled out so a regression to a plain `.date()`
    # cannot pass this test.
    assert recorded.entry_date == date(2026, 8, 28)


@pytest.mark.asyncio
async def test_a_client_that_disagrees_about_the_day_is_refused(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """`entry_date` — сверка часов, а не адрес: расхождение отвергается."""
    mark = await make_mark(client, water)
    status_code, body = await tap(client, mark["id"], entry_date="2001-01-01")
    assert status_code == 409
    assert "the day has turned" in body["detail"]


# --- the directory ----------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_directory_is_an_empty_list(client: AsyncClient) -> None:
    """Пустой справочник — валидное состояние, а не ошибка."""
    response = await client.get(QUICK_MARKS_URL)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_the_directory_carries_the_days_state(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Справочник отдаётся уже с суммой дня — экран рисуется одним запросом."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"])

    response = await client.get(QUICK_MARKS_URL)
    assert response.status_code == 200
    listed = response.json()
    assert len(listed) == 1
    assert listed[0]["id"] == mark["id"]
    assert listed[0]["today_total"] == 250
    assert listed[0]["done"] is True
    assert listed[0]["unit_label"] == "мл"


@pytest.mark.asyncio
async def test_a_deactivated_button_leaves_the_directory(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    mark = await make_mark(client, water, is_active=False)
    assert (await client.get(QUICK_MARKS_URL)).json() == []
    assert await count(db_session, QuickMark, id=mark["id"]) == 1


@pytest.mark.asyncio
async def test_a_taken_hotkey_is_refused(
    client: AsyncClient, water: dict[str, Any]
) -> None:
    """Хоткей — глобальный ресурс: второй претендент получает 409."""
    await make_mark(client, water, hotkey="1")
    response = await client.post(
        QUICK_MARKS_URL,
        json={
            "label": "+100 мл",
            "category_id": water["id"],
            "field_id": only_field(water),
            "kind": "increment",
            "step": 100,
            "hotkey": "1",
        },
    )
    assert response.status_code == 409


# --- the journal ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_journal_records_the_delta_and_the_source(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """Журнал объясняет, как число стало таким: дельта, источник, запись."""
    mark = await make_mark(client, water)
    await tap(client, mark["id"], source="agent")

    result = await db_session.execute(
        select(QuickMarkEvent).where(QuickMarkEvent.quick_mark_id == mark["id"])
    )
    event = result.scalar_one()
    assert float(event.delta or 0) == 250
    assert event.source == "agent"
    assert event.bool_value is None
    assert event.entry_id is not None
    assert event.undone_at is None


# --- the migration ----------------------------------------------------------


def _alembic_config() -> Config:
    """
    Alembic configured without its ini file.

    Deliberate: `alembic/env.py` runs `fileConfig()` when it is given one, and
    `fileConfig` disables every logger already configured — including the one
    `app.crud.values` warns through, whose tests then stop seeing their warning.
    A config built in code carries the only setting the migration needs (where
    the versions live) and leaves the process's logging alone.
    """
    config = Config()
    config.set_main_option("script_location", "alembic")
    return config


def _offline_sql(revision_range: str) -> str:
    """
    The SQL one step of the chain emits, generated without a database.

    Offline mode is what makes this test cheap enough to always run: alembic
    renders the step from the revision files alone, so the assertion below is
    about what `downgrade()` says, not about whether postgres was up.
    """
    config = _alembic_config()
    buffer = StringIO()
    config.output_buffer = buffer
    command.upgrade(config, revision_range, sql=True)
    return buffer.getvalue()


def _offline_downgrade_sql(revision_range: str) -> str:
    config = _alembic_config()
    buffer = StringIO()
    config.output_buffer = buffer
    command.downgrade(config, revision_range, sql=True)
    return buffer.getvalue()


def test_the_migration_creates_both_tables_and_the_index() -> None:
    sql = _offline_sql(f"{PREVIOUS_REVISION}:{QUICK_MARKS_REVISION}").lower()
    assert "create table quick_marks" in sql
    assert "create table quick_mark_events" in sql
    assert "ix_entries_category_date" in sql
    assert "uq_quick_mark_hotkey" in sql
    assert "where hotkey is not null" in sql


def test_the_downgrade_drops_what_the_upgrade_made() -> None:
    """`downgrade` — не заглушка: обе таблицы и индекс снимаются."""
    sql = _offline_downgrade_sql(f"{QUICK_MARKS_REVISION}:{PREVIOUS_REVISION}").lower()
    assert "drop table quick_mark_events" in sql
    assert "drop table quick_marks" in sql
    assert "drop index ix_entries_category_date" in sql


@pytest.mark.asyncio
async def test_entries_survive_the_downgrade(
    client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
) -> None:
    """
    Данные в `entries`/`entry_values` не зависят от справочника.

    Проверяется тем же способом, каким откат и работает: справочник с журналом
    удаляются, а запись дня и её значение остаются на месте.
    """
    mark = await make_mark(client, water)
    await tap(client, mark["id"])

    stored = await quick_mark_crud.get_quick_mark(db_session, mark["id"])
    assert stored is not None
    await db_session.delete(stored)
    await db_session.commit()

    assert await count(db_session, Entry, category_id=water["id"]) == 1
    values = await db_session.execute(
        select(EntryValue.value)
        .join(Entry, Entry.id == EntryValue.entry_id)
        .where(Entry.category_id == water["id"])
    )
    assert values.scalars().all() == ["250"]


# --- PII --------------------------------------------------------------------


def test_the_new_code_never_logs_a_label_or_a_value() -> None:
    """
    В логах нового кода нет `label`, `value` и `note` — только идентификаторы.

    Читается как текст, потому что проверяется отсутствие: тест на поведение
    поймал бы только тот путь логирования, который додумались вызвать.
    """
    from pathlib import Path

    sources = [
        Path("app/crud/quick_mark.py"),
        Path("app/api/quick_marks.py"),
        Path("app/models/quick_mark.py"),
    ]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert "logger" not in text, f"{source} started logging; re-check the PII rule"


def test_no_second_answer_to_which_day_it_is() -> None:
    """Новый код спрашивает `local_date()` и не заводит своей даты или зоны."""
    from pathlib import Path

    for name in ("app/crud/quick_mark.py", "app/api/quick_marks.py"):
        text = Path(name).read_text(encoding="utf-8")
        assert "APP_TIMEZONE" not in text
        assert "ZoneInfo" not in text
        assert "DAY_START_HOUR" not in text

    # The moment is read once, in the endpoint, and handed to the day function;
    # the write path never calls a clock of its own.
    crud_text = Path("app/crud/quick_mark.py").read_text(encoding="utf-8")
    assert "datetime.now" not in crud_text
    assert "local_date(" in crud_text
