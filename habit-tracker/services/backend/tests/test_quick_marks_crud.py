"""
Tests for managing the quick-mark directory from the interface, not from SQL.

The acceptance cases of `#125` that are about the directory itself: a taken
hotkey is refused by naming the button that holds it, deleting a button frees
its key, the validator of `#121` still guards an edit, the order survives a
re-read, and neither `is_active=false` nor an outright delete touches a single
row of `entries` or `entry_values`.
"""

# [review:need-review] PHASE-03/125
# summary: API tests for the directory editor — the 409 that names the holder of the key rather than the index that refused, the key freed by a delete, an edit judged as a whole button rather than as the fields it sent, the order renumbered by list, and the deletion that leaves the day's recorded values exactly where they were
from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, EntryValue
from app.models.quick_mark import QuickMarkEvent

QUICK_MARKS_URL = "/api/v1/quick-marks"


@pytest.fixture
async def water(client: AsyncClient) -> dict[str, Any]:
    """A form category with one number field — the «+250 мл» case."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Вода",
            "display_mode": "form",
            "fields": [{"name": "Объём", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def vitamins(client: AsyncClient) -> dict[str, Any]:
    """A checklist category with one boolean field."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Витамины",
            "display_mode": "checklist",
            "fields": [{"name": "D3", "field_type": "boolean", "order": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def only_field(category: dict[str, Any]) -> int:
    return int(category["fields"][0]["id"])


async def make_mark(
    client: AsyncClient, category: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    """A button over `category`'s first field; defaults for everything else."""
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


async def count(db: AsyncSession, table: Any) -> int:
    result = await db.execute(select(func.count()).select_from(table))
    return int(result.scalar_one())


class TestHotkeyConflict:
    """Клавиша — глобальный ресурс, и отказ обязан назвать того, кто её держит."""

    async def test_taking_a_key_that_another_button_holds_names_that_button(
        self, client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
    ) -> None:
        """
        Второй пункт Acceptance: видно, **какая** кнопка держит клавишу.

        «Нарушение уникальности» не чинится: по имени индекса человек не найдёт
        кнопку, а форму, которую он заполнил, за это время закроют.
        """
        holder = await make_mark(client, water, hotkey="1")

        response = await client.post(
            QUICK_MARKS_URL,
            json={
                "label": "D3",
                "category_id": vitamins["id"],
                "field_id": only_field(vitamins),
                "kind": "check",
                "hotkey": "1",
            },
        )

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["error"] == "hotkey_taken"
        assert detail["quick_mark_id"] == holder["id"]
        assert detail["label"] == holder["label"]
        assert detail["hotkey"] == "1"

    async def test_an_edit_onto_a_taken_key_is_refused_the_same_way(
        self, client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
    ) -> None:
        """Правка ходит тем же путём: отказ один, и он один и тот же."""
        holder = await make_mark(client, water, hotkey="1")
        other = await make_mark(client, vitamins, kind="check", step=None, hotkey="2")

        response = await client.patch(
            f"{QUICK_MARKS_URL}/{other['id']}", json={"hotkey": "1"}
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["quick_mark_id"] == holder["id"]

    async def test_a_button_may_keep_its_own_key(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """Кнопка не конфликтует сама с собой — иначе её нельзя переименовать."""
        mark = await make_mark(client, water, hotkey="1")

        response = await client.patch(
            f"{QUICK_MARKS_URL}/{mark['id']}", json={"label": "+300 мл", "hotkey": "1"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["label"] == "+300 мл"

    async def test_deleting_a_button_frees_its_key(
        self, client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
    ) -> None:
        """Третий пункт Acceptance: клавиша снова назначается."""
        holder = await make_mark(client, water, hotkey="1")

        deleted = await client.delete(f"{QUICK_MARKS_URL}/{holder['id']}")
        assert deleted.status_code == 204, deleted.text

        response = await client.post(
            QUICK_MARKS_URL,
            json={
                "label": "D3",
                "category_id": vitamins["id"],
                "field_id": only_field(vitamins),
                "kind": "check",
                "hotkey": "1",
            },
        )
        assert response.status_code == 201, response.text


class TestTheValidatorGuardsAnEdit:
    """Правка судится как кнопка целиком, а не как присланные поля."""

    async def test_taking_the_step_off_an_increment_is_refused(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Четвёртый пункт Acceptance: инкремент без шага не сохраняется.

        Один тап обязан чего-то стоить, иначе кнопка пишет ничто.
        """
        mark = await make_mark(client, water)

        response = await client.patch(
            f"{QUICK_MARKS_URL}/{mark['id']}", json={"step": None}
        )

        assert response.status_code == 422, response.text
        assert "needs a step" in response.json()["detail"]

    async def test_turning_a_number_button_into_a_tick_is_refused(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        `check` на числовом поле — та же ошибка, что и при создании.

        Патч трогает только `kind`, а невозможной становится пара, которую он
        не трогал: поэтому судится кнопка после правки, а не сама правка.
        """
        mark = await make_mark(client, water)

        response = await client.patch(
            f"{QUICK_MARKS_URL}/{mark['id']}", json={"kind": "check"}
        )

        assert response.status_code == 422, response.text
        assert "needs a checkbox" in response.json()["detail"]

    async def test_a_field_of_another_category_is_refused(
        self, client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
    ) -> None:
        """Поле чужой категории — кнопка, которая пишет неизвестно куда."""
        mark = await make_mark(client, water)

        response = await client.patch(
            f"{QUICK_MARKS_URL}/{mark['id']}",
            json={"field_id": only_field(vitamins)},
        )

        assert response.status_code == 422, response.text
        assert "does not belong to" in response.json()["detail"]

    async def test_editing_a_button_that_is_not_there_is_a_404(
        self, client: AsyncClient
    ) -> None:
        """Правка несуществующей кнопки — 404, а не тихое «готово»."""
        response = await client.patch(f"{QUICK_MARKS_URL}/999", json={"label": "нет"})
        assert response.status_code == 404


class TestOrder:
    """Порядок — свойство списка, и меняется он списком."""

    async def test_the_new_order_holds_after_a_re_read(
        self, client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
    ) -> None:
        """
        Пятый пункт Acceptance: порядок держится и совпадает с Today.

        Сравнивается с выдачей `GET /quick-marks` — той самой, которую рисует
        Today, а не со вторым чтением справочника.
        """
        first = await make_mark(client, water, order=0)
        second = await make_mark(client, vitamins, kind="check", step=None, order=1)

        moved = await client.patch(
            f"{QUICK_MARKS_URL}/order", json={"ids": [second["id"], first["id"]]}
        )
        assert moved.status_code == 200, moved.text
        assert [one["id"] for one in moved.json()] == [second["id"], first["id"]]

        today = await client.get(QUICK_MARKS_URL)
        assert [one["id"] for one in today.json()] == [second["id"], first["id"]]

    async def test_a_button_left_out_of_the_list_keeps_its_place_below(
        self, client: AsyncClient, water: dict[str, Any], vitamins: dict[str, Any]
    ) -> None:
        """
        Экран мог собрать порядок до того, как соседняя вкладка завела кнопку.

        Терять её из-за этого не за что: она уезжает под присланный список, а не
        из справочника.
        """
        first = await make_mark(client, water, order=0)
        second = await make_mark(client, vitamins, kind="check", step=None, order=1)

        moved = await client.patch(
            f"{QUICK_MARKS_URL}/order", json={"ids": [first["id"]]}
        )

        assert [one["id"] for one in moved.json()] == [first["id"], second["id"]]
        assert [one["order"] for one in moved.json()] == [0, 1]


class TestWhatDeletionDoesNotTouch:
    """Кнопка — про экран, а не про прожитый день."""

    async def test_deleting_a_button_leaves_every_recorded_value_in_place(
        self, client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
    ) -> None:
        """
        Предпоследний пункт Acceptance: ни одной строки `entries` не удаляется.

        Выпитая вода остаётся выпитой. Журнал тапов уезжает каскадом — он и есть
        журнал этой кнопки, и без неё отвечать ему не на что.
        """
        mark = await make_mark(client, water)
        tapped = await client.post(f"{QUICK_MARKS_URL}/{mark['id']}/events", json={})
        assert tapped.status_code == 201, tapped.text
        entries_before = await count(db_session, Entry)
        values_before = await count(db_session, EntryValue)
        assert entries_before == 1
        assert values_before == 1

        await client.delete(f"{QUICK_MARKS_URL}/{mark['id']}")

        assert await count(db_session, Entry) == entries_before
        assert await count(db_session, EntryValue) == values_before
        assert await count(db_session, QuickMarkEvent) == 0

    async def test_switching_a_button_off_takes_it_off_today_and_keeps_the_row(
        self, client: AsyncClient, db_session: AsyncSession, water: dict[str, Any]
    ) -> None:
        """
        Последний пункт Acceptance: `is_active=false` — не удаление.

        Кнопка уходит с экрана, значения и события остаются, и клавиша остаётся
        за ней: выключенная кнопка — это пауза, а не смерть.
        """
        mark = await make_mark(client, water, hotkey="1")
        await client.post(f"{QUICK_MARKS_URL}/{mark['id']}/events", json={})

        off = await client.patch(
            f"{QUICK_MARKS_URL}/{mark['id']}", json={"is_active": False}
        )
        assert off.status_code == 200, off.text

        today = await client.get(QUICK_MARKS_URL)
        assert today.json() == []
        assert await count(db_session, Entry) == 1
        assert await count(db_session, QuickMarkEvent) == 1

        with_inactive = await client.get(f"{QUICK_MARKS_URL}?active_only=false")
        assert [one["id"] for one in with_inactive.json()] == [mark["id"]]
