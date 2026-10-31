# [review:need-review] PHASE-03/221, PHASE-03/245, PHASE-03/255, PHASE-03/238, PHASE-03/244
# summary: PHASE-03/244 adds supplement adherence to the week review — the same numbers as the health summary, null without supplements, in the narrative prompt without a dose, behind the dose net, and a flat statement count
# summary: tests for the week review — totals, deltas against the same days of the previous week, best/worst day, role/category time, avoid streaks at the end of the counted window, health with sleep read from nights by wake date, the 04:00 boundary picking the current week, a read that writes nothing, a flat SQL statement count, the window counting today only once it is closed, the week verdict handed to the model ready-made, year-edge weeks, and the AI narrative through a fake client
"""
Weekly review: one answer for the whole week, cut on the day boundary.

The sentences the file is about. A week is Monday to Sunday of *logical* days, so
the night after Sunday still belongs to Sunday. A week that has not ended says so
and is compared with the same number of days of the previous one, not with all of
it. Reading the week costs the same number of SQL statements whether it holds one
habit and one day or ten habits and fourteen days. And the words of the review
come from the orchestration layer with a fake model in the test, never a real one.
"""

from collections.abc import AsyncGenerator, Generator
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core import daytime
from app.crud import day as day_crud
from app.crud import health as health_crud
from app.crud import role as role_crud
from app.crud import supplement_advice as advice_crud
from app.day.debt import week_verdict_line
from app.health.aggregate import HourBucket
from app.health.sleep import SleepNight
from app.llm.client import LLMClient, LLMError
from app.main import app
from app.models import Category, Entry, EntryValue, Field
from app.models.field import FieldType
from app.models.role import ROLE_CODE_CTO, ROLE_CODE_TECHLEAD
from app.models.summary import DaySummary
from app.models.week import Week
from tests.conftest import test_engine
from tests.test_health_advice import add_supplement, take

URL = "/api/v1/week-review"

# Monday 24 to Sunday 30 August 2026, and the week before it.
WEEK = "2026-W35"
PREVIOUS = "2026-W34"
MONDAY = date(2026, 8, 24)
SUNDAY = date(2026, 8, 30)
PREVIOUS_MONDAY = date(2026, 8, 17)

# What the review costs today is fifteen statements (two of them the supplements,
# #244); the ceiling leaves room for one more source without letting the count
# become a per-day or per-habit loop.
MAX_QUERIES = 16

STEPS = "HKQuantityTypeIdentifierStepCount"
EXERCISE = "HKQuantityTypeIdentifierAppleExerciseTime"


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """Rules, roles and the health catalogue as a migrated database has them."""
    await day_crud.seed_rules(db_session)
    await role_crud.seed_roles(db_session)
    await health_crud.seed_catalog(db_session)
    await db_session.commit()
    yield


async def close_day(
    db: AsyncSession,
    on: date,
    verdict: str | None,
    *,
    done: int = 0,
    total: int = 0,
    anchors: tuple[int, int] = (0, 0),
    work: int | None = None,
    streak: int | None = None,
) -> None:
    """A closed day as the close endpoint leaves it, written straight to the table."""
    day = await day_crud.ensure_day(db, on)
    db.add(
        DaySummary(
            day_date=on,
            rule_set_id=day.rule_set_id,
            verdict=verdict,
            tasks_done=done,
            tasks_total=total,
            anchors_done=anchors[0],
            anchors_total=anchors[1],
            work_minutes=work,
            streak_after=streak,
        )
    )
    await db.commit()


async def add_minutes(db: AsyncSession, on: date, code: str, minutes: int) -> None:
    """Minutes of a role, written the way the form writes them."""
    role = await role_crud.get_role_by_code(db, code)
    assert role is not None
    await role_crud.write_time_block(
        db, role_crud.TimeBlockDraft(work_day=on, role_id=role.id, minutes=minutes)
    )
    await db.commit()


async def add_category(
    db: AsyncSession, name: str, field_type: FieldType, *, avoid: bool = False
) -> tuple[int, int]:
    """A category with one field; answers with `(category_id, field_id)`."""
    category = Category(name=name, streak_mode="avoid" if avoid else "build")
    db.add(category)
    await db.flush()
    field = Field(category_id=category.id, name="v", field_type=field_type)
    db.add(field)
    await db.commit()
    return category.id, field.id


async def add_entry(
    db: AsyncSession, category_id: int, field_id: int, on: date, value: str
) -> None:
    """One entry with one value."""
    entry = Entry(category_id=category_id, entry_date=on)
    db.add(entry)
    await db.flush()
    db.add(EntryValue(entry_id=entry.id, field_id=field_id, value=value))
    await db.commit()


async def add_health(db: AsyncSession, identifier: str, on: date, value: float) -> None:
    """One hourly bucket of a catalogue metric, so the day folds to `value`."""
    metrics = {m.identifier: m for m in await health_crud.get_catalog(db)}
    await health_crud.upsert_buckets(
        db,
        metrics[identifier].id,
        [
            HourBucket(
                local_date=on,
                hour=12,
                value=value,
                sample_count=1,
                min_value=value,
                max_value=value,
                utc_offset_minutes=120,
            )
        ],
    )
    await db.commit()


async def add_night(db: AsyncSession, wake_date: date, asleep_min: float) -> None:
    """One night of sleep ending on `wake_date`, all of it core sleep."""
    wake = datetime.combine(wake_date, datetime.min.time(), tzinfo=timezone.utc)
    await health_crud.upsert_nights(
        db,
        [
            SleepNight(
                wake_date=wake_date,
                bedtime=wake - timedelta(minutes=asleep_min),
                wake_time=wake,
                utc_offset_minutes=0,
                in_bed_min=asleep_min,
                asleep_min=asleep_min,
                awake_min=0,
                core_min=asleep_min,
                deep_min=0,
                rem_min=0,
                unspecified_min=0,
            )
        ],
    )
    await db.commit()


async def get_week(client: AsyncClient, iso: str = WEEK) -> dict[str, Any]:
    response = await client.get(f"{URL}/{iso}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def fill_two_weeks(db: AsyncSession) -> None:
    """A previous week of two days and a current one of three, every number distinct."""
    # Previous week: Monday won 2/4, Tuesday lost 1/4.
    await close_day(db, PREVIOUS_MONDAY, "won", done=2, total=4, work=400, streak=1)
    await close_day(
        db, PREVIOUS_MONDAY + timedelta(days=1), "lost", done=1, total=4, streak=0
    )
    # This week: Monday won 4/4, Tuesday lost 1/4, Wednesday won 3/4.
    await close_day(
        db, MONDAY, "won", done=4, total=4, anchors=(2, 2), work=480, streak=1
    )
    await close_day(
        db, MONDAY + timedelta(days=1), "lost", done=1, total=4, work=300, streak=0
    )
    await close_day(
        db, MONDAY + timedelta(days=2), "won", done=3, total=4, work=420, streak=1
    )


# --- the window ---------------------------------------------------------------


async def test_a_finished_week_counts_all_seven_days(client: AsyncClient) -> None:
    body = await get_week(client)

    window = body["window"]
    assert (window["iso_code"], window["previous_iso_code"]) == (WEEK, PREVIOUS)
    assert window["next_iso_code"] == "2026-W36"
    assert (window["starts_on"], window["ends_on"]) == ("2026-08-24", "2026-08-30")
    assert window["is_complete"] is True
    assert (window["counted_days"], window["compared_days"]) == (7, 7)
    assert window["as_of"] == "2026-08-30"
    assert window["timezone"] == "Europe/Berlin"
    assert window["day_start_hour"] == 4
    assert [d["date"] for d in body["days"]] == [
        (MONDAY + timedelta(days=i)).isoformat() for i in range(7)
    ]


async def test_a_code_that_names_no_week_is_404(client: AsyncClient) -> None:
    response = await client.get(f"{URL}/2026-W99")
    assert response.status_code == 404


async def test_reading_a_week_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The retro snapshot is `/weeks`; the review is a read and leaves no row."""
    await get_week(client)

    count = (await db_session.execute(select(func.count()).select_from(Week))).scalar()
    assert count == 0


async def test_the_current_week_is_cut_on_the_day_boundary(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    03:59 Berlin on Monday is still Sunday's night, so the current week is the old one.

    04:00 is the new day, and the new week with it. The week is named by the
    server's boundary, never by the browser's calendar.
    """
    before = datetime(2026, 8, 31, 1, 59, tzinfo=timezone.utc)  # 03:59 in Berlin
    monkeypatch.setattr(daytime, "now_utc", lambda: before)
    old = (await client.get(URL)).json()["window"]
    assert old["iso_code"] == WEEK
    assert old["is_complete"] is False
    # Sunday itself is not closed yet, so the counted window ends on Saturday.
    assert old["as_of"] == "2026-08-29"

    after = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)  # 04:00 in Berlin
    monkeypatch.setattr(daytime, "now_utc", lambda: after)
    new = (await client.get(URL)).json()["window"]
    assert new["iso_code"] == "2026-W36"
    assert new["counted_days"] == 0


async def test_an_unfinished_week_is_compared_up_to_the_last_closed_day(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Wednesday noon with Monday and Tuesday closed: two days against two days.

    Wednesday has no итог yet, and counting it would put three days of the previous
    week in the denominator against two of this one — the week would look worse
    than it is every single day until the evening.
    """
    await close_day(db_session, MONDAY, "won", done=4, total=4)
    await close_day(db_session, MONDAY + timedelta(days=1), "lost", done=1, total=4)
    await close_day(db_session, PREVIOUS_MONDAY, "won", done=2, total=4)
    await close_day(
        db_session, PREVIOUS_MONDAY + timedelta(days=1), "lost", done=1, total=4
    )
    # The previous Wednesday is far outside the two days compared.
    await close_day(
        db_session, PREVIOUS_MONDAY + timedelta(days=2), "won", done=9, total=9
    )
    noon = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    body = (await client.get(URL)).json()

    window = body["window"]
    assert window["is_complete"] is False
    assert (window["counted_days"], window["compared_days"]) == (2, 2)
    assert window["as_of"] == "2026-08-25"
    assert body["previous_totals"]["tasks_total"] == 8
    assert body["totals"]["tasks_total"] == 8
    assert [d["counted"] for d in body["days"]] == [True] * 2 + [False] * 5


async def test_today_joins_the_window_once_it_is_closed(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await close_day(db_session, MONDAY, "won", done=4, total=4)
    await close_day(db_session, MONDAY + timedelta(days=1), "won", done=3, total=4)
    noon = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    window = (await client.get(URL)).json()["window"]

    assert (window["counted_days"], window["as_of"]) == (2, "2026-08-25")


async def test_a_reviewed_but_not_closed_today_is_not_counted(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 15:40 touch leaves `stage='reviewed'`: the day is still going."""
    day = await day_crud.ensure_day(db_session, MONDAY)
    db_session.add(
        DaySummary(day_date=MONDAY, rule_set_id=day.rule_set_id, stage="reviewed")
    )
    await db_session.commit()
    noon = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    window = (await client.get(URL)).json()["window"]

    assert (window["counted_days"], window["as_of"]) == (0, None)


async def test_days_after_today_are_not_counted_even_if_they_hold_data(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    await close_day(db_session, MONDAY + timedelta(days=3), "won", done=1, total=1)
    noon = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    body = (await client.get(URL)).json()

    assert body["totals"]["won_days"] == 1
    assert body["days"][3]["counted"] is False


async def test_the_window_says_whether_today_is_already_counted(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The screen decides its «today joins later» notes by this flag, not by guessing."""
    noon = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)
    await close_day(db_session, MONDAY, "won", done=1, total=1)

    open_today = (await client.get(URL)).json()["window"]
    await close_day(db_session, MONDAY + timedelta(days=1), "won", done=1, total=1)
    closed_today = (await client.get(URL)).json()["window"]

    assert open_today["today_counted"] is False
    assert closed_today["today_counted"] is True


async def test_today_is_the_logical_day_before_four_in_the_morning(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """03:30 on Wednesday is still Tuesday: Tuesday closed means today is counted."""
    night = datetime(2026, 8, 26, 1, 30, tzinfo=timezone.utc)  # 03:30 in Berlin
    monkeypatch.setattr(daytime, "now_utc", lambda: night)
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    assert (await client.get(URL)).json()["window"]["today_counted"] is False

    await close_day(db_session, MONDAY + timedelta(days=1), "won", done=1, total=1)
    window = (await client.get(URL)).json()["window"]

    assert (window["today_counted"], window["as_of"]) == (True, "2026-08-25")


async def test_a_finished_or_a_future_week_does_not_count_today(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    noon = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)
    assert (await get_week(client))["window"]["today_counted"] is False

    later = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: later)
    assert (await get_week(client))["window"]["today_counted"] is False


async def test_a_week_that_has_not_started_is_empty_not_an_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    noon = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    body = await get_week(client)

    assert body["window"]["counted_days"] == 0
    assert body["window"]["as_of"] is None
    assert body["totals"]["closed_days"] == 0


# --- totals, comparison, best and worst day ------------------------------------


async def test_totals_are_added_up_and_compared_with_the_previous_week(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_two_weeks(db_session)

    body = await get_week(client)

    totals = body["totals"]
    assert (totals["closed_days"], totals["won_days"], totals["lost_days"]) == (3, 2, 1)
    assert (totals["tasks_done"], totals["tasks_total"]) == (8, 12)
    assert totals["plan_pct"] == 67
    assert (totals["anchors_done"], totals["anchors_total"]) == (2, 2)
    assert totals["work_minutes"] == 1200
    assert totals["day_streak_end"] == 1
    previous = body["previous_totals"]
    assert (previous["won_days"], previous["tasks_done"]) == (1, 3)
    assert previous["plan_pct"] == 38
    assert previous["work_minutes"] == 400
    assert body["delta"]["won_days"] == 1
    assert body["delta"]["tasks_done"] == 5
    assert body["delta"]["plan_pct"] == 29
    assert body["delta"]["work_minutes"] == 800


async def test_a_week_without_data_answers_null_not_zero(client: AsyncClient) -> None:
    body = await get_week(client)

    totals = body["totals"]
    assert totals["plan_pct"] is None
    assert totals["work_minutes"] is None
    assert totals["day_streak_end"] is None
    assert body["delta"]["plan_pct"] is None
    assert body["delta"]["work_minutes"] is None
    assert body["best_day"] is None and body["worst_day"] is None
    assert body["categories"] == [] and body["habit_streaks"] == []


async def test_the_best_day_is_won_with_the_fuller_plan_and_the_worst_is_lost(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_two_weeks(db_session)

    body = await get_week(client)

    assert body["best_day"] == "2026-08-24"  # won, 4/4
    assert body["worst_day"] == "2026-08-25"  # lost, 1/4


async def test_one_judged_day_is_best_and_has_no_worst(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)

    body = await get_week(client)

    assert body["best_day"] == "2026-08-24"
    assert body["worst_day"] is None


async def test_days_that_tie_have_no_worst(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for offset in range(2):
        await close_day(
            db_session, MONDAY + timedelta(days=offset), "won", done=2, total=2
        )

    body = await get_week(client)

    assert body["best_day"] == "2026-08-24"
    assert body["worst_day"] is None


async def test_a_day_is_reported_with_its_own_plan_share(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_two_weeks(db_session)

    day = (await get_week(client))["days"][2]

    assert day["verdict"] == "won"
    assert (day["tasks_done"], day["tasks_total"], day["plan_pct"]) == (3, 4, 75)
    assert day["work_minutes"] == 420


# --- roles, categories, streaks, health ----------------------------------------


async def test_role_time_is_split_and_compared_with_the_previous_week(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_minutes(db_session, MONDAY, ROLE_CODE_TECHLEAD, 300)
    await add_minutes(db_session, SUNDAY, ROLE_CODE_CTO, 100)
    await add_minutes(db_session, PREVIOUS_MONDAY, ROLE_CODE_TECHLEAD, 100)
    # Sunday night before the week and Monday after it belong to neither.
    await add_minutes(db_session, MONDAY - timedelta(days=1), ROLE_CODE_CTO, 999)
    await add_minutes(db_session, SUNDAY + timedelta(days=1), ROLE_CODE_CTO, 999)

    body = await get_week(client)

    by_code = {r["role_code"]: r for r in body["roles"]}
    assert (by_code["techlead"]["minutes"], by_code["techlead"]["share_pct"]) == (
        300,
        75,
    )
    assert by_code["techlead"]["previous_minutes"] == 100
    assert by_code["techlead"]["delta_minutes"] == 200
    assert by_code["cto"]["minutes"] == 100
    assert body["totals"]["role_minutes"] == 400
    assert body["days"][6]["role_minutes"] == 100


async def test_category_time_sums_duration_fields_and_counts_logged_days(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    run, run_field = await add_category(db_session, "Бег", FieldType.DURATION)
    water, water_field = await add_category(db_session, "Вода", FieldType.NUMBER)
    await add_entry(db_session, run, run_field, MONDAY, "1800")
    await add_entry(db_session, run, run_field, MONDAY, "600")
    await add_entry(db_session, run, run_field, SUNDAY, "1200")
    await add_entry(db_session, run, run_field, PREVIOUS_MONDAY, "900")
    await add_entry(db_session, water, water_field, MONDAY, "500")

    body = await get_week(client)

    (only,) = body["categories"]
    assert only["name"] == "Бег"
    assert only["minutes"] == 60  # 3600 s
    assert only["previous_minutes"] == 15
    assert only["delta_minutes"] == 45
    assert (only["entry_days"], only["previous_entry_days"]) == (2, 1)


async def test_avoid_streak_is_counted_to_the_end_of_the_window_not_to_today(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    smoke, flag = await add_category(
        db_session, "Курение", FieldType.BOOLEAN, avoid=True
    )
    await add_entry(db_session, smoke, flag, MONDAY - timedelta(days=2), "false")
    await add_entry(db_session, smoke, flag, MONDAY + timedelta(days=2), "true")
    # A relapse after the week must not shorten the streak of the week itself.
    await add_entry(db_session, smoke, flag, SUNDAY + timedelta(days=3), "true")

    body = await get_week(client)

    (streak,) = body["habit_streaks"]
    assert streak["name"] == "Курение"
    assert streak["current_streak"] == 4  # Wednesday relapse, Sunday is day four
    assert streak["relapses"] == 1


async def test_an_avoid_category_not_yet_tracked_is_left_out(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    smoke, flag = await add_category(
        db_session, "Курение", FieldType.BOOLEAN, avoid=True
    )
    await add_entry(db_session, smoke, flag, SUNDAY + timedelta(days=5), "true")

    assert (await get_week(client))["habit_streaks"] == []


async def test_health_is_compared_day_by_day_and_sleep_reads_nights_by_wake_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_night(db_session, MONDAY + timedelta(days=2), 420)
    await add_night(db_session, PREVIOUS_MONDAY, 480)
    await add_health(db_session, STEPS, MONDAY, 8000)
    await add_health(db_session, STEPS, MONDAY + timedelta(days=1), 4000)
    await add_health(db_session, STEPS, PREVIOUS_MONDAY, 3000)
    await add_health(db_session, EXERCISE, SUNDAY, 45)

    body = await get_week(client)

    health = {m["key"]: m for m in body["health"]}
    steps = health["steps"]
    assert steps["available"] is True
    assert (steps["total"], steps["avg_per_day"], steps["days_with_data"]) == (
        12000,
        6000,
        2,
    )
    assert steps["previous_avg_per_day"] == 3000
    assert steps["previous_days_with_data"] == 1
    assert steps["delta_avg_per_day"] == 3000
    assert steps["daily"] == [8000, 4000, None, None, None, None, None]
    workouts = health["workouts"]
    assert (workouts["total"], workouts["unit"]) == (45, "min")
    assert workouts["daily"][6] == 45
    # Sleep is minutes asleep of the night that ended that day; a day without a
    # night is "нет данных", not "спал ноль часов".
    sleep = health["sleep"]
    assert (sleep["available"], sleep["unit"]) == (True, "min")
    assert sleep["daily"] == [None, None, 420, None, None, None, None]
    assert (sleep["avg_per_day"], sleep["days_with_data"]) == (420, 1)
    assert sleep["previous_avg_per_day"] == 480
    assert sleep["delta_avg_per_day"] == -60


async def test_role_shares_are_the_ones_of_the_weekly_role_summary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """One implementation of a share: the review must agree with `/roles/summary`."""
    await add_minutes(db_session, MONDAY, ROLE_CODE_TECHLEAD, 5)
    await add_minutes(db_session, MONDAY + timedelta(days=1), ROLE_CODE_CTO, 3)
    summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

    body = await get_week(client)

    ours = {r["role_code"]: r["share_pct"] for r in body["roles"]}
    theirs = {one.role_code: one.share_pct for one in summary.roles}
    assert ours == theirs
    assert body["totals"]["role_minutes"] == summary.total_minutes


async def test_the_workouts_metric_keeps_the_name_the_catalogue_gave_it(
    client: AsyncClient,
) -> None:
    health = {m["key"]: m for m in (await get_week(client))["health"]}

    assert health["workouts"]["name"] == "Минуты тренировки"
    assert health["steps"]["name"] == "Шаги"


# --- the verdict of the week, and the edge of a year ---------------------------


async def test_a_finished_week_is_won_by_the_one_rule_of_the_week(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Every day won, days exist, no debt: the rule of `/weeks`, not a second one."""
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    await close_day(db_session, MONDAY + timedelta(days=1), "won", done=1, total=1)

    body = await get_week(client)

    assert body["is_won"] is True
    assert body["debt_minutes"] == 0
    assert body["totals"]["days_total"] == 2


async def test_a_running_week_has_no_verdict_yet(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    noon = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    assert (await client.get(URL)).json()["is_won"] is None


async def test_the_week_of_the_new_year_is_the_day_after_the_old_one(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2027-01-01 belongs to `2026-W53`; `2027-W01` starts on Monday 4 January."""
    later = datetime(2027, 1, 12, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: later)
    await close_day(db_session, date(2026, 12, 28), "won", done=2, total=2)
    await close_day(db_session, date(2027, 1, 4), "won", done=1, total=1)

    body = await get_week(client, "2027-W01")

    window = body["window"]
    assert (window["starts_on"], window["ends_on"]) == ("2027-01-04", "2027-01-10")
    assert window["previous_iso_code"] == "2026-W53"
    assert window["next_iso_code"] == "2027-W02"
    assert body["totals"]["tasks_total"] == 1
    # 2026-12-28 is the Monday of 2026-W53, and it is what the new year is compared to.
    assert body["previous_totals"]["tasks_total"] == 2

    old = (await get_week(client, "2026-W53"))["window"]
    assert (old["next_iso_code"], old["previous_iso_code"]) == ("2027-W01", "2026-W52")


# --- the number of statements --------------------------------------------------


async def count_statements(client: AsyncClient) -> int:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        await get_week(client)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)
    return len(statements)


async def test_reading_the_week_costs_the_same_with_one_habit_or_ten(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The class of error: a loop that asks the database once per day or per habit.

    The week is read once while it holds a single day and a single category, and
    again after fourteen days, ten duration categories, ten avoid categories and
    health on every day have been added. The count must not move.
    """
    run, run_field = await add_category(db_session, "Бег", FieldType.DURATION)
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    await add_entry(db_session, run, run_field, MONDAY, "600")
    small = await count_statements(client)

    for offset in range(14):
        on = PREVIOUS_MONDAY + timedelta(days=offset)
        if on != MONDAY:
            await close_day(db_session, on, "won", done=offset, total=offset + 1)
        await add_minutes(db_session, on, ROLE_CODE_TECHLEAD, 60 + offset)
        await add_health(db_session, STEPS, on, 1000 + offset)
        await add_health(db_session, EXERCISE, on, 10 + offset)
    for index in range(10):
        category, field = await add_category(
            db_session, f"Привычка {index}", FieldType.DURATION
        )
        await add_entry(
            db_session, category, field, MONDAY + timedelta(days=index % 7), "60"
        )
        smoke, flag = await add_category(
            db_session, f"Срыв {index}", FieldType.BOOLEAN, avoid=True
        )
        await add_entry(
            db_session, smoke, flag, MONDAY + timedelta(days=index % 7), "true"
        )
    large = await count_statements(client)

    assert large == small
    assert large <= MAX_QUERIES


# --- the narrative through the orchestration layer ------------------------------


class FakeLLM(LLMClient):
    """A model that answers with a canned text and remembers what it was asked."""

    model = "fake-model"

    def __init__(self, text: str = "Неделя прошла ровно.") -> None:
        self.text = text
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


class FailingLLM(LLMClient):
    async def generate(self, prompt: str) -> str:
        raise LLMError("upstream")


@pytest.fixture
def llm() -> Generator[FakeLLM, None, None]:
    fake = FakeLLM()
    app.dependency_overrides[get_llm_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_llm_client, None)


async def test_the_narrative_is_written_from_the_numbers_of_the_week(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_two_weeks(db_session)

    response = await client.post(f"{URL}/{WEEK}/narrative")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["iso_code"], body["text"], body["model"]) == (
        WEEK,
        "Неделя прошла ровно.",
        "fake-model",
    )
    (prompt,) = llm.prompts
    assert "2 из 3" in prompt  # won days of closed days
    assert "8 из 12" in prompt  # tasks


async def test_the_prompt_tells_the_model_the_week_is_not_over(
    client: AsyncClient,
    db_session: AsyncSession,
    llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await fill_two_weeks(db_session)
    noon = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    response = await client.post(f"{URL}/{WEEK}/narrative")

    assert response.status_code == 200
    assert "не закончилась" in llm.prompts[0]


async def test_a_week_with_nothing_in_it_does_not_reach_the_model(
    client: AsyncClient, llm: FakeLLM
) -> None:
    response = await client.post(f"{URL}/{WEEK}/narrative")

    assert response.status_code == 422
    assert llm.prompts == []


async def test_no_backend_is_503_and_a_failing_one_is_502(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_two_weeks(db_session)

    app.dependency_overrides[get_llm_client] = lambda: None
    try:
        assert (await client.post(f"{URL}/{WEEK}/narrative")).status_code == 503
        app.dependency_overrides[get_llm_client] = lambda: FailingLLM()
        assert (await client.post(f"{URL}/{WEEK}/narrative")).status_code == 502
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


async def test_the_narrative_of_a_bad_code_is_404(
    client: AsyncClient, llm: FakeLLM
) -> None:
    response = await client.post(f"{URL}/2026-W99/narrative")

    assert response.status_code == 404
    assert llm.prompts == []


async def test_the_model_is_told_the_verdict_not_asked_for_it(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    """Five won days of six is «нет» in the data of the prompt, by the rule of the week."""
    for offset in range(5):
        await close_day(
            db_session, MONDAY + timedelta(days=offset), "won", done=1, total=1
        )
    await close_day(db_session, MONDAY + timedelta(days=5), "lost", done=0, total=1)

    response = await client.post(f"{URL}/{WEEK}/narrative")

    assert response.status_code == 200
    (prompt,) = llm.prompts
    assert "Неделя выиграна: нет" in prompt
    assert "выиграно 5 из 6 дней" in prompt


async def test_the_prompt_says_a_won_week_is_won(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)

    await client.post(f"{URL}/{WEEK}/narrative")

    assert "Неделя выиграна: да" in llm.prompts[0]


async def test_the_prompt_names_steps_in_russian_and_workouts_as_the_catalogue_does(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await add_health(db_session, STEPS, MONDAY, 8000)
    await add_health(db_session, EXERCISE, MONDAY, 45)

    await client.post(f"{URL}/{WEEK}/narrative")

    prompt = llm.prompts[0]
    assert "8000 шагов" in prompt
    assert "count" not in prompt
    assert "Минуты тренировки: в среднем 0 ч 45 мин" in prompt
    # The denominator of the average is named: days with data, not all days.
    assert "по дням с данными: 1 из" in prompt


async def test_the_prompt_names_the_days_behind_the_previous_average(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    """«+4000 шагов к прошлой неделе» is only as good as the 2 days of 7 behind it."""
    await add_health(db_session, STEPS, MONDAY, 8000)
    await add_health(db_session, STEPS, PREVIOUS_MONDAY, 3000)
    await add_health(db_session, STEPS, PREVIOUS_MONDAY + timedelta(days=1), 5000)

    await client.post(f"{URL}/{WEEK}/narrative")

    assert "+4000 шагов к прошлой неделе, против 2 из 7 дн." in llm.prompts[0]


async def test_the_word_average_is_said_once_per_health_line(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await add_health(db_session, STEPS, MONDAY, 8000)

    await client.post(f"{URL}/{WEEK}/narrative")

    (line,) = [ln for ln in llm.prompts[0].splitlines() if ln.startswith("Шаги:")]
    assert line.count("средн") == 1


async def test_the_verdict_line_of_the_screen_is_the_sentence_the_model_retells(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    """One sentence, written once; with nothing owed the screen and the model read it alike."""
    for offset in range(5):
        await close_day(
            db_session, MONDAY + timedelta(days=offset), "won", done=1, total=1
        )
    await close_day(db_session, MONDAY + timedelta(days=5), "lost", done=0, total=1)

    body = await get_week(client)
    await client.post(f"{URL}/{WEEK}/narrative")

    assert body["verdict_line"] == (
        "Неделя выиграна: нет (правило: выиграны все дни недели и нет долга за "
        "переработку; выиграно 5 из 6 дней, долг 0 мин)."
    )
    assert body["verdict_line"] in llm.prompts[0]


@pytest.mark.parametrize(
    ("debt", "screen", "prompt"),
    [
        (0, "долг 0 мин", "долг 0 мин"),
        (30, "долг 30 мин", "долг 30 мин"),
        (65, "долг 1 ч 05 мин", "долг 65 мин"),
        (90, "долг 1 ч 30 мин", "долг 90 мин"),
        (120, "долг 2 ч", "долг 120 мин"),
    ],
)
def test_the_debt_is_hours_on_the_screen_and_minutes_in_the_prompt(
    debt: int, screen: str, prompt: str
) -> None:
    on_screen = week_verdict_line(False, 6, 6, debt, as_hours=True)
    to_model = week_verdict_line(False, 6, 6, debt, as_hours=False)

    assert screen in on_screen
    assert prompt in to_model
    assert on_screen.replace(screen, prompt) == to_model


def test_a_week_that_runs_has_the_same_undecided_line_everywhere() -> None:
    assert week_verdict_line(None, 0, 0, 0, as_hours=True) == week_verdict_line(
        None, 0, 0, 0, as_hours=False
    )


async def test_a_running_week_says_its_verdict_is_not_decided(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    noon = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: noon)

    body = (await client.get(URL)).json()

    assert body["verdict_line"] == "Неделя выиграна: пока не решено, неделя идёт."


async def test_a_week_with_only_a_habit_streak_still_has_something_to_say(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    smoke, flag = await add_category(
        db_session, "Курение", FieldType.BOOLEAN, avoid=True
    )
    await add_entry(db_session, smoke, flag, MONDAY - timedelta(days=2), "false")

    response = await client.post(f"{URL}/{WEEK}/narrative")

    assert response.status_code == 200
    assert "Курение" in llm.prompts[0]


# --- supplements and sport in the week (#244) ------------------------------------

SUPPLEMENT_START = MONDAY - timedelta(days=30)
WEEK_DAYS = [MONDAY + timedelta(days=offset) for offset in range(7)]


async def add_magnesium(db: AsyncSession, taken_days: int) -> None:
    supplement = await add_supplement(db, "Магний цитрат", SUPPLEMENT_START)
    await take(db, supplement, *WEEK_DAYS[:taken_days])


async def test_a_week_without_supplements_is_the_week_it_was(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_two_weeks(db_session)

    body = await get_week(client)
    await client.post(f"{URL}/{WEEK}/narrative")

    assert body["supplements"] is None
    assert "Добавки" not in llm.prompts[0]


async def test_the_week_carries_what_was_taken_of_what_was_planned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_magnesium(db_session, taken_days=3)

    body = await get_week(client)

    supplements = body["supplements"]
    assert (supplements["planned"], supplements["taken"], supplements["pct"]) == (
        7,
        3,
        43,
    )
    assert [day["taken"] for day in supplements["days"]] == [1, 1, 1, 0, 0, 0, 0]
    assert supplements["supplements"] == [
        {
            "supplement_id": supplements["supplements"][0]["supplement_id"],
            "name": "Магний цитрат",
            "planned_days": 7,
            "taken_days": 3,
        }
    ]


async def test_the_week_counts_adherence_by_the_one_calculation_of_the_advice(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The week 24-30 August is the window of seven days on 31 August."""
    await add_magnesium(db_session, taken_days=5)
    monday_after = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: monday_after)

    body = await get_week(client)
    summary = await advice_crud.build_health_summary(db_session, 7, date(2026, 8, 31))

    assert body["supplements"] == summary.adherence.model_dump(mode="json")


async def test_a_running_week_counts_adherence_over_the_counted_days_only(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_magnesium(db_session, taken_days=2)
    wednesday = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(daytime, "now_utc", lambda: wednesday)

    body = await get_week(client)

    assert body["window"]["counted_days"] == 2
    assert (body["supplements"]["planned"], body["supplements"]["taken"]) == (2, 2)


async def test_the_narrative_is_told_adherence_by_name_and_never_a_dose(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_two_weeks(db_session)
    await add_magnesium(db_session, taken_days=3)

    response = await client.post(f"{URL}/{WEEK}/narrative")

    assert response.status_code == 200
    (prompt,) = llm.prompts
    assert "Добавки: принято 3 из 7 запланированных приёмов (43%)." in prompt
    assert "«Магний цитрат»: 3 из 7 дн." in prompt
    assert "777" not in prompt


async def test_a_narrative_that_names_a_dose_is_dropped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_two_weeks(db_session)
    await add_magnesium(db_session, taken_days=3)
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM(
        "Неделя ровная. Магний по 400 мг продолжай."
    )
    try:
        response = await client.post(f"{URL}/{WEEK}/narrative")
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 502
    assert response.json()["detail"] == "Совет отклонён защитой."
    assert "400" not in response.text


async def test_reading_the_week_costs_the_same_with_one_supplement_or_eight(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await close_day(db_session, MONDAY, "won", done=1, total=1)
    await add_magnesium(db_session, taken_days=1)
    small = await count_statements(client)

    for index in range(7):
        supplement = await add_supplement(
            db_session, f"Добавка {index}", SUPPLEMENT_START
        )
        await take(db_session, supplement, *WEEK_DAYS[index % 3 :])
    large = await count_statements(client)

    assert large == small
    assert large <= MAX_QUERIES
