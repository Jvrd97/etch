# [review:need-review] PHASE-03/140
# summary: tests of the plan as a source of roles — a tick on an item that names an act closes the act without a visit to `/roles`, «не сделал» closes nothing, un-ticking takes the act back unless a person confirmed it, a second tick does not double it, an item naming no act is an ordinary item, a section's windows charge minutes that displace the agent's for the same hours, and the act opens up to the line of the plan it came from
"""
Tests of the two connections `#140` adds between the plan and the roles.

The interval arithmetic underneath them is pure and lives in
`test_role_precedence.py`. What is checked here is everything that needs the
plan, the marks and the role tables at once.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import role as role_crud
from app.models.plan import PlanItem, PlanSection
from app.models.role import (
    CONFIDENCE_CONFIRMED,
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_TECHLEAD,
    SOURCE_APP_USAGE,
    SOURCE_PLAN,
    RoleAct,
    RoleTimeBlock,
)

DAY_URL = "/api/v1/day"
ROLES_URL = "/api/v1/roles"
ACTS_URL = "/api/v1/role-acts"

PLAN_DAY = today_local()
DAY_PATH = f"{DAY_URL}/{PLAN_DAY.isoformat()}"
PLAN_URL = f"{DAY_PATH}/plan"

ACT_KIND = "data_model_decision"


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The day canon and the four roles, neither of which `create_all` seeds."""
    await day_crud.seed_rules(db_session)
    await role_crud.seed_roles(db_session)
    await db_session.commit()
    yield


async def role_id(db_session: AsyncSession, code: str) -> int:
    role = await role_crud.get_role_by_code(db_session, code)
    assert role is not None
    return role.id


def task(code: str, window: str = "11:00-12:00", **overrides: Any) -> dict[str, Any]:
    """A task that satisfies every row-level rule of `#87`."""
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "решение записано",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


def document(*items: dict[str, Any], section_role: int | None = None) -> dict[str, Any]:
    """A plan of one work section holding `items`."""
    section: dict[str, Any] = {
        "kind": "work",
        "title": "Работа",
        "items": list(items),
    }
    if section_role is not None:
        section["role_id"] = section_role
    return {"title": f"План {PLAN_DAY.isoformat()}", "sections": [section]}


async def post_plan(client: AsyncClient, plan: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(PLAN_URL, json=plan)
    assert response.status_code == 201, response.text
    return dict(response.json())


def first_item(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(plan["sections"][0]["items"][0])


async def put_mark(client: AsyncClient, item_id: str, state: str | None) -> None:
    response = await client.put(f"{DAY_PATH}/marks/{item_id}", json={"state": state})
    assert response.status_code == 200, response.text


async def day_acts(db_session: AsyncSession) -> list[RoleAct]:
    return list(
        (
            await db_session.execute(
                select(RoleAct).where(RoleAct.work_day == PLAN_DAY).order_by(RoleAct.id)
            )
        )
        .scalars()
        .all()
    )


async def day_blocks(db_session: AsyncSession) -> list[RoleTimeBlock]:
    return list(
        (
            await db_session.execute(
                select(RoleTimeBlock)
                .where(RoleTimeBlock.work_day == PLAN_DAY)
                .order_by(RoleTimeBlock.id)
            )
        )
        .scalars()
        .all()
    )


def moment(hour: int, minute: int = 0) -> datetime:
    """
    A moment of the plan day on the wall clock the windows are written in.

    Built in the canon's zone rather than in UTC: `"10:00-12:00"` in a plan is
    ten o'clock where the day is lived, and comparing it against a UTC literal
    would make these tests pass only in winter.
    """
    return datetime(
        PLAN_DAY.year,
        PLAN_DAY.month,
        PLAN_DAY.day,
        hour,
        minute,
        tzinfo=ZoneInfo(settings.APP_TIMEZONE),
    )


# --- пункт плана несёт намерение на акт ------------------------------------


class TestActFromMark:
    async def test_a_tick_closes_the_act_without_visiting_roles(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case of the ticket, end to end.

        «Архитектурное решение по модели данных», planned at 11:00 and ticked —
        and the day now carries an architect act, with nothing typed on
        `/roles`.
        """
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client,
            document(
                task(
                    "W1",
                    text_md="Архитектурное решение по модели данных",
                    role_id=architect,
                    act_kind=ACT_KIND,
                )
            ),
        )
        await put_mark(client, first_item(plan)["id"], "done")

        acts = await day_acts(db_session)
        assert len(acts) == 1
        assert acts[0].role_id == architect
        assert acts[0].act_kind == ACT_KIND
        assert acts[0].source == SOURCE_PLAN
        assert acts[0].external_ref == first_item(plan)["id"]

        answer = await client.get(f"{ROLES_URL}/day/{PLAN_DAY.isoformat()}")
        assert answer.status_code == 200
        slices = {row["role_code"]: row for row in answer.json()["roles"]}
        assert slices[ROLE_CODE_ARCHITECT]["act_count"] == 1

    async def test_failed_closes_nothing_and_the_day_stays_without_an_act(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """«Не сделал» — the whole value of the connection is that it means it."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client, document(task("W1", role_id=architect, act_kind=ACT_KIND))
        )
        await put_mark(client, first_item(plan)["id"], "failed")
        assert await day_acts(db_session) == []

    async def test_unticking_takes_the_act_back(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client, document(task("W1", role_id=architect, act_kind=ACT_KIND))
        )
        item_id = first_item(plan)["id"]
        await put_mark(client, item_id, "done")
        assert len(await day_acts(db_session)) == 1

        await put_mark(client, item_id, None)
        assert await day_acts(db_session) == []

    async def test_an_act_a_person_confirmed_survives_unticking(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        `manual > plan`, in the only place the two can disagree.

        A person who corrected the act on `/roles` and marked it `confirmed` has
        said what the day was; un-ticking the line it grew from is not a retraction
        of that.
        """
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client, document(task("W1", role_id=architect, act_kind=ACT_KIND))
        )
        item_id = first_item(plan)["id"]
        await put_mark(client, item_id, "done")

        stored = (await day_acts(db_session))[0]
        patched = await client.patch(
            f"{ACTS_URL}/{stored.id}", json={"confidence": CONFIDENCE_CONFIRMED}
        )
        assert patched.status_code == 200, patched.text

        await put_mark(client, item_id, None)
        survivors = await day_acts(db_session)
        assert len(survivors) == 1
        assert survivors[0].confidence == CONFIDENCE_CONFIRMED

    async def test_ticking_twice_does_not_make_a_second_act(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Idempotent on `(source, external_ref)`, exactly as `#134` promised."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client, document(task("W1", role_id=architect, act_kind=ACT_KIND))
        )
        item_id = first_item(plan)["id"]
        await put_mark(client, item_id, "done")
        await put_mark(client, item_id, "done")
        assert len(await day_acts(db_session)) == 1

    async def test_an_item_without_an_act_kind_works_as_before(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Neither an act nor an error: planning an act ahead is not an obligation."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(client, document(task("W1", role_id=architect)))
        await put_mark(client, first_item(plan)["id"], "done")
        assert await day_acts(db_session) == []

    async def test_an_unknown_act_kind_is_refused_on_the_field(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The vocabulary lives in `app.schemas.role`, and the plan speaks it."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        response = await client.post(
            PLAN_URL,
            json=document(task("W1", role_id=architect, act_kind="починил кран")),
        )
        assert response.status_code == 422, response.text

    async def test_the_act_opens_up_to_the_line_of_the_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`/roles` names the item the act came from, and prints its text."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client,
            document(
                task(
                    "W1",
                    text_md="Архитектурное решение по модели данных",
                    role_id=architect,
                    act_kind=ACT_KIND,
                )
            ),
        )
        item_id = first_item(plan)["id"]
        await put_mark(client, item_id, "done")

        answer = await client.get(f"{ROLES_URL}/day/{PLAN_DAY.isoformat()}")
        act = answer.json()["acts"][0]
        assert act["plan_item_id"] == item_id
        assert act["plan_item_text"] == "Архитектурное решение по модели данных"
        assert act["is_manual"] is False

    async def test_a_line_that_stops_naming_an_act_loses_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        A plan rewritten without the act kind leaves no act standing behind it.

        The act would otherwise sit on the day with nothing to explain it — the
        exact silent lie the ticket set out to remove.
        """
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        plan = await post_plan(
            client, document(task("W1", role_id=architect, act_kind=ACT_KIND))
        )
        item_id = first_item(plan)["id"]
        await put_mark(client, item_id, "done")
        assert len(await day_acts(db_session)) == 1

        await post_plan(client, document(task("W1", id=item_id, role_id=architect)))
        assert await day_acts(db_session) == []


# --- секция плана размечает минуты -----------------------------------------


class TestMinutesFromSection:
    async def test_a_section_with_a_role_charges_its_windows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        await post_plan(
            client,
            document(
                task("W1", window="10:00-12:00"),
                task("W2", window="13:00-14:00"),
                section_role=techlead,
            ),
        )
        blocks = await day_blocks(db_session)
        assert len(blocks) == 1
        assert blocks[0].source == SOURCE_PLAN
        assert blocks[0].role_id == techlead
        assert blocks[0].minutes == 180

    async def test_nested_windows_are_counted_once(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        A «Минимум» inside a task is the same hour lived once.

        Summing the two would inflate exactly the days that plan carefully.
        """
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        await post_plan(
            client,
            document(
                task(
                    "W1",
                    window="10:00-12:00",
                    children=[
                        {
                            "kind": "minimum",
                            "text_md": "Минимум",
                            "window": "10:00-10:30",
                        }
                    ],
                ),
                section_role=techlead,
            ),
        )
        blocks = await day_blocks(db_session)
        assert len(blocks) == 1
        assert blocks[0].minutes == 120

    async def test_a_section_without_a_role_charges_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await post_plan(client, document(task("W1", window="10:00-12:00")))
        assert await day_blocks(db_session) == []

    async def test_rewriting_the_plan_restates_the_minutes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A second write states the day again instead of adding to it."""
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        await post_plan(
            client, document(task("W1", window="10:00-12:00"), section_role=techlead)
        )
        await post_plan(
            client, document(task("W1", window="10:00-11:00"), section_role=techlead)
        )
        blocks = await day_blocks(db_session)
        assert len(blocks) == 1
        assert blocks[0].minutes == 60

    async def test_a_section_that_loses_its_role_loses_its_minutes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        await post_plan(
            client, document(task("W1", window="10:00-12:00"), section_role=techlead)
        )
        assert len(await day_blocks(db_session)) == 1

        await post_plan(client, document(task("W1", window="10:00-12:00")))
        assert await day_blocks(db_session) == []


# --- план сильнее автоматики -----------------------------------------------


class TestPrecedenceOverTheAgent:
    async def test_the_section_displaces_the_agent_over_the_same_hours(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case: the day does not add up twice.

        Three hours of the agent's minutes, two of them inside the planned
        window, come back as one hour — and the day totals three, not five.
        """
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=PLAN_DAY,
                role_id=architect,
                minutes=180,
                source=SOURCE_APP_USAGE,
                started_at=moment(10),
                ended_at=moment(13),
                external_ref="interval-1",
            ),
        )
        await db_session.commit()

        await post_plan(
            client, document(task("W1", window="10:00-12:00"), section_role=techlead)
        )

        blocks = {block.source: block for block in await day_blocks(db_session)}
        assert blocks[SOURCE_PLAN].minutes == 120
        assert blocks[SOURCE_APP_USAGE].minutes == 60
        assert blocks[SOURCE_APP_USAGE].started_at == moment(12)
        assert sum(block.minutes for block in await day_blocks(db_session)) == 180

    async def test_an_agent_block_swallowed_whole_disappears(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Zero minutes is not a row: the table refuses it and the fact is «нет»."""
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=PLAN_DAY,
                role_id=architect,
                minutes=60,
                source=SOURCE_APP_USAGE,
                started_at=moment(10, 30),
                ended_at=moment(11, 30),
                external_ref="interval-1",
            ),
        )
        await db_session.commit()

        await post_plan(
            client, document(task("W1", window="10:00-12:00"), section_role=techlead)
        )
        sources = [block.source for block in await day_blocks(db_session)]
        assert sources == [SOURCE_PLAN]

    async def test_an_agent_block_a_person_confirmed_is_not_touched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Automation retracts its own claim and nobody else's."""
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=PLAN_DAY,
                role_id=architect,
                minutes=180,
                source=SOURCE_APP_USAGE,
                started_at=moment(10),
                ended_at=moment(13),
                confidence=CONFIDENCE_CONFIRMED,
                external_ref="interval-1",
            ),
        )
        await db_session.commit()

        await post_plan(
            client, document(task("W1", window="10:00-12:00"), section_role=techlead)
        )
        blocks = {block.source: block for block in await day_blocks(db_session)}
        assert blocks[SOURCE_APP_USAGE].minutes == 180

    async def test_a_manual_record_without_a_window_is_left_alone(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        «Полтора часа на найм» records an amount, not a piece of the clock.

        There is no honest way to ask whether it overlaps the plan, so nothing
        pretends to know.
        """
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        cto = await role_id(db_session, ROLE_CODE_ARCHITECT)
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=PLAN_DAY, role_id=cto, minutes=90, note="найм"
            ),
        )
        await db_session.commit()

        await post_plan(
            client, document(task("W1", window="10:00-12:00"), section_role=techlead)
        )
        assert sum(block.minutes for block in await day_blocks(db_session)) == 210


# --- ссылки на справочник ---------------------------------------------------


async def test_a_role_leaving_the_directory_does_not_take_the_plan_with_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    `SET NULL` rather than the `RESTRICT` of `role_rule`.

    A role removed from the directory must not make a plan written three months
    ago unreadable; the line and the section stay and simply stop naming
    anybody's minutes. The plan here carries no window on purpose — minutes are
    a `RESTRICT` foreign key of their own, and this is a test of the plan's two
    columns, not of theirs.
    """
    created = await client.post(
        "/api/v1/roles", json={"code": "mentor", "title": "Ментор", "ord": 9}
    )
    assert created.status_code == 201, created.text
    mentor = int(created.json()["id"])

    plan = await post_plan(
        client,
        document(
            {
                "kind": "bullet",
                "text_md": "Разобрать модель данных с джуном",
                "role_id": mentor,
                "act_kind": ACT_KIND,
            },
            section_role=mentor,
        ),
    )
    item_id = uuid.UUID(first_item(plan)["id"])
    section_id = uuid.UUID(plan["sections"][0]["id"])

    role = await role_crud.get_role(db_session, mentor)
    assert role is not None
    await db_session.delete(role)
    await db_session.commit()

    item = await db_session.get(PlanItem, item_id)
    assert item is not None
    assert item.role_id is None
    assert item.act_kind == ACT_KIND
    section = await db_session.get(PlanSection, section_id)
    assert section is not None
    assert section.role_id is None
