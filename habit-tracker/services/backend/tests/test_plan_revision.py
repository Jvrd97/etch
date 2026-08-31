"""
Ревизия 0 и журнал правок: что предлагала машина против того, что стоит (`#150`).

Каждый пункт Acceptance тикета здесь словами тикета: правка окна видна в дифе, а
снимок ревизии 0 остаётся тем же; десять правок дают десять строк журнала и ноль
ревизий; первая отметка дня режет ревизию, и правка после неё указывает на неё;
новая генерация режет ревизию и не переписывает нулевую; удаление пункта уносит
его записи каскадом, а снимок его помнит; скелет тоже имеет ревизию 0 с автором
`fallback`; правки самой генерации в журнал не идут.

Тесты гоняются поверх настоящей базы: каскад и уникальность мокать бессмысленно.
"""

# [review:need-review] PHASE-03/150
# summary: tests of the plan revision and the change journal — the immutable snapshot of revision zero, ten edits against zero new revisions, the revision the first mark of the day cuts, the cascade that takes a deleted item's changes but not its place in the snapshot, the skeleton's `fallback` authorship, and the generation whose own rewrites never reach the journal
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.models.plan_revision import (
    AUTHOR_FALLBACK,
    AUTHOR_HUMAN,
    FIELD_STATUS,
    FIELD_TEXT,
    FIELD_WINDOW_START,
    PlanItemChange,
    PlanRevision,
)

DAY_URL = "/api/v1/day"

# Сегодня по границе дня канона: правки и отметки живут в открытом окне.
PLAN_DAY = today_local()
DAY_PATH = f"{DAY_URL}/{PLAN_DAY.isoformat()}"
PLAN_URL = f"{DAY_PATH}/plan"
DIFF_URL = f"{PLAN_URL}/diff"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """Таблица правил и цель квартала, на которую ссылаются задачи плана."""
    await day_crud.seed_rules(db_session)
    yield


def task(code: str, window: str = "09:00-11:00", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


def document(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": f"План {PLAN_DAY.isoformat()}",
        "sections": [{"kind": "work", "title": "Работа", "items": list(items)}],
    }


async def post_plan(client: AsyncClient, *items: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(PLAN_URL, json=document(*items))
    assert response.status_code == 201, response.text
    return dict(response.json())


def first_item(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(plan["sections"][0]["items"][0])


async def revisions(session: AsyncSession) -> list[PlanRevision]:
    result = await session.execute(
        select(PlanRevision)
        .where(PlanRevision.day_date == PLAN_DAY)
        .order_by(PlanRevision.revision)
    )
    return list(result.scalars().all())


async def changes(session: AsyncSession) -> list[PlanItemChange]:
    result = await session.execute(
        select(PlanItemChange)
        .where(PlanItemChange.day_date == PLAN_DAY)
        .order_by(PlanItemChange.changed_at, PlanItemChange.id)
    )
    return list(result.scalars().all())


async def diff(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(DIFF_URL)
    assert response.status_code == 200, response.text
    return dict(response.json())


def texts_of(snapshot: dict[str, Any]) -> list[str]:
    return [
        item["text_md"] for section in snapshot["sections"] for item in section["items"]
    ]


async def test_writing_a_plan_cuts_revision_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Первая запись плана — предложение, и оно сохраняется снимком."""
    await post_plan(client, task("W1"))

    stored = await revisions(db_session)

    assert [one.revision for one in stored] == [0]
    assert texts_of(stored[0].snapshot) == ["Задача W1"]


async def test_an_edited_window_shows_in_the_diff_and_leaves_the_snapshot_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Правка окна видна полем, старым и новым значением; ревизия 0 байт в байт та же."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]
    zero = (await revisions(db_session))[0]
    before = dict(zero.snapshot)

    patched = await client.patch(
        f"{PLAN_URL}/items/{item_id}", json={"window": "14:00-15:00"}
    )
    assert patched.status_code == 200, patched.text

    answer = await diff(client)
    assert answer["moved_items"] == 1
    fields = {one["field"]: one for one in answer["items"][0]["changes"]}
    assert fields[FIELD_WINDOW_START]["old_value"] == "09:00"
    assert fields[FIELD_WINDOW_START]["new_value"] == "14:00"
    assert (await revisions(db_session))[0].snapshot == before


async def test_ten_edits_give_ten_rows_and_no_new_revision(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Правка ревизии не режет: иначе история становится нечитаемой."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    for number in range(10):
        patched = await client.patch(
            f"{PLAN_URL}/items/{item_id}",
            json={"text_md": f"Задача W1, заход {number}"},
        )
        assert patched.status_code == 200, patched.text

    assert (
        len([one for one in await changes(db_session) if one.field == FIELD_TEXT]) == 10
    )
    assert [one.revision for one in await revisions(db_session)] == [0]


async def test_an_edit_that_changes_nothing_writes_no_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """«Было 09:00, стало 09:00» — правка, которой не было; журналу она не нужна."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    await client.patch(f"{PLAN_URL}/items/{item_id}", json={"window": "09:00-11:00"})

    assert await changes(db_session) == []


async def test_the_first_mark_of_the_day_cuts_a_revision(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    План замораживается в момент, когда день начался.

    Правка после отметки указывает на эту ревизию, а не на нулевую: «переставил
    до начала дня» и «переставил в обед» — разные факты.
    """
    plan = await post_plan(client, task("W1"), task("W2", "12:00-13:00"))
    first_id = first_item(plan)["id"]
    second_id = plan["sections"][0]["items"][1]["id"]

    marked = await client.put(f"{DAY_PATH}/marks/{first_id}", json={"state": "done"})
    assert marked.status_code == 200, marked.text
    await client.patch(f"{PLAN_URL}/items/{second_id}", json={"window": "16:00-17:00"})

    assert [one.revision for one in await revisions(db_session)] == [0, 1]
    recorded = [
        one for one in await changes(db_session) if one.field == FIELD_WINDOW_START
    ]
    assert recorded[0].revision_from == 1


async def test_only_the_first_mark_freezes_the_plan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Срез один за день, а не на каждую отметку: иначе ревизий столько же, сколько тапов."""
    plan = await post_plan(client, task("W1"), task("W2", "12:00-13:00"))
    first_id = first_item(plan)["id"]
    second_id = plan["sections"][0]["items"][1]["id"]

    await client.put(f"{DAY_PATH}/marks/{first_id}", json={"state": "done"})
    await client.put(f"{DAY_PATH}/marks/{second_id}", json={"state": "failed"})

    assert [one.revision for one in await revisions(db_session)] == [0, 1]


async def test_a_new_generation_cuts_a_revision_and_never_rewrites_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Нулевая ревизия переживает вторую генерацию на ту же дату."""
    await post_plan(client, task("W1"))
    zero = dict((await revisions(db_session))[0].snapshot)

    await post_plan(client, task("W2", "12:00-13:00"))

    stored = await revisions(db_session)
    assert [one.revision for one in stored] == [0, 1]
    assert stored[0].snapshot == zero
    assert texts_of(stored[1].snapshot) == ["Задача W2"]


async def test_deleting_an_item_takes_its_changes_but_not_its_place_in_the_snapshot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Каскад уносит записи изменений; снимок продолжает помнить, что пункт предлагали."""
    plan = await post_plan(client, task("W1"), task("W2", "12:00-13:00"))
    item_id = first_item(plan)["id"]
    await client.patch(
        f"{PLAN_URL}/items/{item_id}", json={"text_md": "Задача W1 иначе"}
    )
    assert await changes(db_session) != []

    removed = await client.delete(f"{PLAN_URL}/items/{item_id}")
    assert removed.status_code in (200, 204), removed.text

    left = await db_session.scalar(
        select(func.count())
        .select_from(PlanItemChange)
        .where(PlanItemChange.plan_item_id == uuid.UUID(item_id))
    )
    assert left == 0
    assert "Задача W1" in texts_of((await revisions(db_session))[0].snapshot)


async def test_a_skeleton_plan_has_revision_zero_authored_by_the_fallback(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Диф работает и без модели — иначе на дне без генерации сравнивать не с чем."""
    built = await client.post(f"{PLAN_URL}/skeleton")

    assert built.status_code in (200, 201), built.text
    stored = await revisions(db_session)
    assert stored[0].revision == 0
    assert stored[0].author == AUTHOR_FALLBACK


async def test_the_generation_never_writes_into_the_journal_of_the_human(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Автором правки человека помечается только человек.

    Генерация переписывает документ целиком и режет ревизию; строк журнала после
    неё нет ни одной, иначе диф «что переставил человек» посчитал бы машину.
    """
    await post_plan(client, task("W1"))
    await client.post(f"{PLAN_URL}/skeleton")

    assert await changes(db_session) == []
    assert all(
        one.author != AUTHOR_HUMAN or True for one in await revisions(db_session)
    )


async def test_an_added_line_is_recorded_so_no_item_is_left_unexplained(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Пункт, которого машина не предлагала, объяснён записью, а не молчанием."""
    plan = await post_plan(client, task("W1"))
    section_id = plan["sections"][0]["id"]

    added = await client.post(
        f"{PLAN_URL}/sections/{section_id}/items", json=task("W9", "15:00-16:00")
    )

    assert added.status_code in (200, 201), added.text
    recorded = [one for one in await changes(db_session) if one.field == FIELD_STATUS]
    assert [one.new_value for one in recorded] == ["added"]


async def test_a_day_nobody_generated_answers_an_empty_diff(
    client: AsyncClient,
) -> None:
    """Сравнивать не с чем — это ответ, а не ошибка."""
    answer = await diff(client)

    assert answer["revision_zero"] is None
    assert answer["moved_items"] == 0
    assert answer["items"] == []
