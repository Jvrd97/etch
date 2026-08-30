"""
Tests for GET /api/v1/goals and the two writes beside it.

The board is asserted through the API after a real import of the fixture
`goal.md`, so what the screen gets is what the file says rather than what a test
builder invented. The ceiling of five is asserted twice: once against the tables
directly — that is where the rule lives — and once through the handle, which
only has to name the refusal rather than repeat it.
"""

# [review:need-review] PHASE-03/93
# summary: the goal board answers six levels, ten milestones with their dependency codes and five goals of the quarter; a sixth goal is refused by two different constraints of the database and comes back as a 422 through the API; closing a milestone dates it and reopening it clears the date
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import goal as goal_crud
from app.imports.personal_os import import_root
from app.models.goal import QuarterGoal

FIXTURES = Path(__file__).parent / "fixtures" / "personal_os"

GOALS_URL = "/api/v1/goals"
QUARTER = "2026-Q3"


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The rule table as a migrated database has it; `create_all` has no seed."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


@pytest.fixture
async def imported(
    db_session: AsyncSession, tmp_path: Path
) -> AsyncGenerator[None, None]:
    """The fixture repository imported, goals included."""
    root = tmp_path / "personal-os"
    shutil.copytree(FIXTURES, root)
    await import_root(db_session, root)
    yield


def goal(ord_: int) -> dict[str, object]:
    return {"ord": ord_, "text_md": f"Цель {ord_}", "milestone_code": None}


async def test_get_goals_returns_six_levels_ten_milestones_and_five_quarter_goals(
    client: AsyncClient, imported: None
) -> None:
    """The first acceptance case, from the side the screen sees it."""
    response = await client.get(GOALS_URL)

    assert response.status_code == 200
    body = response.json()
    assert [level["level"] for level in body["levels"]] == [0, 1, 2, 3, 4, 5]
    assert [one["code"] for one in body["milestones"]] == [
        f"M{n}" for n in range(1, 11)
    ]
    assert len(body["goals"]) == 5
    assert [one["ord"] for one in body["goals"]] == [1, 2, 3, 4, 5]
    # The open questions travel as questions, not as prose inside the body.
    assert body["levels"][0]["open_questions"]


async def test_the_quarter_is_the_one_today_falls_in(
    client: AsyncClient, imported: None
) -> None:
    """
    The quarter is computed from the day boundary, not from the browser.

    The fixture's goals are `2026-Q3`, and the answer names whichever quarter is
    running now — so this asserts the naming rather than the fixture.
    """
    response = await client.get(GOALS_URL)

    assert response.json()["quarter"] == goal_crud.quarter_code(today_local())


async def test_m10_depends_on_m9_and_m8(client: AsyncClient, imported: None) -> None:
    """The fifth acceptance case: «M9 + M8» arrives as two codes, not a sentence."""
    body = (await client.get(GOALS_URL)).json()
    by_code = {one["code"]: one for one in body["milestones"]}

    assert by_code["M10"]["depends_on"] == ["M8", "M9"]
    assert by_code["M4"]["depends_on"] == ["M2"]
    assert by_code["M1"]["depends_on"] == []


async def test_marking_a_milestone_done_sets_the_date_and_drops_it_from_open(
    client: AsyncClient, imported: None
) -> None:
    """The sixth acceptance case, and the way back out of it."""
    response = await client.patch(f"{GOALS_URL}/milestones/M9", json={"status": "done"})

    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert response.json()["done_on"] == today_local().isoformat()

    board = (await client.get(GOALS_URL)).json()
    open_codes = [one["code"] for one in board["milestones"] if one["status"] == "open"]
    assert "M9" not in open_codes

    reopened = await client.patch(f"{GOALS_URL}/milestones/M9", json={"status": "open"})
    # A milestone that is not closed has no date of being closed; leaving the old
    # one behind is how a board shows a closed M9 that is also open.
    assert reopened.json()["done_on"] is None


async def test_an_unknown_status_is_refused_by_name(
    client: AsyncClient, imported: None
) -> None:
    response = await client.patch(
        f"{GOALS_URL}/milestones/M9", json={"status": "почти"}
    )

    assert response.status_code == 422
    assert "почти" in response.json()["detail"]


async def test_patching_a_milestone_nobody_entered_is_a_404(
    client: AsyncClient, imported: None
) -> None:
    response = await client.patch(
        f"{GOALS_URL}/milestones/M42", json={"status": "done"}
    )

    assert response.status_code == 404


async def test_a_sixth_quarter_goal_is_refused_by_the_database(
    db_session: AsyncSession,
) -> None:
    """
    The fourth acceptance case, written past every service.

    Two branches, because neither constraint is the ceiling on its own: the
    CHECK refuses a sixth position, and the UNIQUE refuses a sixth row squeezed
    into a position that is taken.
    """
    for ord_ in range(1, 6):
        db_session.add(QuarterGoal(quarter=QUARTER, ord=ord_, text_md=f"Цель {ord_}"))
    await db_session.flush()

    db_session.add(QuarterGoal(quarter=QUARTER, ord=6, text_md="Шестая"))
    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "ck_quarter_goal_ord" in str(error.value)

    await db_session.rollback()
    for ord_ in range(1, 6):
        db_session.add(QuarterGoal(quarter=QUARTER, ord=ord_, text_md=f"Цель {ord_}"))
    await db_session.flush()

    db_session.add(QuarterGoal(quarter=QUARTER, ord=5, text_md="Шестая"))
    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "uq_quarter_goal_quarter_ord" in str(error.value)


async def test_a_sixth_goal_through_the_api_answers_422_not_500(
    client: AsyncClient,
) -> None:
    """The refusal came from the database; the handle only names it."""
    body = {"goals": [goal(ord_) for ord_ in range(1, 6)]}
    assert (
        await client.put(f"{GOALS_URL}/quarter/{QUARTER}", json=body)
    ).status_code == 200

    body["goals"] = [
        *body["goals"],
        {"ord": 5, "text_md": "Шестая", "milestone_code": None},
    ]
    response = await client.put(f"{GOALS_URL}/quarter/{QUARTER}", json=body)

    assert response.status_code == 422
    assert QUARTER in response.json()["detail"]


async def test_replacing_the_quarter_answers_the_board_it_wrote(
    client: AsyncClient,
) -> None:
    body = {"goals": [goal(ord_) for ord_ in range(1, 6)]}

    response = await client.put(f"{GOALS_URL}/quarter/{QUARTER}", json=body)

    assert response.status_code == 200
    assert [one["text_md"] for one in response.json()["goals"]] == [
        f"Цель {n}" for n in range(1, 6)
    ]
