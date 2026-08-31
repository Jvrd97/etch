# [review:need-review] PHASE-03/147
# summary: the skeleton against the rules it is built from — clean on both seeded rows, edges and training slot and carryovers where the canon puts them, the free block left empty, the evening with the family on a day off — and the endpoint that writes it: the plan appears, the neighbour dates are byte-identical before and after, and a person's edit that breaks a rule is stored with a `warn` beside it
"""
The deterministic plan, and the ticket's two strongest claims.

**"Passes `check_all` by construction" is asserted, not described.** The
skeleton is built from the same rule row the eight rules read, so the claim is
supposed to hold for any row — including one whose start of work or ceiling has
moved. The test therefore runs it against both seeded rows and against a row
with the edges shifted, rather than against the one it was written on.

**"Does not touch the neighbours" is a snapshot, not an inspection.** The plans
of `date-1` and `date+1` are read whole before and after the call and compared
as values. A test that only counted rows would pass on a generator that
rewrote yesterday's window.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date, time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import plan_violation as violation_crud
from app.day import constraints, skeleton
from app.day.rules import SEED_RULES
from app.models.plan_violation import ORIGINS as MODEL_ORIGINS
from app.models.plan_violation import RULE_CODES as MODEL_RULE_CODES
from app.models.plan_violation import SEVERITIES as MODEL_SEVERITIES
from app.models.plan_violation import PlanViolation

from tests.test_day_constraints import DAY_OFF, WORKDAY, rule

DAY_URL = "/api/v1/day"


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it; `create_all` has no seed.

    Autouse because the endpoint answers 404 for a date no rule covers, and
    that answer is correct: a day nothing describes must not be judged by an
    invented canon.
    """
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


# --- the claim the whole ticket stands on ------------------------------------


def test_the_skeleton_breaks_no_rule_on_the_current_canon() -> None:
    built = skeleton.skeleton_plan(WORKDAY, rule())

    assert constraints.check_all(built.draft, rule()) == []


def test_the_skeleton_breaks_no_rule_on_the_legacy_canon() -> None:
    """
    Скелет проходит `check_all` и на действующем правиле, и на `legacy`.

    Обе строки, потому что утверждение «по построению» — про строку правила
    вообще, а не про ту, на которой скелет писали.
    """
    legacy_seed = SEED_RULES[0]
    legacy = rule(
        work_cap_min=legacy_seed.work_cap_min,
        work_hard_cap_min=legacy_seed.work_hard_cap_min,
        max_work_tasks=legacy_seed.max_work_tasks,
        max_study_items=legacy_seed.max_study_items,
        relationship_anchor_required=legacy_seed.relationship_anchor_required,
        anchors=list(legacy_seed.anchors),
    )

    for target in (WORKDAY, DAY_OFF):
        built = skeleton.skeleton_plan(target, legacy)
        assert constraints.check_all(built.draft, legacy) == [], target


def test_the_skeleton_follows_a_canon_whose_edges_moved() -> None:
    """
    Числа берутся из строки, а не из модуля.

    Правило со сдвинутыми краями — самый дешёвый способ доказать это: скелет,
    зашивший 7:45, сломался бы здесь, а не через месяц на живом дне.
    """
    moved = rule(
        wake_at=time(5, 30),
        work_start=time(9, 0),
        review_at=time(17, 0),
        bedtime_max=time(23, 0),
        free_evening_start=time(20, 0),
        free_evening_end=time(22, 0),
        work_stop_at=time(18, 0),
    )

    built = skeleton.skeleton_plan(WORKDAY, moved)

    assert constraints.check_all(built.draft, moved) == []
    starts = {item.code: item.starts_at for item in built.draft.items}
    assert starts["старт работы"] is not None
    assert starts["старт работы"].astimezone().hour == 9


# --- what the skeleton is made of --------------------------------------------


def test_the_edges_of_the_day_are_the_edges_of_the_canon() -> None:
    canon = rule()
    built = skeleton.skeleton_plan(WORKDAY, canon)

    hard = {
        item.code
        for item in built.draft.items
        if item.rigidity == "hard" and item.code is not None
    }
    assert hard == {"подъём", "старт работы", "ревью", "отбой"}


def test_the_training_slot_ends_where_work_begins() -> None:
    canon = rule()
    built = skeleton.skeleton_plan(WORKDAY, canon)

    sport = next(item for item in built.draft.items if item.code == "спорт")
    work_start = next(item for item in built.draft.items if item.code == "старт работы")
    assert sport.ends_at == work_start.starts_at


def test_a_day_off_carries_the_evening_with_the_family() -> None:
    built = skeleton.skeleton_plan(DAY_OFF, rule())

    assert any(item.code == "relationship" for item in built.draft.items)


def test_a_working_day_does_not_carry_it() -> None:
    built = skeleton.skeleton_plan(WORKDAY, rule())

    assert not any(item.code == "relationship" for item in built.draft.items)


def test_the_free_block_stays_empty() -> None:
    built = skeleton.skeleton_plan(WORKDAY, rule())

    free = next(
        section for section in built.sections if section.kind == skeleton.SECTION_FREE
    )
    assert free.items == ()


# --- the carryovers ----------------------------------------------------------


def carry(text: str, priority: int, minutes: int = 60) -> skeleton.Carryover:
    return skeleton.Carryover(text_md=text, priority=priority, minutes=minutes)


def test_carryovers_are_placed_in_the_order_the_caller_ranked_them() -> None:
    canon = rule()
    built = skeleton.skeleton_plan(
        WORKDAY, canon, (carry("второе", 2), carry("первое", 1))
    )

    work = next(
        section for section in built.sections if section.kind == skeleton.SECTION_WORK
    )
    assert work.texts == ("первое", "второе")


def test_what_does_not_fit_under_the_bar_is_reported_rather_than_squeezed_in() -> None:
    """Что не влезло — не впихивается: список режется, а остаток виден."""
    canon = rule()
    queue = tuple(carry(f"задача {n}", n) for n in range(1, canon.max_work_tasks + 3))

    built = skeleton.skeleton_plan(WORKDAY, canon, queue)

    tasks = [item for item in built.draft.items if item.kind == "task"]
    assert len(tasks) == canon.max_work_tasks
    assert len(built.overflow) == 2
    assert constraints.check_all(built.draft, canon) == []


def test_nothing_is_scheduled_past_the_canon_stop() -> None:
    canon = rule()
    long_queue = tuple(carry(f"задача {n}", n, minutes=600) for n in range(1, 4))

    built = skeleton.skeleton_plan(WORKDAY, canon, long_queue)

    assert [item for item in built.draft.items if item.kind == "task"] == []
    assert len(built.overflow) == 3


def test_a_day_without_training_leaves_the_slot_out() -> None:
    built = skeleton.skeleton_plan(
        WORKDAY, rule(), signals=skeleton.Signals(is_training_day=False)
    )

    assert not any(item.code == "спорт" for item in built.draft.items)


# --- the three spellings of the vocabularies agree ---------------------------


def test_the_model_and_the_module_name_the_same_rules() -> None:
    """
    Три написания словаря обязаны совпадать.

    Модуль, модель и миграция пишут коды правил каждый у себя — модель не может
    импортировать `constraints` (цикл), а миграция не имеет права зависеть от
    кода приложения. Тест — то, что держит три списка вместе.
    """
    assert MODEL_RULE_CODES == constraints.RULE_CODES
    assert MODEL_SEVERITIES == constraints.SEVERITIES
    assert MODEL_ORIGINS == constraints.ORIGINS


# --- the endpoint ------------------------------------------------------------


async def snapshot(client: AsyncClient, on: date) -> dict[str, Any]:
    """The whole day as the API answers it — the value a neighbour is compared by."""
    response = await client.get(f"{DAY_URL}/{on.isoformat()}")
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.mark.asyncio
async def test_the_endpoint_writes_a_plan_with_edges_and_an_empty_evening(
    client: AsyncClient,
) -> None:
    """
    `POST .../plan/skeleton` даёт план с жёсткими краями и пустым вечером.

    Тренировочный слот и переносы там же; свободный вечерний блок существует и
    пуст — это разные вещи, и вторая проверяется отдельно.
    """
    response = await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan/skeleton")

    assert response.status_code == 201, response.text
    body = response.json()
    sections = {section["kind"]: section for section in body["sections"]}

    hard_codes = {
        item["code"]
        for item in sections["anchors"]["items"]
        if item["rigidity"] == "hard"
    }
    assert hard_codes == {"подъём", "старт работы", "ревью", "отбой"}
    assert sections["training"]["items"]
    assert sections["free"]["items"] == []


@pytest.mark.asyncio
async def test_the_skeleton_does_not_touch_the_neighbour_dates(
    client: AsyncClient,
) -> None:
    """
    Снимок соседних дат до и после вызова совпадает.

    Машинная форма правила «сегодня сорвалось — неделю не трогаем»: генерация
    физически пишет строки только на целевую дату.
    """
    before = WORKDAY - timedelta(days=1)
    after = WORKDAY + timedelta(days=1)
    # Both neighbours get a plan of their own first, so the comparison is between
    # two plans rather than between two absences.
    for neighbour in (before, after):
        assert (
            await client.post(f"{DAY_URL}/{neighbour.isoformat()}/plan/skeleton")
        ).status_code == 201

    was = {day: await snapshot(client, day) for day in (before, after)}

    assert (
        await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan/skeleton")
    ).status_code == 201

    now = {day: await snapshot(client, day) for day in (before, after)}
    assert now == was


@pytest.mark.asyncio
async def test_calling_it_twice_replaces_rather_than_doubles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for _ in range(2):
        assert (
            await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan/skeleton")
        ).status_code == 201

    body = (await snapshot(client, WORKDAY))["plan"]
    kinds = [section["kind"] for section in body["sections"]]
    assert len(kinds) == len(set(kinds))

    left = await db_session.execute(
        select(func.count())
        .select_from(PlanViolation)
        .where(PlanViolation.day_date == WORKDAY)
    )
    # A skeleton that broke nothing leaves nothing behind to explain.
    assert left.scalar_one() == 0


@pytest.mark.asyncio
async def test_a_persons_edit_into_the_free_evening_is_stored_with_a_warn_beside_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Машине нарушение блокирует запись, человеку — нет.

    Правка, ставящая рабочую задачу в свободный вечер, проходит там, где база
    это позволяет, и создаёт `plan_violation` со `severity='warn'` и
    `origin='human'`.
    """
    canon = rule()
    evening = canon.free_evening_start.strftime("%H:%M")
    document = {
        "title": "правка руками",
        "sections": [
            {
                "title": "Работа",
                "kind": "work",
                "items": [
                    {
                        "kind": "task",
                        "text_md": "дописать разбор",
                        "window": f"{evening}-20:10",
                        "done_criterion": "разбор дописан",
                        "unlinked_reason": "личное",
                    }
                ],
            }
        ],
    }

    response = await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan", json=document)

    # Stored, not refused: a person edits their own day freely.
    assert response.status_code == 201, response.text

    rows = await violation_crud.list_violations(db_session, WORKDAY)
    by_code = {row.rule_code: row for row in rows}
    assert constraints.RULE_FREE_EVENING_EMPTY in by_code
    warn = by_code[constraints.RULE_FREE_EVENING_EMPTY]
    assert warn.severity == constraints.SEVERITY_WARN
    assert warn.origin == constraints.ORIGIN_HUMAN
    # Ids and numbers only: the row outlives the plan it describes.
    assert "дописать разбор" not in repr(warn.detail)


@pytest.mark.asyncio
async def test_the_violations_of_a_day_are_readable(client: AsyncClient) -> None:
    canon = rule()
    evening = canon.free_evening_start.strftime("%H:%M")
    await client.post(
        f"{DAY_URL}/{WORKDAY.isoformat()}/plan",
        json={
            "sections": [
                {
                    "kind": "work",
                    "items": [
                        {
                            "kind": "task",
                            "text_md": "вечерняя задача",
                            "window": f"{evening}-20:10",
                            "done_criterion": "сделано",
                            "unlinked_reason": "личное",
                        }
                    ],
                }
            ]
        },
    )

    response = await client.get(f"{DAY_URL}/{WORKDAY.isoformat()}/plan/violations")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload
    assert {row["severity"] for row in payload} == {constraints.SEVERITY_WARN}
    assert all("text" not in row for row in payload)


@pytest.mark.asyncio
async def test_a_second_edit_replaces_the_previous_answer_rather_than_adding_to_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Перечитать день дважды — не то же, что нарушить правило дважды."""
    canon = rule()
    evening = canon.free_evening_start.strftime("%H:%M")
    document = {
        "sections": [
            {
                "kind": "work",
                "items": [
                    {
                        "kind": "task",
                        "text_md": "вечерняя задача",
                        "window": f"{evening}-20:10",
                        "done_criterion": "сделано",
                        "unlinked_reason": "личное",
                    }
                ],
            }
        ]
    }

    for _ in range(3):
        assert (
            await client.post(f"{DAY_URL}/{WORKDAY.isoformat()}/plan", json=document)
        ).status_code == 201

    rows = await violation_crud.list_violations(db_session, WORKDAY)
    free_evening = [
        row for row in rows if row.rule_code == constraints.RULE_FREE_EVENING_EMPTY
    ]
    assert len(free_evening) == 1
