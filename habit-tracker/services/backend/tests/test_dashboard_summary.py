# [review:need-review] PHASE-03/296, 309
# summary: #309 — the history of every habit is read once and every value once; `parts=health` says what the full answer says about health, leaves the other blocks empty and costs the same whatever the habits
# summary: tests for GET /dashboard/summary — empty database answers 200 with null/empty blocks, the window cut on the server's day (boundary included), week and month, streak day strips for avoid and build, the three rings, health state against the personal norm, bests and records, workout weeks, one insight without a model, and a flat SQL statement count
"""
Dashboard summary: one answer for the whole dashboard.

The sentences the file is about. A database with nothing in it answers 200 with
`null` and empty lists, never with zeros. The window is cut on the day of the
server, so the night after midnight still belongs to yesterday. The health ring is
the share of key metrics that are not worse than the person's own norm, and it
stays `null` rather than guess on fewer than three days. The words of the insight
come from a rule over the same numbers, never from a model. And reading the
dashboard costs the same number of SQL statements with two categories and
two weeks as with twenty categories and a month.
"""

from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.crud import day as day_crud
from app.crud import health as health_crud
from app.llm import client as llm_client
from app.models.challenge import Challenge
from app.models.field import FieldType
from app.models.summary import DaySummary
from app.schemas.health import HealthWorkoutIn
from tests.conftest import SqlCounter, test_engine
from tests.test_week_review import (
    add_category,
    add_entry,
    add_health,
    add_night,
    close_day,
)

URL = "/api/v1/dashboard/summary"

# 2026-10-31 is a Saturday; the server's noon is 13:00 in Europe/Berlin.
TODAY = date(2026, 10, 31)
NOON = datetime(2026, 10, 31, 11, 0, tzinfo=timezone.utc)
WEEK_FROM = date(2026, 10, 25)
MONTH_FROM = date(2026, 10, 2)

STEPS = "HKQuantityTypeIdentifierStepCount"
RESTING_HR = "HKQuantityTypeIdentifierRestingHeartRate"
HRV = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"

# The dashboard costs nine statements, whatever it holds; a tenth is a new source
# on purpose, not a loop.
MAX_QUERIES = 9


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[None, None]:
    """The day rules and health catalogue as a migrated database has them, and the clock at noon."""
    await day_crud.seed_rules(db_session)
    await health_crud.seed_catalog(db_session)
    await db_session.commit()
    monkeypatch.setattr(daytime, "now_utc", lambda: NOON)
    yield


async def summary(client: AsyncClient, period: str | None = None) -> dict[str, Any]:
    response = await client.get(URL, params={"period": period} if period else None)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def fill_metric(
    db: AsyncSession, identifier: str, start: date, end: date, value: float
) -> None:
    for day in days_between(start, end):
        await add_health(db, identifier, day, value)


async def fill_sleep(db: AsyncSession, start: date, end: date, minutes: float) -> None:
    for day in days_between(start, end):
        await add_night(db, day, minutes)


# --- the contract on an empty database -------------------------------------------


async def test_an_empty_database_answers_200_with_nulls_and_empty_lists(
    client: AsyncClient,
) -> None:
    body = await summary(client)

    assert body == {
        "period": "week",
        "from": "2026-10-25",
        "to": "2026-10-31",
        "today": "2026-10-31",
        "scores": {
            "health": {"value": None, "label": None, "basis_days": 0},
            "habits": {"value": None, "done": None, "total": None},
            "challenges": {"done": None, "total": None},
        },
        "streaks": [],
        "health": [],
        "bests": [],
        "workouts": {"weeks": [], "total": None, "delta_vs_previous": None},
        "insight": None,
    }


async def test_the_month_window_is_thirty_days_ending_today(
    client: AsyncClient,
) -> None:
    body = await summary(client, "month")

    assert (body["period"], body["from"], body["to"]) == (
        "month",
        MONTH_FROM.isoformat(),
        TODAY.isoformat(),
    )


async def test_an_unknown_period_is_refused(client: AsyncClient) -> None:
    response = await client.get(URL, params={"period": "year"})

    assert response.status_code == 422


async def test_the_window_follows_the_day_of_the_server_not_the_calendar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """02:30 Berlin on 1 November is still 31 October; 04:30 is the new day."""
    monkeypatch.setattr(
        daytime, "now_utc", lambda: datetime(2026, 11, 1, 1, 30, tzinfo=timezone.utc)
    )
    night = await summary(client)
    monkeypatch.setattr(
        daytime, "now_utc", lambda: datetime(2026, 11, 1, 3, 30, tzinfo=timezone.utc)
    )
    morning = await summary(client)

    assert (night["today"], night["to"]) == ("2026-10-31", "2026-10-31")
    assert (morning["today"], morning["from"], morning["to"]) == (
        "2026-11-01",
        "2026-10-26",
        "2026-11-01",
    )


# --- streaks ---------------------------------------------------------------------


async def test_an_avoid_streak_breaks_on_the_relapse_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category, flag = await add_category(
        db_session, "Курение", FieldType.BOOLEAN, avoid=True
    )
    await add_entry(db_session, category, flag, date(2026, 10, 20), "false")
    await add_entry(db_session, category, flag, date(2026, 10, 29), "true")

    [streak] = (await summary(client))["streaks"]

    assert streak == {
        "category_id": category,
        "name": "Курение",
        "kind": "avoid",
        "current": 2,
        "best": 9,
        "days": [True, True, True, True, False, True, True],
    }


async def test_a_build_streak_counts_days_with_an_entry_and_forgives_today(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Today without an entry is not a miss yet: the day is not over."""
    category, flag = await add_category(db_session, "Зарядка", FieldType.BOOLEAN)
    for day in (25, 26, 27, 30):
        await add_entry(db_session, category, flag, date(2026, 10, day), "true")

    [before] = (await summary(client))["streaks"]
    await add_entry(db_session, category, flag, TODAY, "true")
    [after] = (await summary(client))["streaks"]

    assert before["kind"] == "build"
    assert (before["current"], before["best"]) == (1, 3)
    assert before["days"] == [True, True, True, False, False, True, None]
    assert (after["current"], after["best"]) == (2, 3)
    assert after["days"][-1] is True


async def test_days_before_the_first_entry_are_unknown_and_the_month_strip_is_30_long(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category, flag = await add_category(db_session, "Йога", FieldType.BOOLEAN)
    await add_entry(db_session, category, flag, date(2026, 10, 28), "true")

    [week] = (await summary(client))["streaks"]
    [month] = (await summary(client, "month"))["streaks"]

    assert week["days"] == [None, None, None, True, False, False, None]
    assert len(month["days"]) == 30
    assert month["days"][:26] == [None] * 26


async def test_a_category_with_no_entries_or_not_active_is_not_a_streak(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_category(db_session, "Пустая", FieldType.BOOLEAN)
    old, flag = await add_category(db_session, "Старая", FieldType.BOOLEAN)
    await add_entry(db_session, old, flag, TODAY, "true")
    await db_session.execute(text("UPDATE categories SET is_active = false"))
    await db_session.commit()

    assert (await summary(client))["streaks"] == []


async def test_streaks_are_ordered_by_the_current_run_then_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for name, days in (("Б", (31,)), ("А", (31,)), ("В", (30, 31))):
        category, flag = await add_category(db_session, name, FieldType.BOOLEAN)
        for day in days:
            await add_entry(db_session, category, flag, date(2026, 10, day), "true")

    names = [item["name"] for item in (await summary(client))["streaks"]]

    assert names == ["В", "А", "Б"]


# --- the rings -------------------------------------------------------------------


async def test_the_habits_ring_is_the_share_of_plan_items_done_in_the_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await close_day(db_session, date(2026, 10, 20), "won", done=4, total=4)
    await close_day(db_session, date(2026, 10, 29), "lost", done=1, total=4)
    await close_day(db_session, date(2026, 10, 30), "won", done=3, total=4)

    week = (await summary(client))["scores"]["habits"]
    month = (await summary(client, "month"))["scores"]["habits"]

    assert week == {"value": 50, "done": 4, "total": 8}
    assert month == {"value": 67, "done": 8, "total": 12}


async def test_days_without_plan_items_leave_the_habits_ring_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await close_day(db_session, date(2026, 10, 30), "won", done=0, total=0)

    assert (await summary(client))["scores"]["habits"] == {
        "value": None,
        "done": None,
        "total": None,
    }


async def add_challenge(
    db: AsyncSession,
    category: int,
    field: int,
    status: str,
    starts_on: date,
    ends_on: date,
) -> None:
    db.add(
        Challenge(
            title=f"c-{uuid4().hex[:6]}",
            category_id=category,
            field_id=field,
            rule_kind="checked",
            starts_on=starts_on,
            ends_on=ends_on,
            status=status,
        )
    )
    await db.commit()


async def test_the_challenges_ring_counts_won_of_those_running_in_the_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category, flag = await add_category(db_session, "Вода", FieldType.BOOLEAN)
    window = (date(2026, 10, 20), date(2026, 10, 27))
    await add_challenge(db_session, category, flag, "won", *window)
    await add_challenge(db_session, category, flag, "won", *window)
    await add_challenge(db_session, category, flag, "failed", *window)
    await add_challenge(
        db_session, category, flag, "active", date(2026, 10, 30), date(2026, 11, 5)
    )
    # Not counted: proposed, abandoned, over before the window, not started yet.
    await add_challenge(db_session, category, flag, "proposed", *window)
    await add_challenge(db_session, category, flag, "abandoned", *window)
    await add_challenge(
        db_session, category, flag, "won", date(2026, 9, 1), date(2026, 9, 7)
    )
    await add_challenge(
        db_session, category, flag, "active", date(2026, 11, 2), date(2026, 11, 9)
    )

    week = (await summary(client))["scores"]["challenges"]

    assert week == {"done": 2, "total": 4}


async def test_the_health_ring_is_the_closeness_to_the_personal_norm(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Steps are above the norm (1.0), sleep is a quarter under it (0.75), resting
    pulse is higher than it (60/66): the ring is the mean of the three shares.
    Today's steps are a half day and are left out of the average.
    """
    before = (date(2026, 10, 1), date(2026, 10, 24))
    inside = (WEEK_FROM, date(2026, 10, 30))
    await fill_metric(db_session, STEPS, *before, 10000)
    await fill_metric(db_session, STEPS, *inside, 12000)
    await add_health(db_session, STEPS, TODAY, 500)
    await fill_sleep(db_session, *before, 480)
    await fill_sleep(db_session, WEEK_FROM, TODAY, 360)
    await fill_metric(db_session, RESTING_HR, *before, 60)
    await fill_metric(db_session, RESTING_HR, WEEK_FROM, TODAY, 66)

    body = await summary(client)

    expected = round(100 * (1 + 0.75 + 60 / 66) / 3)
    assert body["scores"]["health"] == {
        "value": expected,
        "label": "good",
        "basis_days": 7,
    }
    states = {item["identifier"]: item for item in body["health"]}
    assert states[STEPS] == {
        "identifier": STEPS,
        "label": "Шаги",
        "value": 12000,
        "unit": "count",
        "baseline_delta": 2000,
        "higher_is_better": True,
    }
    assert (states[RESTING_HR]["value"], states[RESTING_HR]["baseline_delta"]) == (
        66,
        6,
    )
    sleep = states["HKCategoryTypeIdentifierSleepAnalysis"]
    assert (sleep["label"], sleep["unit"], sleep["value"], sleep["baseline_delta"]) == (
        "Сон",
        "min",
        360,
        -120,
    )


async def test_a_ring_far_under_the_norm_is_poor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_metric(db_session, STEPS, date(2026, 10, 1), date(2026, 10, 24), 10000)
    await fill_metric(db_session, STEPS, WEEK_FROM, date(2026, 10, 30), 3000)

    health = (await summary(client))["scores"]["health"]

    assert (health["value"], health["label"]) == (30, "poor")


async def test_fewer_than_three_days_of_data_leave_the_ring_null_but_show_the_days(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_metric(db_session, STEPS, date(2026, 10, 1), date(2026, 10, 24), 10000)
    await fill_metric(db_session, STEPS, date(2026, 10, 29), date(2026, 10, 30), 9000)

    body = await summary(client)

    assert body["scores"]["health"] == {"value": None, "label": None, "basis_days": 2}
    assert [item["value"] for item in body["health"]] == [9000]


async def test_without_a_norm_the_metric_is_shown_but_not_scored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Five days of data and no history: there is nothing to compare them with."""
    await fill_metric(db_session, STEPS, date(2026, 10, 25), date(2026, 10, 29), 8000)

    body = await summary(client)

    assert body["scores"]["health"] == {"value": None, "label": None, "basis_days": 0}
    assert body["health"][0]["baseline_delta"] is None


# --- bests -----------------------------------------------------------------------


async def test_a_best_day_is_a_record_only_if_nothing_in_ninety_days_beat_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_metric(db_session, STEPS, date(2026, 10, 1), date(2026, 10, 24), 10000)
    await fill_metric(db_session, STEPS, WEEK_FROM, date(2026, 10, 30), 11000)
    await add_health(db_session, STEPS, date(2026, 10, 28), 14220)

    [steps] = (await summary(client))["bests"]

    assert steps == {
        "identifier": STEPS,
        "label": "Шаги",
        "value": 14220,
        "unit": "count",
        "date": "2026-10-28",
        "is_record": True,
    }

    await add_health(db_session, STEPS, date(2026, 10, 3), 20000)
    [again] = (await summary(client))["bests"]

    assert (again["value"], again["is_record"]) == (14220, False)


async def test_for_the_resting_pulse_the_best_day_is_the_lowest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_metric(db_session, RESTING_HR, date(2026, 10, 1), date(2026, 10, 24), 62)
    await fill_metric(db_session, RESTING_HR, WEEK_FROM, date(2026, 10, 30), 60)
    await add_health(db_session, RESTING_HR, date(2026, 10, 27), 55)

    [best] = (await summary(client))["bests"]

    assert (best["value"], best["date"], best["is_record"]) == (55, "2026-10-27", True)


async def test_a_best_without_history_to_compare_is_not_called_a_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_metric(db_session, STEPS, date(2026, 10, 26), date(2026, 10, 28), 9000)

    [best] = (await summary(client))["bests"]

    assert best["is_record"] is False


# --- workouts --------------------------------------------------------------------


async def add_workout(db: AsyncSession, on: date, minutes: int) -> None:
    start = datetime.combine(on, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
        hours=10
    )
    await health_crud.upsert_workouts(
        db,
        [
            HealthWorkoutIn(
                uuid=uuid4(),
                activity_type="running",
                start=start,
                end=start + timedelta(minutes=minutes),
                utc_offset_minutes=0,
                duration_seconds=minutes * 60,
            )
        ],
    )
    await db.commit()


async def test_workouts_are_counted_by_week_and_against_the_previous_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for on, minutes in (
        (date(2026, 10, 8), 40),
        (date(2026, 10, 21), 50),
        (date(2026, 10, 26), 30),
        (date(2026, 10, 28), 45),
        (date(2026, 10, 29), 25),
    ):
        await add_workout(db_session, on, minutes)

    workouts = (await summary(client))["workouts"]

    assert workouts["weeks"] == [
        {"week_start": "2026-10-05", "count": 1, "minutes": 40},
        {"week_start": "2026-10-12", "count": 0, "minutes": 0},
        {"week_start": "2026-10-19", "count": 1, "minutes": 50},
        {"week_start": "2026-10-26", "count": 3, "minutes": 100},
    ]
    # 25..31 October holds three, 18..24 October holds one.
    assert (workouts["total"], workouts["delta_vs_previous"]) == (3, 2)


async def test_the_month_shows_eight_weeks(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_workout(db_session, date(2026, 10, 27), 30)

    weeks = (await summary(client, "month"))["workouts"]["weeks"]

    assert len(weeks) == 8
    assert weeks[0]["week_start"] == "2026-09-07"
    assert weeks[-1] == {"week_start": "2026-10-26", "count": 1, "minutes": 30}


# --- the insight -----------------------------------------------------------------


async def test_the_insight_compares_plan_on_well_slept_days_with_the_rest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for day, minutes, done in (
        (25, 480, 4),
        (26, 450, 4),
        (27, 360, 1),
        (28, 330, 2),
    ):
        on = date(2026, 10, day)
        await add_night(db_session, on, minutes)
        await close_day(db_session, on, "won", done=done, total=4)

    insight = (await summary(client))["insight"]

    assert insight["text"] == (
        "В дни со сном от 7 ч закрыто 100 % плана (2 дн.), в остальные — 38 % (2 дн.)."
    )
    assert datetime.fromisoformat(insight["generated_at"]).utcoffset() == timedelta(
        hours=1
    )


async def test_without_that_pattern_the_insight_names_the_longest_current_streak(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category, flag = await add_category(
        db_session, "Холодный душ", FieldType.BOOLEAN, avoid=False
    )
    for day in (29, 30, 31):
        await add_entry(db_session, category, flag, date(2026, 10, day), "true")

    insight = (await summary(client))["insight"]

    assert insight["text"] == "«Холодный душ» — 3 дн. подряд (лучший результат 3)."


async def test_with_nothing_to_say_the_insight_is_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category, flag = await add_category(db_session, "Йога", FieldType.BOOLEAN)
    await add_entry(db_session, category, flag, TODAY, "true")

    assert (await summary(client))["insight"] is None


async def test_the_dashboard_never_reaches_for_a_real_model(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the dashboard must not resolve an LLM client")

    monkeypatch.setattr(llm_client, "resolve_insights_client", forbidden)
    category, flag = await add_category(db_session, "Йога", FieldType.BOOLEAN)
    for day in (29, 30, 31):
        await add_entry(db_session, category, flag, date(2026, 10, day), "true")

    assert (await summary(client))["insight"] is not None


# --- the number of statements -----------------------------------------------------


async def count_statements(client: AsyncClient, period: str) -> int:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        await summary(client, period)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)
    return len(statements)


async def test_reading_the_dashboard_costs_the_same_with_two_categories_or_twenty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The class of error: a loop that asks the database once per category or per day.

    Read once with two categories and a day of data, and again after twenty
    categories, a month of entries, plan items, health, workouts and challenges.
    """
    avoid, avoid_flag = await add_category(
        db_session, "Срыв", FieldType.BOOLEAN, avoid=True
    )
    await add_entry(db_session, avoid, avoid_flag, TODAY, "true")
    build, build_flag = await add_category(db_session, "Зарядка", FieldType.BOOLEAN)
    await add_entry(db_session, build, build_flag, TODAY, "true")
    small = await count_statements(client, "month")

    for index in range(10):
        for avoiding in (True, False):
            category, flag = await add_category(
                db_session, f"К{index}-{avoiding}", FieldType.BOOLEAN, avoid=avoiding
            )
            for offset in range(0, 30, 3):
                await add_entry(
                    db_session, category, flag, TODAY - timedelta(days=offset), "true"
                )
    for day in days_between(date(2026, 9, 1), TODAY):
        await close_day(db_session, day, "won", done=2, total=3)
        await add_night(db_session, day, 420)
    await fill_metric(db_session, STEPS, date(2026, 9, 1), TODAY, 9000)
    await fill_metric(db_session, RESTING_HR, date(2026, 9, 1), TODAY, 60)
    await fill_metric(db_session, HRV, date(2026, 9, 1), TODAY, 40)
    for offset in range(0, 40, 4):
        await add_workout(db_session, TODAY - timedelta(days=offset), 30)
    await add_challenge(
        db_session, build, build_flag, "won", date(2026, 10, 20), date(2026, 10, 27)
    )
    large = await count_statements(client, "month")

    assert large == small
    assert large <= MAX_QUERIES


async def test_health_gives_all_five_key_metrics_with_the_direction_of_better(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The client reads `higher_is_better` instead of guessing it from the identifier."""
    energy = "HKQuantityTypeIdentifierActiveEnergyBurned"
    sleep = "HKCategoryTypeIdentifierSleepAnalysis"
    await fill_sleep(db_session, WEEK_FROM, TODAY, 420)
    for identifier in (STEPS, RESTING_HR, HRV, energy):
        await fill_metric(db_session, identifier, WEEK_FROM, date(2026, 10, 30), 50)

    states = {item["identifier"]: item for item in (await summary(client))["health"]}

    assert {i: s["higher_is_better"] for i, s in states.items()} == {
        sleep: True,
        RESTING_HR: False,
        HRV: True,
        STEPS: True,
        energy: True,
    }
    assert [s["label"] for s in states.values()] == [
        "Сон",
        "Пульс покоя",
        "Вариабельность пульса (SDNN)",
        "Шаги",
        "Активная энергия",
    ]


async def add_reviewed_day(db: AsyncSession, on: date, done: int, total: int) -> None:
    """The 15:40 touch: a row on stage `reviewed` with the numbers of that moment."""
    day = await day_crud.ensure_day(db, on)
    db.add(
        DaySummary(
            day_date=on,
            rule_set_id=day.rule_set_id,
            verdict=None,
            tasks_done=done,
            tasks_total=total,
            stage="reviewed",
        )
    )
    await db.commit()


async def test_a_day_that_is_not_closed_is_left_out_of_the_habits_ring_and_the_insight(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await close_day(db_session, date(2026, 10, 30), "won", done=4, total=4)
    await add_reviewed_day(db_session, TODAY, 1, 4)

    scores = (await summary(client))["scores"]

    assert scores["habits"] == {"value": 100, "done": 4, "total": 4}


async def test_an_unchecked_box_is_not_a_done_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unticking writes `false` and keeps the row: the day was not done."""
    category, flag = await add_category(db_session, "Зарядка", FieldType.BOOLEAN)
    await add_entry(db_session, category, flag, date(2026, 10, 29), "true")
    await add_entry(db_session, category, flag, date(2026, 10, 30), "false")

    [streak] = (await summary(client))["streaks"]

    assert streak["days"] == [None, None, None, None, True, False, None]
    assert (streak["current"], streak["best"]) == (0, 1)


async def test_a_category_with_only_unchecked_boxes_is_not_a_streak(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category, flag = await add_category(db_session, "Зарядка", FieldType.BOOLEAN)
    await add_entry(db_session, category, flag, date(2026, 10, 30), "false")

    assert (await summary(client))["streaks"] == []


async def test_days_of_a_metric_without_a_norm_are_not_the_basis_of_the_ring(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Six days of steps with no history and one day of pulse with a norm: one day."""
    await fill_metric(db_session, STEPS, WEEK_FROM, date(2026, 10, 30), 8000)
    await fill_metric(db_session, RESTING_HR, date(2026, 10, 1), date(2026, 10, 24), 60)
    await add_health(db_session, RESTING_HR, date(2026, 10, 29), 60)

    health = (await summary(client))["scores"]["health"]

    assert health == {"value": None, "label": None, "basis_days": 1}


async def test_the_record_window_is_exactly_ninety_days(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_metric(db_session, STEPS, date(2026, 10, 1), date(2026, 10, 24), 10000)
    await fill_metric(db_session, STEPS, WEEK_FROM, date(2026, 10, 30), 11000)
    await add_health(db_session, STEPS, date(2026, 10, 28), 14220)
    # 90 days ending today start on 3 August; 2 August is the 91st day back.
    await add_health(db_session, STEPS, date(2026, 8, 2), 20000)
    [outside] = (await summary(client))["bests"]
    await add_health(db_session, STEPS, date(2026, 8, 3), 20000)
    [inside] = (await summary(client))["bests"]

    assert (outside["is_record"], inside["is_record"]) == (True, False)


# --- the history read once; the health part alone (#309) -------------------------


async def add_habits(
    db: AsyncSession, count: int, days: int, prefix: str = "Х"
) -> None:
    """`count` avoid and `count` build habits, each with an entry on each of `days` days."""
    for index in range(count):
        for avoiding in (True, False):
            category, flag = await add_category(
                db, f"{prefix}{index}-{avoiding}", FieldType.BOOLEAN, avoid=avoiding
            )
            for offset in range(days):
                await add_entry(
                    db, category, flag, TODAY - timedelta(days=offset), "true"
                )


async def test_the_dashboard_reads_the_history_once_and_every_value_once(
    client: AsyncClient, db_session: AsyncSession, sql_counter: SqlCounter
) -> None:
    """
    The class of error: the history of every habit read once per streak mode.

    Avoid and build habits come out of one read of `entry_values`, and that read
    returns each stored value exactly once — not once per mode, not once per
    field of its category.
    """
    await add_habits(db_session, count=3, days=12)
    stored = (
        await db_session.execute(text("SELECT count(*) FROM entry_values"))
    ).scalar_one()

    with sql_counter() as seen:
        await summary(client, "month")

    assert seen.rows_of("entry_values") == [stored]


async def health_part(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(URL, params={"period": "week", "parts": "health"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def fill_health_week(db: AsyncSession) -> None:
    await fill_sleep(db, date(2026, 10, 1), TODAY, 420)
    await fill_metric(db, STEPS, date(2026, 10, 1), TODAY, 9000)
    await fill_metric(db, RESTING_HR, date(2026, 10, 1), TODAY, 60)


async def test_the_health_part_says_what_the_full_answer_says_about_health(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_health_week(db_session)
    await add_habits(db_session, count=2, days=5)

    full = await summary(client, "week")
    part = await health_part(client)

    assert part["scores"]["health"] == full["scores"]["health"]
    assert part["scores"]["health"]["value"] is not None
    assert (part["health"], part["bests"]) == (full["health"], full["bests"])
    assert (part["period"], part["from"], part["to"]) == (
        full["period"],
        full["from"],
        full["to"],
    )


async def test_the_health_part_leaves_the_other_blocks_empty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_habits(db_session, count=1, days=5)

    part = await health_part(client)

    assert part["streaks"] == []
    assert part["scores"]["habits"] == {"value": None, "done": None, "total": None}
    assert part["scores"]["challenges"] == {"done": None, "total": None}
    assert part["workouts"] == {"weeks": [], "total": None, "delta_vs_previous": None}
    assert part["insight"] is None


async def test_the_health_part_costs_the_same_whatever_the_habits(
    client: AsyncClient, db_session: AsyncSession, sql_counter: SqlCounter
) -> None:
    """
    The class of error: the health screen paying for the streaks of every habit.

    Statements and rows of the health part are the same with one pair of habits
    and with twenty pairs of a month each.
    """
    await fill_health_week(db_session)
    await add_habits(db_session, count=1, days=3)
    with sql_counter() as few:
        await health_part(client)

    await add_habits(db_session, count=20, days=30, prefix="Ещё")
    with sql_counter() as many:
        await health_part(client)

    assert (many.queries, many.rows) == (few.queries, few.rows)
    assert many.rows_of("entry_values") == []
