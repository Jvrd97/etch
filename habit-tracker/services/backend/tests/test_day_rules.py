"""
Tests for the day canon: the resolver, the seed, and the constraint the database
enforces so that no date can ever be covered by two rules.
"""

# [review:need-review] PHASE-03/86
# summary: pure resolver tests (no database) plus the exclusion constraint, the seed, boundary publication and the "one local_date in the repo" guard
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.crud import day as day_crud
from app.day.rules import (
    CANON_CHANGED_ON,
    KIND_OFF,
    KIND_WORK,
    SEED_RULES,
    NoRuleForDate,
    active_rule,
    covers,
    day_kind,
    is_nocode_date,
    resolve_rule,
)
from app.models.day import DayRuleSet

BERLIN = ZoneInfo("Europe/Berlin")


def make_rule(
    valid_from: date,
    valid_to: date | None = None,
    *,
    id: int = 1,
    timezone: str = "Europe/Berlin",
    day_start_hour: int = 4,
    workdays: tuple[int, ...] = (1, 2, 3, 4, 5),
    nocode_days: tuple[int, ...] = (2, 4),
) -> DayRuleSet:
    """A rule row built in memory; nothing here needs a database."""
    return DayRuleSet(
        id=id,
        valid_from=valid_from,
        valid_to=valid_to,
        timezone=timezone,
        day_start_hour=day_start_hour,
        work_cap_min=480,
        work_hard_cap_min=540,
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        tasks_required_ratio=Decimal("1.00"),
        overtime_disqualifies=True,
        workdays=list(workdays),
        nocode_days=list(nocode_days),
        required_anchors=["подъём"],
        note_md="",
    )


# --- the interval is half-open ------------------------------------------------


def test_valid_from_belongs_to_the_rule() -> None:
    rule = make_rule(date(2026, 8, 17), date(2026, 9, 1))
    assert covers(rule, date(2026, 8, 17))


def test_valid_to_belongs_to_the_next_rule() -> None:
    """The day a canon changes is lived under the new rule, not the old one."""
    rule = make_rule(date(2026, 8, 17), date(2026, 9, 1))
    assert not covers(rule, date(2026, 9, 1))


def test_a_date_before_the_interval_is_not_covered() -> None:
    rule = make_rule(date(2026, 8, 17), date(2026, 9, 1))
    assert not covers(rule, date(2026, 8, 16))


def test_an_open_interval_covers_every_later_date() -> None:
    rule = make_rule(date(2026, 8, 17), None)
    assert covers(rule, date(2099, 1, 1))


# --- resolving a date to its rule --------------------------------------------


def test_resolve_picks_the_interval_containing_the_date() -> None:
    legacy = make_rule(date(2020, 1, 1), CANON_CHANGED_ON, id=1)
    current = make_rule(CANON_CHANGED_ON, None, id=2)
    assert resolve_rule([legacy, current], date(2026, 8, 14)).id == 1
    assert resolve_rule([legacy, current], date(2026, 8, 30)).id == 2


def test_resolve_refuses_a_date_no_rule_covers() -> None:
    """A verdict under an invented canon is worse than no verdict."""
    current = make_rule(date(2026, 8, 17), None)
    with pytest.raises(NoRuleForDate) as error:
        resolve_rule([current], date(2026, 8, 16))
    assert "2026-08-16" in str(error.value)


def test_active_rule_is_the_last_interval_and_needs_no_clock() -> None:
    legacy = make_rule(date(2020, 1, 1), CANON_CHANGED_ON, id=1)
    current = make_rule(CANON_CHANGED_ON, None, id=2)
    assert active_rule([legacy, current]).id == 2


def test_active_rule_refuses_an_empty_table() -> None:
    with pytest.raises(NoRuleForDate):
        active_rule([])


# --- what kind of day a date is ----------------------------------------------


def test_weekday_is_a_working_day_and_sunday_is_not() -> None:
    rule = make_rule(date(2026, 8, 17))
    assert day_kind(rule, date(2026, 8, 28)) == KIND_WORK  # Friday
    assert day_kind(rule, date(2026, 8, 30)) == KIND_OFF  # Sunday


def test_nocode_days_follow_the_rule_s_own_schedule() -> None:
    rule = make_rule(date(2026, 8, 17), nocode_days=(2, 4))
    assert is_nocode_date(rule, date(2026, 9, 1))  # Tuesday
    assert not is_nocode_date(rule, date(2026, 9, 2))  # Wednesday


# --- the seed -----------------------------------------------------------------


def test_the_seed_has_two_versions_that_meet_without_a_gap() -> None:
    legacy, current = SEED_RULES
    assert legacy.valid_to == current.valid_from == CANON_CHANGED_ON
    assert current.valid_to is None


def test_the_seed_records_what_changed_on_the_canon_date() -> None:
    """The numbers the record names, and only those, differ between the rows."""
    legacy, current = SEED_RULES
    assert (legacy.work_cap_min, current.work_cap_min) == (600, 480)
    assert (legacy.tasks_required_ratio, current.tasks_required_ratio) == (
        Decimal("0.80"),
        Decimal("1.00"),
    )
    assert legacy.timezone == current.timezone
    assert legacy.day_start_hour == current.day_start_hour
    assert legacy.workdays == current.workdays
    assert legacy.required_anchors == current.required_anchors


# --- the day boundary is read from the rule ----------------------------------


@pytest.fixture(autouse=True)
def _clean_boundary() -> None:
    """Every test in this module starts from the settings fallback."""
    daytime.reset_boundary()


def test_publishing_a_rule_moves_the_answer_of_local_date() -> None:
    """
    The acceptance case: 00:01 belongs to yesterday, and the hour that says so
    comes from the rule row rather than from a setting.
    """
    day_crud.publish_boundary([make_rule(date(2026, 8, 17), day_start_hour=4)])
    at = datetime(2026, 8, 29, 0, 1, tzinfo=BERLIN)
    assert daytime.local_date(at) == date(2026, 8, 28)


def test_a_rule_with_a_midnight_boundary_answers_the_calendar_date() -> None:
    """Proof the answer follows the row, not a constant baked in somewhere."""
    day_crud.publish_boundary([make_rule(date(2026, 8, 17), day_start_hour=0)])
    at = datetime(2026, 8, 29, 0, 1, tzinfo=BERLIN)
    assert daytime.local_date(at) == date(2026, 8, 29)


def test_the_zone_follows_the_rule_too() -> None:
    day_crud.publish_boundary(
        [make_rule(date(2026, 8, 17), timezone="Asia/Tokyo", day_start_hour=4)]
    )
    assert daytime.current_boundary().timezone == "Asia/Tokyo"


def test_an_empty_table_leaves_the_settings_fallback_in_place() -> None:
    """A process may start against a database that has not been migrated yet."""
    assert day_crud.publish_boundary([]) is False
    assert daytime.current_boundary().day_start_hour == 4


def test_the_boundary_of_the_current_rule_wins_over_an_older_one() -> None:
    legacy = make_rule(date(2020, 1, 1), CANON_CHANGED_ON, id=1, day_start_hour=6)
    current = make_rule(CANON_CHANGED_ON, None, id=2, day_start_hour=4)
    day_crud.publish_boundary([legacy, current])
    assert daytime.current_boundary().day_start_hour == 4


def test_the_repository_defines_local_date_exactly_once() -> None:
    """
    Nine tickets attach data to a day. A second answer to "what day is it"
    anywhere under `app/` is the failure this whole module exists to prevent, so
    it is checked mechanically rather than left to review.
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    definitions = [
        path
        for path in app_dir.rglob("*.py")
        if "def local_date(" in path.read_text(encoding="utf-8")
    ]
    assert [path.name for path in definitions] == ["daytime.py"]


# --- what the database refuses ------------------------------------------------


async def test_overlapping_rule_intervals_are_refused_by_the_database(
    db_session: AsyncSession,
) -> None:
    """
    Not by a service: a service check is skipped by every writer that does not
    go through it — an import, a later migration, a psql session.
    """
    db_session.add(make_rule(date(2026, 1, 1), date(2026, 8, 17), id=1))
    await db_session.flush()

    db_session.add(make_rule(date(2026, 6, 1), date(2026, 12, 1), id=2))
    with pytest.raises(IntegrityError) as error:
        await db_session.flush()
    assert "excl_day_rule_set_no_overlap" in str(error.value)


async def test_touching_intervals_are_accepted(db_session: AsyncSession) -> None:
    """`[valid_from, valid_to)` — the end of one rule is the start of the next."""
    db_session.add(make_rule(date(2026, 1, 1), date(2026, 8, 17), id=1))
    db_session.add(make_rule(date(2026, 8, 17), None, id=2))
    await db_session.flush()
    assert len(await day_crud.list_rules(db_session)) == 2


async def test_two_open_ended_rules_cannot_coexist(db_session: AsyncSession) -> None:
    """An unbounded `valid_to` overlaps every later interval, including another one."""
    db_session.add(make_rule(date(2026, 1, 1), None, id=1))
    await db_session.flush()
    db_session.add(make_rule(date(2026, 8, 17), None, id=2))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# --- the seed lands, and lands once ------------------------------------------


async def test_seed_rules_fills_an_empty_table(db_session: AsyncSession) -> None:
    await day_crud.seed_rules(db_session)
    rules = await day_crud.list_rules(db_session)
    assert [rule.valid_from for rule in rules] == [
        seed.valid_from for seed in SEED_RULES
    ]


async def test_seed_rules_is_idempotent(db_session: AsyncSession) -> None:
    await day_crud.seed_rules(db_session)
    await day_crud.seed_rules(db_session)
    assert len(await day_crud.list_rules(db_session)) == len(SEED_RULES)


async def test_rule_for_date_resolves_history_to_the_legacy_row(
    db_session: AsyncSession,
) -> None:
    await day_crud.seed_rules(db_session)
    legacy = await day_crud.rule_for_date(db_session, date(2026, 8, 14))
    current = await day_crud.rule_for_date(db_session, date(2026, 8, 30))
    assert legacy.work_cap_min == 600
    assert current.work_cap_min == 480
    assert legacy.id != current.id
