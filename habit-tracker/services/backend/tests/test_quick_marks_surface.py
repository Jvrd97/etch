"""
Tests for the contract the floating window of the agent reads: `surface`, `ETag`.

The acceptance cases of `#125` that belong to the polling client rather than to
the editor: `show_in_agent` taken off removes the button from the agent's list
and leaves it on Today, an unknown `surface` is a 422 rather than a full list,
one GET carries everything the window needs to draw a row, a repeated GET with
`If-None-Match` answers 304 without a body, one tap answers with the new state
so no second call is needed, and a request without the key is a 401 while
`API_KEY` is not empty.
"""

# [review:need-review] PHASE-03/125
# summary: API tests for the agent contract — one switch with two visible consequences, the 422 that refuses to guess a surface, the single GET that draws the row, the 304 that keeps polling cheap, the tap that repaints from its own answer, and the perimeter that still refuses an unkeyed request
from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import settings

QUICK_MARKS_URL = "/api/v1/quick-marks"


@pytest.fixture
async def water(client: AsyncClient) -> dict[str, Any]:
    """A form category with one number field."""
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


async def make_mark(
    client: AsyncClient, category: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    """A button over `category`'s first field."""
    payload: dict[str, Any] = {
        "label": "+250 мл",
        "category_id": category["id"],
        "field_id": int(category["fields"][0]["id"]),
        "kind": "increment",
        "step": 250,
        "unit_label": "мл",
    }
    payload.update(overrides)
    response = await client.post(QUICK_MARKS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestSurface:
    """Один переключатель, два видимых следствия — и ни одной догадки."""

    async def test_taking_show_in_agent_off_hides_the_button_from_the_window_only(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Шестой пункт Acceptance: кнопка ушла из окна и осталась на Today.

        В окне помещается пять-шесть кнопок, в справочнике их будет больше, и
        это единственный способ развести «всегда под рукой» и «раз в день».
        """
        mark = await make_mark(client, water)

        off = await client.patch(
            f"{QUICK_MARKS_URL}/{mark['id']}", json={"show_in_agent": False}
        )
        assert off.status_code == 200, off.text

        agent = await client.get(f"{QUICK_MARKS_URL}?surface=agent")
        web = await client.get(f"{QUICK_MARKS_URL}?surface=web")

        assert agent.json() == []
        assert [one["id"] for one in web.json()] == [mark["id"]]

    async def test_an_unknown_surface_is_refused_rather_than_guessed(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Восьмой пункт Acceptance: 422, а не полный список.

        Опечатка в клиенте, которая молча отдаёт всё, выглядит как рабочее
        поведение и находится через месяц — по жалобе «в окне лишние кнопки».
        """
        await make_mark(client, water)

        response = await client.get(f"{QUICK_MARKS_URL}?surface=agnet")

        assert response.status_code == 422, response.text
        assert "unknown surface" in response.json()["detail"]

    async def test_one_get_carries_everything_the_window_draws(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Седьмой пункт Acceptance: подпись, сумма дня и «сделано» одним запросом.

        Окну не нужен второй вызов, чтобы понять, что рисовать, — иначе поллинг
        стоил бы вдвое и половину времени показывал бы рассогласованное.
        """
        mark = await make_mark(client, water, icon="droplet", color="#4aa3ff")
        await client.post(f"{QUICK_MARKS_URL}/{mark['id']}/events", json={})

        response = await client.get(f"{QUICK_MARKS_URL}?surface=agent")

        drawn = response.json()[0]
        for field in ("label", "icon", "color", "step", "unit_label", "done"):
            assert field in drawn
        assert drawn["today_total"] == 250
        assert drawn["done"] is True


class TestPollingIsCheap:
    """Опрос каждые несколько секунд не имеет права качать тело."""

    async def test_a_repeated_get_without_changes_answers_304(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """Десятый пункт Acceptance: `If-None-Match` совпал — тела нет."""
        await make_mark(client, water)
        first = await client.get(f"{QUICK_MARKS_URL}?surface=agent")
        tag = first.headers["ETag"]

        second = await client.get(
            f"{QUICK_MARKS_URL}?surface=agent", headers={"If-None-Match": tag}
        )

        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["ETag"] == tag

    async def test_a_tap_changes_the_tag(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Отпечаток берётся с выдачи целиком, а не с `updated_at` справочника.

        Чужой тап меняет сумму дня, не трогая строку кнопки; отпечаток по
        `updated_at` отдал бы на это 304 — то есть окно врало бы ровно про то,
        ради чего его открыли.
        """
        mark = await make_mark(client, water)
        before = (await client.get(f"{QUICK_MARKS_URL}?surface=agent")).headers["ETag"]

        await client.post(f"{QUICK_MARKS_URL}/{mark['id']}/events", json={})

        after = await client.get(
            f"{QUICK_MARKS_URL}?surface=agent", headers={"If-None-Match": before}
        )
        assert after.status_code == 200
        assert after.headers["ETag"] != before

    async def test_a_tap_answers_with_the_state_it_produced(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Девятый пункт Acceptance: второго запроса для перерисовки не требуется.

        Проверяется телом ответа, а не числом сетевых вызовов: тест и есть тот
        единственный вызов, и всё, что нужно ряду, лежит уже в нём.
        """
        mark = await make_mark(client, water)

        tapped = await client.post(
            f"{QUICK_MARKS_URL}/{mark['id']}/events", json={"source": "agent"}
        )

        assert tapped.status_code == 201, tapped.text
        body = tapped.json()
        assert body["today_total"] == 250
        assert body["done"] is True
        assert body["quick_mark_id"] == mark["id"]


class TestThePerimeterStillHolds:
    """Окно ходит по сети внутри tailnet, и ключ — единственная граница."""

    async def test_a_request_without_the_key_is_refused(
        self, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        """
        Одиннадцатый пункт Acceptance: 401 при непустом `API_KEY`.

        Риск пустого ключа (`core/auth.py` тогда выключает проверку целиком)
        назван в `docs/quick-marks-agent-contract.md` как принятый: здесь
        проверяется, что при непустом ключе граница на месте.
        """
        assert settings.API_KEY
        await make_mark(client, water)

        response = await client.get(QUICK_MARKS_URL, headers={"X-API-Key": ""})

        assert response.status_code == 401
