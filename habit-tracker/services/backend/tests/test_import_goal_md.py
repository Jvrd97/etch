"""
Tests for the import of `goal.md` — levels, milestones, the graph, the quarter.

The second run is what these tests are really about. A file that has not changed
must leave the four tables byte-for-byte as they were, and a milestone somebody
marked done by hand must survive a re-read of a file that does not record
statuses at all. Idempotence bought by overwriting is not idempotence.
"""

# [review:need-review] PHASE-03/93
# summary: `goal.md` parsed into six levels with their `⚠ подтверди` questions, ten milestones with criteria and the «Открывается чем» graph, five goals of `2026-Q3`; a second run changes no row, and the status a person set is not overwritten by a file that does not know it
import shutil
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.imports.personal_os import import_root
from app.models.goal import GoalLevel, Milestone, MilestoneDep, QuarterGoal

FIXTURES = Path(__file__).parent / "fixtures" / "personal_os"

QUARTER = "2026-Q3"


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The rule table as a migrated database has it; `create_all` has no seed."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A copy of the fixture repository, so a test can prove nothing wrote to it."""
    copied = tmp_path / "personal-os"
    shutil.copytree(FIXTURES, copied)
    return copied


async def goal_rows(db: AsyncSession) -> list[tuple[Any, ...]]:
    """
    Every row of the four goal tables, as plain values.

    Compared before and after the second run: "changes nothing" has to mean the
    rows were not rewritten, not that they were rewritten to equal values.
    """
    levels = await db.execute(
        select(
            GoalLevel.level,
            GoalLevel.title,
            GoalLevel.body_md,
            GoalLevel.open_questions,
        ).order_by(GoalLevel.level)
    )
    milestones = await db.execute(
        select(
            Milestone.code,
            Milestone.title,
            Milestone.done_criterion,
            Milestone.when_text,
            Milestone.ord,
            Milestone.status,
            Milestone.done_on,
        ).order_by(Milestone.ord)
    )
    deps = await db.execute(
        select(MilestoneDep.milestone_code, MilestoneDep.depends_on_code).order_by(
            MilestoneDep.milestone_code, MilestoneDep.depends_on_code
        )
    )
    goals = await db.execute(
        select(
            QuarterGoal.quarter,
            QuarterGoal.ord,
            QuarterGoal.text_md,
            QuarterGoal.milestone_code,
            QuarterGoal.status,
        ).order_by(QuarterGoal.quarter, QuarterGoal.ord)
    )
    return [
        *(tuple(row) for row in levels),
        *(tuple(row) for row in milestones),
        *(tuple(row) for row in deps),
        *(tuple(row) for row in goals),
    ]


async def test_goal_md_parses_levels_milestones_deps_and_quarter(
    db_session: AsyncSession, root: Path
) -> None:
    """The whole file, read once: six levels, ten milestones, five goals."""
    await import_root(db_session, root)

    levels = (
        (await db_session.execute(select(GoalLevel).order_by(GoalLevel.level)))
        .scalars()
        .all()
    )
    assert [level.level for level in levels] == [0, 1, 2, 3, 4, 5]
    assert levels[0].title.startswith("конечная точка")
    # The `⚠ подтверди` lines stay questions rather than becoming prose.
    assert len(levels[0].open_questions) == 1
    assert "какой из двух главный" in levels[0].open_questions[0]
    assert len(levels[2].open_questions) == 1
    assert levels[1].open_questions == []

    milestones = (
        (await db_session.execute(select(Milestone).order_by(Milestone.ord)))
        .scalars()
        .all()
    )
    assert [one.code for one in milestones] == [f"M{n}" for n in range(1, 11)]
    assert milestones[0].title == "Переезд"
    assert milestones[0].done_criterion == "переехал"
    assert milestones[0].when_text == "сейчас"
    # Nothing in the file says a milestone is done, so nothing may claim it is.
    assert {one.status for one in milestones} == {"open"}
    assert all(one.done_on is None for one in milestones)

    deps = (
        await db_session.execute(
            select(MilestoneDep.milestone_code, MilestoneDep.depends_on_code)
        )
    ).all()
    edges = {(code, depends_on) for code, depends_on in deps}
    assert ("M4", "M2") in edges
    assert ("M9", "M5") in edges
    assert ("M10", "M8") in edges
    assert ("M10", "M9") in edges
    # «ничем, это первый шаг» is not a dependency on a milestone called «ничем».
    assert not any(code == "M1" for code, _ in edges)

    goals = (
        (await db_session.execute(select(QuarterGoal).order_by(QuarterGoal.ord)))
        .scalars()
        .all()
    )
    assert [one.ord for one in goals] == [1, 2, 3, 4, 5]
    # «Q3 2026» in the file, `2026-Q3` in the column: sortable, and the shape
    # `week.iso_code` already uses.
    assert {one.quarter for one in goals} == {QUARTER}
    assert goals[0].text_md.startswith("**Денежный контур")
    # «M1 — переезд» is a goal of the quarter that is also a milestone.
    assert goals[2].milestone_code == "M1"
    assert goals[3].milestone_code == "M2"
    assert goals[0].milestone_code is None


async def test_a_second_run_changes_no_row(
    db_session: AsyncSession, root: Path
) -> None:
    """The seventh acceptance case, over the four tables of the goals."""
    await import_root(db_session, root)
    before = await goal_rows(db_session)

    await import_root(db_session, root)

    assert await goal_rows(db_session) == before


async def test_a_milestone_marked_done_by_hand_survives_a_re_import(
    db_session: AsyncSession, root: Path
) -> None:
    """
    Whether M2 is done is a fact of a person, and `goal.md` does not record it.

    Without this the idempotence above would be bought by overwriting: the rows
    would match each other after every run and lose what somebody entered
    between them.
    """
    await import_root(db_session, root)
    milestone = await db_session.get(Milestone, "M2")
    assert milestone is not None
    milestone.status = "done"
    milestone.done_on = date(2026, 8, 30)
    await db_session.flush()

    await import_root(db_session, root)

    reread = await db_session.get(Milestone, "M2")
    assert reread is not None
    assert reread.status == "done"
    assert reread.done_on == date(2026, 8, 30)


async def test_nothing_under_the_root_is_written_to(
    db_session: AsyncSession, root: Path
) -> None:
    """`goal.md` is read; the repository it lives in is an archive."""
    before = (root / "goal.md").read_bytes()

    await import_root(db_session, root)

    assert (root / "goal.md").read_bytes() == before
