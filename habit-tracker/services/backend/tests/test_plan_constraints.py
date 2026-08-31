"""
Tests for the rules of a plan: the CHECK constraints, and the pure validator.

Two halves on purpose. The first writes straight into the tables, past every
service, and asserts the database refuses — that is what makes the rules true
for an import, a migration and a `psql` session as well as for the API. The
second calls `app.day.plan_validate` with no database at all, and asserts the
same refusals arrive as messages naming the line.
"""

# [review:need-review] PHASE-03/87, PHASE-03/93
# summary: the four CHECKs refuse a plan written past the service, generated `window`/`search` are populated by postgres, and the pure validator (task bar, hardness, windows across midnight, markdown flattening) answers with the offending item
import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import DayBoundary
from app.crud import day as day_crud
from app.day.plan_validate import (
    ItemFacts,
    PlanRejected,
    check_goal_exists,
    check_hard_rigidity,
    check_item_shape,
    check_task_bar,
    count_tasks,
    parse_window,
    resolve_window,
    to_plain,
)
from app.models.plan import DayPlan, PlanItem, PlanSection

PLAN_DAY = date(2026, 8, 31)

# The seeded boundary: Europe/Berlin, a day that runs 04:00 to 04:00.
BOUNDARY = DayBoundary(timezone="Europe/Berlin", day_start_hour=4)

MINUTES_IN_HOUR = 60


@pytest.fixture
async def plan_id(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[uuid.UUID, None]:
    """
    An empty plan with one section, so a test can write a single item into it.

    `seeded_goal` comes with it: the items below name goal 1 of the quarter to
    satisfy `ck_plan_item_task_is_linked_or_explained`, and since `#93` that
    column also has a foreign key.
    """
    await day_crud.seed_rules(db_session)
    await day_crud.ensure_day(db_session, PLAN_DAY)

    plan = DayPlan(id=uuid.uuid4(), day_date=PLAN_DAY, status="active", source="manual")
    section = PlanSection(
        id=uuid.uuid4(), plan_id=plan.id, ord=0, title="Работа", kind="work"
    )
    db_session.add(plan)
    db_session.add(section)
    await db_session.flush()
    yield section.id


def _item(section_id: uuid.UUID, **overrides: object) -> PlanItem:
    """A minimal valid bullet, before a test breaks one field of it."""
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "section_id": section_id,
        "ord": 0,
        "kind": "bullet",
        "rigidity": "soft",
        "text_md": "пункт",
        "text_plain": "пункт",
    }
    fields.update(overrides)
    return PlanItem(**fields)


def _at(hour: int, minute: int = 0) -> datetime:
    """A moment on the plan's date, in UTC — the shape the columns store."""
    return datetime(
        PLAN_DAY.year, PLAN_DAY.month, PLAN_DAY.day, hour, minute, tzinfo=timezone.utc
    )


# --------------------------------------------------------------------------
# The database refuses, whoever is writing
# --------------------------------------------------------------------------


async def test_a_free_item_cannot_carry_a_window(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    """
    The free evening block is physically impossible to fill with a schedule.

    Written past the service on purpose: the constraint is the rule, and the
    422 the API returns is only its explanation.
    """
    db_session.add(_item(plan_id, rigidity="free", starts_at=_at(19), ends_at=_at(21)))

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "ck_plan_item_free_has_no_window" in str(error.value)


async def test_a_task_without_a_window_is_refused(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    db_session.add(
        _item(plan_id, kind="task", done_criterion="письмо ушло", quarter_goal_id=1)
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "ck_plan_item_task_has_window_and_criterion" in str(error.value)


async def test_a_task_without_a_criterion_is_refused(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    db_session.add(
        _item(
            plan_id,
            kind="task",
            starts_at=_at(9),
            ends_at=_at(10),
            quarter_goal_id=1,
        )
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "ck_plan_item_task_has_window_and_criterion" in str(error.value)


async def test_a_task_named_by_neither_a_goal_nor_a_reason_is_refused(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    """Somebody else's urgency cannot be written into the day in silence."""
    db_session.add(
        _item(
            plan_id,
            kind="task",
            starts_at=_at(9),
            ends_at=_at(10),
            done_criterion="письмо ушло",
        )
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "ck_plan_item_task_is_linked_or_explained" in str(error.value)


async def test_a_window_that_ends_before_it_starts_is_refused(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    """
    A backwards window never lands, and `tstzrange` is what stops it first.

    The `+24h` unrolling happens in the service, so by the time a row is
    written a backwards window is a bug rather than a window across midnight.
    Worth knowing which constraint speaks: the generated `window` column is
    computed before the row-level CHECKs run, and `tstzrange(23:30, 00:30)`
    raises on its own — so the refusal arrives as a range error from asyncpg,
    not as `ck_plan_item_window_is_forward`. The CHECK is still there and still
    correct; it simply never gets the chance to be the one that fires.
    """
    db_session.add(_item(plan_id, starts_at=_at(23, 30), ends_at=_at(0, 30)))

    with pytest.raises(DBAPIError) as error:
        await db_session.flush()
    assert "range lower bound must be less than or equal" in str(error.value)


async def test_two_sections_cannot_claim_the_same_place(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    """What keeps a repeated POST from leaving two sections numbered zero."""
    section = await db_session.get(PlanSection, plan_id)
    assert section is not None
    db_session.add(
        PlanSection(id=uuid.uuid4(), plan_id=section.plan_id, ord=0, kind="study")
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "uq_plan_section_plan_ord" in str(error.value)


async def test_postgres_generates_the_window_and_the_search_vector(
    db_session: AsyncSession, plan_id: uuid.UUID
) -> None:
    """
    The two generated columns are the reason overlaps are a query.

    Asserted here because nothing in the application writes them: if the
    expression is ever dropped from a migration, this is what notices.
    """
    item = _item(
        plan_id,
        text_md="**Подтягивания** 3x5",
        text_plain="Подтягивания 3x5",
        starts_at=_at(9),
        ends_at=_at(10),
    )
    db_session.add(item)
    await db_session.flush()
    await db_session.refresh(item)

    assert item.window is not None
    assert item.search is not None
    assert "подтягиван" in str(item.search)


# --------------------------------------------------------------------------
# The validator, with no database in sight
# --------------------------------------------------------------------------


def _facts(**overrides: object) -> ItemFacts:
    """A valid bullet's facts, before a test breaks one of them."""
    fields: dict[str, object] = {
        "kind": "bullet",
        "rigidity": "soft",
        "code": None,
        "text_plain": "пункт",
    }
    fields.update(overrides)
    return ItemFacts(**fields)  # type: ignore[arg-type]  # **fields is dict[str, object], not the typed kwargs


def _task(code: str) -> ItemFacts:
    """A task that satisfies every row-level rule; only the bar can reject it."""
    return _facts(
        kind="task",
        code=code,
        text_plain=f"задача {code}",
        has_window=True,
        has_criterion=True,
        is_goal_linked=True,
    )


class _Rule:
    """The fields of `day_rule_set` the validator reads, and nothing else."""

    def __init__(
        self,
        max_work_tasks: int = 4,
        anchors: tuple[str, ...] = (),
        hard_edge_kinds: tuple[str, ...] = ("anchor", "hard_point"),
    ) -> None:
        self.max_work_tasks = max_work_tasks
        self.required_anchors = list(anchors) or ["подъём", "спорт", "отбой"]
        # Since `#142` the kinds allowed to be hard are a column of the row too,
        # so a duck of `day_rule_set` has to carry one.
        self.hard_edge_kinds = list(hard_edge_kinds)


def test_the_fifth_task_is_named_not_just_counted() -> None:
    """
    The acceptance case: 422 says which line to delete.

    "Validation error" would send the author back to re-read a document they
    just wrote; the bar exists precisely because the fifth task is the one that
    turns a day into overtime.
    """
    tasks = [_task(f"W{n}") for n in range(1, 6)]

    with pytest.raises(PlanRejected) as error:
        check_task_bar(tasks, _Rule(max_work_tasks=4))  # type: ignore[arg-type]  # _Rule is a duck-typed DayRuleSet

    assert error.value.error == "too_many_tasks"
    assert error.value.code == "W5"


def test_four_tasks_are_exactly_at_the_bar_and_pass() -> None:
    check_task_bar([_task(f"W{n}") for n in range(1, 5)], _Rule())  # type: ignore[arg-type]  # _Rule is a duck-typed DayRuleSet


def test_bullets_do_not_count_towards_the_bar() -> None:
    """Only `kind='task'` is work; the anchors and the training list are not."""
    items = [_facts(kind="anchor"), _facts(kind="minimum"), _task("W1")]
    assert count_tasks(items) == 1


def test_a_task_cannot_declare_itself_immovable() -> None:
    hard_task = _facts(kind="task", rigidity="hard", code="W1")

    with pytest.raises(PlanRejected) as error:
        check_hard_rigidity([hard_task], _Rule())  # type: ignore[arg-type]  # _Rule is a duck-typed DayRuleSet

    assert error.value.error == "hard_is_not_an_edge"
    assert error.value.code == "W1"


def test_a_hard_anchor_has_to_be_one_the_canon_names() -> None:
    stray = _facts(kind="anchor", rigidity="hard", code="кофе")

    with pytest.raises(PlanRejected) as error:
        check_hard_rigidity([stray], _Rule(anchors=("подъём", "отбой")))  # type: ignore[arg-type]  # _Rule is a duck-typed DayRuleSet

    assert error.value.error == "hard_anchor_is_not_in_canon"


def test_an_anchor_from_the_canon_may_be_hard() -> None:
    check_hard_rigidity(
        [_facts(kind="anchor", rigidity="hard", code="подъём")],
        _Rule(anchors=("подъём", "отбой")),  # type: ignore[arg-type]  # _Rule is a duck-typed DayRuleSet
    )


def test_a_hard_point_may_be_hard_without_being_an_anchor() -> None:
    """A commitment at a clock time is what that kind is for."""
    check_hard_rigidity(
        [_facts(kind="hard_point", rigidity="hard", code="Sylvia")],
        _Rule(),  # type: ignore[arg-type]  # _Rule is a duck-typed DayRuleSet
    )


def test_the_service_names_the_free_item_the_database_would_only_number() -> None:
    with pytest.raises(PlanRejected) as error:
        check_item_shape([_facts(rigidity="free", code="E1", has_window=True)])

    assert error.value.error == "free_item_has_window"
    assert error.value.code == "E1"


def test_the_service_names_a_task_missing_its_criterion() -> None:
    with pytest.raises(PlanRejected) as error:
        check_item_shape(
            [
                _facts(
                    kind="task",
                    code="W1",
                    has_window=True,
                    has_criterion=False,
                    is_goal_linked=True,
                )
            ]
        )

    assert error.value.error == "task_without_window_or_criterion"


def test_the_service_names_an_unlinked_task() -> None:
    with pytest.raises(PlanRejected) as error:
        check_item_shape(
            [
                _facts(
                    kind="task",
                    code="W1",
                    has_window=True,
                    has_criterion=True,
                    is_goal_linked=False,
                )
            ]
        )

    assert error.value.error == "task_is_not_linked"


def test_an_unlinked_reason_is_as_good_as_a_goal() -> None:
    """The rule is "say it out loud", not "always have a quarter goal"."""
    check_item_shape(
        [
            _facts(
                kind="task",
                code="W1",
                has_window=True,
                has_criterion=True,
                is_goal_linked=True,
            )
        ]
    )


def test_check_goal_exists_names_a_task_pointing_at_nothing() -> None:
    """
    A link to a goal nobody entered is not a link.

    Pure, with no session at all: the set of known ids arrives as an argument,
    which is what keeps the whole truth table of this rule testable in
    milliseconds alongside the rest of the module.
    """
    with pytest.raises(PlanRejected) as error:
        check_goal_exists(
            [_facts(kind="task", code="W1", quarter_goal_id=99)], frozenset()
        )

    assert error.value.error == "goal_does_not_exist"
    assert error.value.code == "W1"


def test_check_goal_exists_lets_a_known_goal_through() -> None:
    check_goal_exists(
        [_facts(kind="task", code="W1", quarter_goal_id=3)], frozenset({3})
    )


def test_check_goal_exists_reads_the_goal_named_in_the_header_of_the_plan() -> None:
    """«Ради чего сегодня» has no code — it is the day, not a line of it."""
    with pytest.raises(PlanRejected) as error:
        check_goal_exists([], frozenset(), plan_goal_id=99)

    assert error.value.error == "goal_does_not_exist"
    assert error.value.code is None


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def test_a_window_reads_as_two_wall_clock_times() -> None:
    assert parse_window("09:30-11:00") == (time(9, 30), time(11, 0))


def test_a_window_that_is_not_a_window_is_rejected_by_name() -> None:
    with pytest.raises(PlanRejected) as error:
        parse_window("после обеда")
    assert error.value.error == "bad_window"


def test_a_window_across_midnight_is_sixty_minutes_not_minus_twenty_three_hours() -> (
    None
):
    """
    The acceptance case, and the defect it names.

    23:30 and 00:30 are on different calendar dates but inside the same day,
    because the day runs 04:00 to 04:00. Subtracting them as times of one date
    is where the negative duration came from.
    """
    start, end = parse_window("23:30-00:30")
    window = resolve_window(PLAN_DAY, start, end, BOUNDARY)

    assert window.minutes == MINUTES_IN_HOUR
    assert window.starts_at.astimezone(timezone.utc).day == PLAN_DAY.day
    assert window.ends_at > window.starts_at


def test_an_ordinary_window_stays_on_its_own_date() -> None:
    start, end = parse_window("09:30-11:00")
    window = resolve_window(PLAN_DAY, start, end, BOUNDARY)

    assert window.minutes == 90
    assert window.starts_at.astimezone(timezone.utc).date() == PLAN_DAY


def test_a_window_before_the_boundary_hour_belongs_to_the_same_day() -> None:
    """01:00-02:00 written into the plan of the 31st happens on the 1st."""
    start, end = parse_window("01:00-02:00")
    window = resolve_window(PLAN_DAY, start, end, BOUNDARY)

    assert window.minutes == MINUTES_IN_HOUR
    assert (
        window.starts_at
        > resolve_window(PLAN_DAY, time(22, 0), time(23, 0), BOUNDARY).starts_at
    )


def test_a_zero_length_window_is_pushed_a_full_day_rather_than_refused() -> None:
    """
    The same `+24h` `parse_window` in `plan_html.py` has always applied.

    Not a good window, but the `ends_at > starts_at` CHECK passes and the
    twenty-four-hour bar on the schedule is as visible as it deserves to be.
    """
    window = resolve_window(PLAN_DAY, time(10, 0), time(10, 0), BOUNDARY)
    assert window.minutes == 24 * MINUTES_IN_HOUR


# --------------------------------------------------------------------------
# Markdown flattened
# --------------------------------------------------------------------------


def test_plain_text_drops_the_markup_and_keeps_the_words() -> None:
    assert to_plain("**Подтягивания** 3x5, `RIR 2`") == "Подтягивания 3x5, RIR 2"


def test_plain_text_keeps_the_text_of_a_link_and_drops_the_url() -> None:
    assert to_plain("[86cbau6mb](https://app.clickup.com/t/86cbau6mb)") == "86cbau6mb"


def test_plain_text_collapses_the_line_breaks_of_a_wrapped_paragraph() -> None:
    assert to_plain("первая\n  вторая") == "первая вторая"
