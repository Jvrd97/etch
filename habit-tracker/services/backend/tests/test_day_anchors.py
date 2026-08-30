"""
Якоря дня как строки справочника, а не как буллеты, узнанные по подстроке.

До `#92` якорь был пунктом плана, чей текст содержал «якор», и вердикт дня
считался по этому узнаванию: план, сформулировавший якорь другими словами, терял
его молча. Здесь якорь — строка `day_anchor` с `UNIQUE(day_date, kind)`, состав
приходит из `day_rule_set.anchors`, а вид — из каталога `anchor_kind`.

Отдельная тема того же тикета — `relationship`. Приоритет «здоровье > работа >
отношения» до этого среза был выражен на две трети: у здоровья были якоря улицы
и силового, у работы потолок и стоп, у отношений не было ничего. Здесь у него
есть строка справочника, он виден на странице дня, отмечается и после отметки
попадает в вердикт наравне с первыми двумя.
"""

# [review:need-review] PHASE-03/92
# summary: API tests for the anchors of a day — the catalogue answers with `relationship` beside the edges of the day, a mark lands and reaches the verdict, a second anchor of the same kind is refused by the database, an unknown kind is a 422, and a day whose anchors say nothing falls back to the anchor lines of the plan
import uuid
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import anchor as anchor_crud
from app.crud import day as day_crud
from app.day.evaluate import REASON_ANCHORS, VERDICT_LOST, VERDICT_WON
from app.models.anchor import ANCHOR_RELATIONSHIP, AnchorKind, DayAnchor

DAY_URL = "/api/v1/day"

# A Monday under the current canon — the row that names all six anchors.
ANCHOR_DAY = date(2026, 8, 24)
ANCHOR_PATH = f"{DAY_URL}/{ANCHOR_DAY.isoformat()}"

# Every anchor the current canon names, so a day can be closed cleanly.
ALL_KINDS = ("подъём", "спорт", "старт работы", "ревью", "отбой", ANCHOR_RELATIONSHIP)


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The rule rows and the catalogue of anchor kinds they name."""
    await day_crud.seed_rules(db_session)
    yield


async def anchors_of(client: AsyncClient, on: date = ANCHOR_DAY) -> dict[str, Any]:
    response = await client.get(f"{DAY_URL}/{on.isoformat()}/anchors")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def mark_anchor(
    client: AsyncClient, kind: str, state: str | None, on: date = ANCHOR_DAY
) -> dict[str, Any]:
    response = await client.put(
        f"{DAY_URL}/{on.isoformat()}/anchors",
        json={"anchors": [{"kind": kind, "state": state}]},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_the_day_answers_with_every_kind_of_the_catalogue(
    client: AsyncClient,
) -> None:
    # «Вечера с близкими сегодня не было» обязано отличаться от «про вечер с
    # близкими не спрашивали»: вид приезжает даже без строки.
    payload = await anchors_of(client)

    kinds = [one["kind"] for one in payload["anchors"]]
    assert kinds == list(ALL_KINDS)
    assert all(one["state"] is None for one in payload["anchors"])


async def test_the_relationship_anchor_is_in_the_catalogue_and_named_in_russian(
    client: AsyncClient,
) -> None:
    payload = await anchors_of(client)

    family = next(
        one for one in payload["anchors"] if one["kind"] == ANCHOR_RELATIONSHIP
    )
    assert family["title"] == "вечер с близкими"
    assert family["required_in_nonwork_evening"] is True
    assert family["required_today"] is True


async def test_marking_the_relationship_anchor_lands(client: AsyncClient) -> None:
    payload = await mark_anchor(client, ANCHOR_RELATIONSHIP, "done")

    family = next(
        one for one in payload["anchors"] if one["kind"] == ANCHOR_RELATIONSHIP
    )
    assert family["state"] == "done"
    assert "вечер с близкими" not in payload["missing"]


async def test_the_day_screen_carries_the_anchors(client: AsyncClient) -> None:
    await mark_anchor(client, "подъём", "done")

    response = await client.get(ANCHOR_PATH)
    assert response.status_code == 200, response.text
    block = response.json()["anchors"]

    assert block["total"] == len(ALL_KINDS)
    assert block["done"] == 1


async def test_a_day_closed_without_the_family_evening_is_lost_on_anchors(
    client: AsyncClient,
) -> None:
    # Приёмка: после отметки якорь виден вердикту `#90`. Пять из шести закрыты,
    # шестой — «вечер с близкими» — нет, и день снимается по `anchors`.
    for kind in ALL_KINDS[:-1]:
        await mark_anchor(client, kind, "done")

    response = await client.post(f"{ANCHOR_PATH}/close", json={})
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["verdict"] == VERDICT_LOST
    assert summary["verdict_reason"] == REASON_ANCHORS
    assert summary["missing_anchors"] == ["вечер с близкими"]


async def test_closing_the_family_evening_wins_the_day(client: AsyncClient) -> None:
    for kind in ALL_KINDS:
        await mark_anchor(client, kind, "done")

    response = await client.post(f"{ANCHOR_PATH}/close", json={})
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["verdict"] == VERDICT_WON
    assert summary["anchors_done"] == len(ALL_KINDS)
    assert summary["missing_anchors"] == []


async def test_a_skipped_anchor_does_not_lower_the_day(client: AsyncClient) -> None:
    for kind in ALL_KINDS[:-1]:
        await mark_anchor(client, kind, "done")
    await mark_anchor(client, ANCHOR_RELATIONSHIP, "skipped")

    response = await client.post(f"{ANCHOR_PATH}/close", json={})
    assert response.json()["verdict"] == VERDICT_WON


async def test_a_second_anchor_of_the_same_kind_is_refused_by_the_database(
    db_session: AsyncSession,
) -> None:
    # Приёмка тикета. Проверяется базой, а не сервисом: сервисную проверку
    # обходят импорт, миграция и сессия psql, и «два подъёма 30-го» появились бы
    # именно оттуда.
    await day_crud.ensure_day(db_session, ANCHOR_DAY)
    await anchor_crud.set_anchor(
        db_session, ANCHOR_DAY, "подъём", state="done", note=None
    )

    with pytest.raises(IntegrityError):
        await db_session.execute(
            insert(DayAnchor).values(
                id=uuid.uuid4(),
                day_date=ANCHOR_DAY,
                kind="подъём",
                state="failed",
            )
        )
    await db_session.rollback()


async def test_marking_the_same_anchor_twice_replaces_the_state(
    client: AsyncClient,
) -> None:
    await mark_anchor(client, "подъём", "done")
    payload = await mark_anchor(client, "подъём", "failed")

    wake = next(one for one in payload["anchors"] if one["kind"] == "подъём")
    assert wake["state"] == "failed"


async def test_taking_the_mark_off_returns_the_anchor_to_unanswered(
    client: AsyncClient,
) -> None:
    await mark_anchor(client, "подъём", "done")
    payload = await mark_anchor(client, "подъём", None)

    wake = next(one for one in payload["anchors"] if one["kind"] == "подъём")
    assert wake["state"] is None


async def test_an_unknown_kind_of_anchor_is_refused(client: AsyncClient) -> None:
    response = await client.put(
        f"{ANCHOR_PATH}/anchors",
        json={"anchors": [{"kind": "медитация", "state": "done"}]},
    )

    assert response.status_code == 422
    assert "anchor_kind" in response.json()["detail"]


async def test_an_unknown_state_is_refused(client: AsyncClient) -> None:
    response = await client.put(
        f"{ANCHOR_PATH}/anchors",
        json={"anchors": [{"kind": "подъём", "state": "почти"}]},
    )

    assert response.status_code == 422


async def test_the_composition_changes_by_an_insert_and_a_rule_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Приёмка тикета: ни один вид якоря не зашит в код. Новый вид — строка
    # каталога плюс правка состава в правиле, и день начинает судиться по нему.
    db_session.add(
        AnchorKind(
            code="медитация",
            title="медитация",
            ord=7,
            counts_for_verdict=True,
            required_in_nonwork_evening=False,
        )
    )
    rules = await day_crud.list_rules(db_session)
    current = max(rules, key=lambda rule: rule.valid_from)
    current.anchors = [*ALL_KINDS, "медитация"]
    await db_session.flush()

    payload = await anchors_of(client)

    assert "медитация" in [one["kind"] for one in payload["anchors"]]
    assert payload["total"] == len(ALL_KINDS) + 1


async def test_a_kind_outside_this_canon_is_shown_but_not_required(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Канон до 2026-08-17 называет пять видов, каталог держит шесть: «вечер с
    # близкими» виден и в тот день, но днём июля не судится.
    legacy = date(2026, 8, 10)
    response = await client.get(f"{DAY_URL}/{legacy.isoformat()}/anchors")
    assert response.status_code == 200, response.text
    payload = response.json()

    family = next(
        one for one in payload["anchors"] if one["kind"] == ANCHOR_RELATIONSHIP
    )
    assert family["required_today"] is False
    assert payload["total"] == len(ALL_KINDS) - 1


async def test_a_plan_links_its_anchor_lines_to_the_anchors_of_the_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Пункт плана и якорь показывают друг на друга: `code` строки — это вид
    # якоря, тот же словарь, что у `day_rule_set.anchors`.
    response = await client.post(
        f"{ANCHOR_PATH}/plan",
        json={
            "sections": [
                {
                    "kind": "anchors",
                    "title": "Якоря",
                    "items": [
                        {"kind": "anchor", "code": "подъём", "text_md": "подъём 6:00"}
                    ],
                }
            ]
        },
    )
    assert response.status_code == 201, response.text

    result = await db_session.execute(
        select(DayAnchor).where(
            DayAnchor.day_date == ANCHOR_DAY, DayAnchor.kind == "подъём"
        )
    )
    stored = result.scalar_one()
    assert stored.item_id is not None
    # Переписанный план не ставит и не снимает отметку.
    assert stored.state is None
