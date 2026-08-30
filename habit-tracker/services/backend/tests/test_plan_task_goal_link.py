"""
Tests for the link between a task of a plan and a goal of the quarter.

Two halves, the same split as `test_plan_constraints.py`. The foreign key is
written past the service and asserted to refuse — that is what makes the rule
true for an import and a `psql` session. The 422 is asserted through the API and
has to arrive *before* anything is written: an `IntegrityError` would come back
as a 500 naming a constraint, and the author of the plan needs the code of the
task.
"""

# [review:need-review] PHASE-03/93
# summary: `plan_item.quarter_goal_id` refuses an unknown goal at the database, and POST /day/{date}/plan refuses it earlier with a 422 that names the task
import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.models.plan import DayPlan, PlanItem, PlanSection

PLAN_DAY = date(2026, 8, 31)
PLAN_URL = f"/api/v1/day/{PLAN_DAY.isoformat()}/plan"

# An id nothing ever inserted. Four digits rather than a plausible 2, so a test
# that passes for the wrong reason is visible in the failure message.
UNKNOWN_GOAL_ID = 9999


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The canon a plan is judged by; `create_all` never runs the seed."""
    await day_crud.seed_rules(db_session)
    yield


@pytest.fixture
async def section_id(db_session: AsyncSession) -> AsyncGenerator[uuid.UUID, None]:
    """An empty plan with one section, to write a single item into."""
    await day_crud.ensure_day(db_session, PLAN_DAY)
    plan = DayPlan(id=uuid.uuid4(), day_date=PLAN_DAY, status="active", source="manual")
    section = PlanSection(
        id=uuid.uuid4(), plan_id=plan.id, ord=0, title="Работа", kind="work"
    )
    db_session.add(plan)
    db_session.add(section)
    await db_session.flush()
    yield section.id


def task(code: str, **overrides: Any) -> dict[str, Any]:
    """A task that satisfies every row-level rule, before a test breaks one."""
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": "09:00-10:00",
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


async def test_a_plan_item_naming_an_unknown_goal_is_refused_by_the_fk(
    db_session: AsyncSession, section_id: uuid.UUID
) -> None:
    """The eighth acceptance case: the foreign key works, whoever is writing."""
    db_session.add(
        PlanItem(
            id=uuid.uuid4(),
            section_id=section_id,
            ord=0,
            kind="task",
            rigidity="soft",
            text_md="Задача W1",
            text_plain="Задача W1",
            starts_at=datetime(2026, 8, 31, 7, tzinfo=timezone.utc),
            ends_at=datetime(2026, 8, 31, 8, tzinfo=timezone.utc),
            done_criterion="письмо отправлено",
            quarter_goal_id=UNKNOWN_GOAL_ID,
        )
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "fk_plan_item_quarter_goal_id" in str(error.value)


async def test_posting_a_plan_with_an_unknown_goal_answers_422_naming_the_task(
    client: AsyncClient,
) -> None:
    """
    The refusal arrives as an answer, not as a crash.

    A plan that names a goal nobody entered would break the foreign key on the
    way in, and an `IntegrityError` is a 500 naming a constraint. The check runs
    before the first row is written, so the author gets the code of the task.
    """
    body = {
        "title": "План 2026-08-31 (пн)",
        "sections": [
            {"kind": "work", "items": [task("W1", quarter_goal_id=UNKNOWN_GOAL_ID)]}
        ],
    }

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "goal_does_not_exist"
    assert detail["item_code"] == "W1"
    assert str(UNKNOWN_GOAL_ID) in detail["message"]


async def test_a_plan_with_a_real_goal_is_accepted(
    client: AsyncClient, seeded_goal: int
) -> None:
    """The control branch: without it the test above is green for any refusal."""
    body = {
        "title": "План 2026-08-31 (пн)",
        "sections": [
            {"kind": "work", "items": [task("W1", quarter_goal_id=seeded_goal)]}
        ],
    }

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 201
    assert response.json()["sections"][0]["items"][0]["quarter_goal_id"] == seeded_goal


async def test_a_plan_naming_a_goal_in_its_header_is_checked_too(
    client: AsyncClient,
) -> None:
    """
    «Ради чего сегодня» is a link like any other, and it has the same foreign key.

    Checked in the same pass rather than left to the database: a header pointing
    at nothing would otherwise be the one way to turn a plan into a 500.
    """
    body = {
        "title": "План 2026-08-31 (пн)",
        "quarter_goal_id": UNKNOWN_GOAL_ID,
        "sections": [],
    }

    response = await client.post(PLAN_URL, json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "goal_does_not_exist"
    assert detail["item_code"] is None
