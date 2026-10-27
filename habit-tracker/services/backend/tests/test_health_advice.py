# [review:need-review] PHASE-03/223
# summary: tests for the health summary and the advice built on it — steps, workout minutes and resting heart rate against the previous window, sleep honestly «данных нет», supplement adherence per day, the window closed by yesterday, a flat SQL statement count, «данных мало» instead of an invented advice, the fixed disclaimer, 422/503/502, and no supplement name or health value in a log line
"""
Advice from sleep, sport and supplements (`#223`).

The sentences the file is about. The summary covers the `days` logical days that
are over (today is not, it can still be lived), and compares them with the same
number of days before. Sleep has no metric in the catalogue yet, and the summary
says «данных нет» instead of a zero. With too little data the advice is not
written at all. When it is written, the model sees numbers (never a dose), the
answer always ends with «не медицинская рекомендация», and nothing the person
takes or measures reaches a log line. The model is a fake in every test.
"""

import logging
from collections.abc import AsyncGenerator, Generator
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.core import daytime
from app.crud import health as health_crud
from app.health.aggregate import HourBucket
from app.llm.client import LLMClient, LLMError
from app.llm.health_advice import NOT_MEDICAL_ADVICE
from app.main import app
from app.models.supplement import Supplement, SupplementIntake
from tests.conftest import test_engine

SUMMARY_URL = "/api/v1/health-advice/summary"
ADVICE_URL = "/api/v1/health-advice"

# Tuesday 27 October 2026, 11:00 in Berlin. The window of seven days is 20-26
# October, the one before it 13-19 October.
NOON = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
FIRST_DAY = date(2026, 10, 20)
LAST_DAY = date(2026, 10, 26)
PREVIOUS_FIRST_DAY = date(2026, 10, 13)

STEPS = "HKQuantityTypeIdentifierStepCount"
EXERCISE = "HKQuantityTypeIdentifierAppleExerciseTime"
RESTING = "HKQuantityTypeIdentifierRestingHeartRate"

# What the summary reads: supplements, intakes, the catalogue, the daily values.
MAX_QUERIES = 6

MAGNESIUM = "Магний цитрат"
D3 = "Витамин D3"


@pytest.fixture(autouse=True)
async def seeded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[None, None]:
    """The health catalogue as a migrated database has it, and a pinned clock."""
    monkeypatch.setattr(daytime, "now_utc", lambda: NOON)
    await health_crud.seed_catalog(db_session)
    await db_session.commit()
    yield


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
                utc_offset_minutes=60,
            )
        ],
    )
    await db.commit()


async def add_supplement(
    db: AsyncSession,
    name: str,
    created: date,
    *,
    archived: datetime | None = None,
) -> int:
    supplement = Supplement(
        name=name,
        dose=200,
        unit="мг",
        intake_time=time(21, 30),
        created_at=datetime.combine(created, time(12), tzinfo=timezone.utc),
        archived_at=archived,
    )
    db.add(supplement)
    await db.commit()
    return supplement.id


async def take(db: AsyncSession, supplement_id: int, *days: date) -> None:
    for day in days:
        db.add(
            SupplementIntake(
                supplement_id=supplement_id,
                intake_date=day,
                taken_at=datetime.combine(day, time(20), tzinfo=timezone.utc),
            )
        )
    await db.commit()


async def fill_window(db: AsyncSession) -> None:
    """
    Every number distinct, so a swapped pair of fields cannot pass.

    Steps average 8000 against 7000 (+1000). Workouts: 30 min on four days
    against 20 min on two. Resting heart rate: 60 on five days against 64 on five.
    Magnesium is planned all seven days and taken on five; D3 was started on the
    22nd, so it is planned five days and taken two.
    """
    for offset, steps in enumerate([6000, 7000, 8000, 9000, 10000, 8000, 8000]):
        await add_health(db, STEPS, FIRST_DAY + timedelta(days=offset), steps)
        await add_health(db, STEPS, PREVIOUS_FIRST_DAY + timedelta(days=offset), 7000)
    for offset in range(4):
        await add_health(db, EXERCISE, FIRST_DAY + timedelta(days=offset), 30)
    for offset in range(2):
        await add_health(db, EXERCISE, PREVIOUS_FIRST_DAY + timedelta(days=offset), 20)
    for offset in range(5):
        await add_health(db, RESTING, FIRST_DAY + timedelta(days=offset), 60)
        await add_health(db, RESTING, PREVIOUS_FIRST_DAY + timedelta(days=offset), 64)

    magnesium = await add_supplement(db, MAGNESIUM, date(2026, 10, 1))
    d3 = await add_supplement(db, D3, date(2026, 10, 22))
    await take(db, magnesium, *[FIRST_DAY + timedelta(days=i) for i in (0, 1, 2, 4, 5)])
    await take(db, d3, date(2026, 10, 22), date(2026, 10, 23))


async def get_summary(client: AsyncClient, days: int = 7) -> dict[str, Any]:
    response = await client.get(SUMMARY_URL, params={"days": days})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def figure(body: dict[str, Any], key: str) -> dict[str, Any]:
    (found,) = [f for f in body["figures"] if f["key"] == key]
    return found


# --- the summary ----------------------------------------------------------------


async def test_the_window_is_the_days_that_are_over(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await get_summary(client)

    window = body["window"]
    assert (window["starts_on"], window["ends_on"], window["days"]) == (
        "2026-10-20",
        "2026-10-26",
        7,
    )
    assert (window["previous_starts_on"], window["previous_ends_on"]) == (
        "2026-10-13",
        "2026-10-19",
    )


async def test_today_is_not_in_the_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_health(db_session, STEPS, date(2026, 10, 27), 99999)
    await add_health(db_session, STEPS, LAST_DAY, 5000)

    steps = figure(await get_summary(client), "steps")

    assert (steps["days_with_data"], steps["avg_per_day"]) == (1, 5000)


async def test_the_window_follows_the_day_boundary(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At 03:30 the logical day is still the 26th, so the window ends on the 25th."""
    monkeypatch.setattr(
        daytime, "now_utc", lambda: datetime(2026, 10, 27, 2, 30, tzinfo=timezone.utc)
    )

    body = await get_summary(client)

    assert body["window"]["ends_on"] == "2026-10-25"


async def test_steps_workouts_and_resting_heart_rate_against_the_previous_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_window(db_session)

    body = await get_summary(client)

    steps = figure(body, "steps")
    assert (steps["avg_per_day"], steps["previous_avg_per_day"]) == (8000, 7000)
    assert (steps["delta_avg_per_day"], steps["days_with_data"]) == (1000, 7)
    workouts = figure(body, "workouts")
    assert (workouts["avg_per_day"], workouts["previous_avg_per_day"]) == (30, 20)
    assert (workouts["delta_avg_per_day"], workouts["days_with_data"]) == (10, 4)
    resting = figure(body, "resting_hr")
    assert (resting["avg_per_day"], resting["previous_avg_per_day"]) == (60, 64)
    assert resting["delta_avg_per_day"] == -4


async def test_names_and_units_come_from_the_catalogue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await get_summary(client)

    assert figure(body, "workouts")["name"] == "Минуты тренировки"
    assert figure(body, "workouts")["unit"] == "min"
    assert figure(body, "resting_hr")["name"] == "Пульс покоя"


async def test_sleep_says_no_data_instead_of_a_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_window(db_session)

    sleep = figure(await get_summary(client), "sleep")

    assert sleep["available"] is False
    assert sleep["enough_data"] is False
    assert sleep["avg_per_day"] is None
    assert sleep["days_with_data"] == 0


async def test_a_gap_in_the_previous_window_is_no_comparison_not_a_drop(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_health(db_session, STEPS, LAST_DAY, 5000)

    steps = figure(await get_summary(client), "steps")

    assert steps["previous_avg_per_day"] is None
    assert steps["delta_avg_per_day"] is None


async def test_adherence_is_taken_over_planned_by_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_window(db_session)

    adherence = (await get_summary(client))["adherence"]

    assert (adherence["planned"], adherence["taken"], adherence["pct"]) == (12, 7, 58)
    assert [(d["planned"], d["taken"]) for d in adherence["days"]] == [
        (1, 1),
        (1, 1),
        (2, 2),
        (2, 1),
        (2, 1),
        (2, 1),
        (2, 0),
    ]
    assert [d["date"] for d in adherence["days"]][0] == "2026-10-20"
    by_name = {s["name"]: s for s in adherence["supplements"]}
    assert (by_name[MAGNESIUM]["planned_days"], by_name[MAGNESIUM]["taken_days"]) == (
        7,
        5,
    )
    assert (by_name[D3]["planned_days"], by_name[D3]["taken_days"]) == (5, 2)


async def test_an_archived_supplement_is_planned_only_until_the_day_it_left(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_supplement(
        db_session,
        MAGNESIUM,
        date(2026, 10, 1),
        archived=datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc),
    )

    adherence = (await get_summary(client))["adherence"]

    # The 20th, 21st and 22nd; nothing after the day it was archived.
    assert (adherence["planned"], adherence["taken"]) == (3, 0)


async def test_a_supplement_not_yet_started_is_not_planned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await add_supplement(db_session, MAGNESIUM, date(2026, 10, 27))

    adherence = (await get_summary(client))["adherence"]

    assert (adherence["planned"], adherence["pct"]) == (0, None)


async def test_a_mark_outside_the_planned_days_still_counts_as_planned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Taken can never exceed planned: an archived supplement taken that day is planned."""
    archived = await add_supplement(
        db_session,
        MAGNESIUM,
        date(2026, 10, 1),
        archived=datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc),
    )
    await take(db_session, archived, date(2026, 10, 23))

    adherence = (await get_summary(client))["adherence"]

    assert adherence["taken"] <= adherence["planned"]
    assert (adherence["planned"], adherence["taken"]) == (3, 1)


async def test_an_empty_summary_is_empty_and_not_enough(client: AsyncClient) -> None:
    body = await get_summary(client)

    assert body["enough_data"] is False
    assert all(f["days_with_data"] == 0 for f in body["figures"])
    assert body["adherence"]["planned"] == 0
    assert body["adherence"]["supplements"] == []


async def test_the_length_of_the_window_is_seven_to_fourteen(
    client: AsyncClient,
) -> None:
    fourteen = await get_summary(client, 14)
    assert fourteen["window"]["starts_on"] == "2026-10-13"

    for days in (6, 15):
        response = await client.get(SUMMARY_URL, params={"days": days})
        assert response.status_code == 422


async def test_reading_the_summary_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_window(db_session)
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(str(args[2]).lstrip().upper())

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    try:
        await get_summary(client)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record)

    assert statements
    assert all(s.startswith("SELECT") for s in statements)


# --- the number of statements ---------------------------------------------------


async def count_statements(client: AsyncClient, days: int) -> int:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(test_engine.sync_engine, "before_cursor_execute", count)
    try:
        await get_summary(client, days)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", count)
    return len(statements)


async def test_the_summary_costs_the_same_with_one_supplement_or_ten(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The class of error: a loop that asks the database once per day or supplement.

    Read once with one supplement and one day of data, then again after ten
    supplements, a mark on every day of the longest window and health on every
    day of both windows. The count must not move, whatever the window.
    """
    first = await add_supplement(db_session, "Одна", date(2026, 9, 1))
    await take(db_session, first, LAST_DAY)
    await add_health(db_session, STEPS, LAST_DAY, 1000)
    small = await count_statements(client, 7)

    for index in range(10):
        extra = await add_supplement(db_session, f"Добавка {index}", date(2026, 9, 1))
        await take(
            db_session, extra, *[LAST_DAY - timedelta(days=i) for i in range(14)]
        )
    for offset in range(28):
        day = LAST_DAY - timedelta(days=offset)
        await add_health(db_session, STEPS, day, 1000 + offset)
        await add_health(db_session, EXERCISE, day, 10 + offset)
        await add_health(db_session, RESTING, day, 60 + offset)

    assert await count_statements(client, 7) == small
    assert await count_statements(client, 14) == small
    assert small <= MAX_QUERIES


# --- the advice through the orchestration layer ---------------------------------


class FakeLLM(LLMClient):
    """A model that answers with a canned text and remembers what it was asked."""

    model = "fake-model"

    def __init__(self, text: str = "Шагов стало больше, так держать.") -> None:
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


async def ask(client: AsyncClient, days: int = 7) -> Any:
    return await client.post(ADVICE_URL, json={"days": days})


async def test_the_advice_is_written_from_the_numbers_of_the_window(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_window(db_session)

    response = await ask(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "fake-model"
    assert body["text"].startswith("Шагов стало больше, так держать.")
    assert (body["starts_on"], body["ends_on"], body["days"]) == (
        "2026-10-20",
        "2026-10-26",
        7,
    )
    (prompt,) = llm.prompts
    assert "8000 шагов" in prompt
    assert "+1000 шагов" in prompt
    assert "Минуты тренировки: в среднем 0 ч 30 мин" in prompt
    assert "Пульс покоя: в среднем 60 уд/мин" in prompt
    assert "-4 уд/мин" in prompt
    assert "Сон: данных нет" in prompt
    assert "принято 7 из 12" in prompt
    assert f"«{MAGNESIUM}»: 5 из 7 дн." in prompt
    assert f"«{D3}»: 2 из 5 дн." in prompt


async def test_the_model_is_never_given_a_dose(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_window(db_session)

    await ask(client)

    (prompt,) = llm.prompts
    assert "200" not in prompt
    assert "мг" not in prompt


async def test_the_prompt_forbids_diagnoses_and_doses(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_window(db_session)

    await ask(client)

    prompt = llm.prompts[0].lower()
    assert "не ставь диагнозов" in prompt
    assert "не назначай доз" in prompt


async def test_the_answer_always_carries_the_disclaimer(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_window(db_session)

    text = (await ask(client)).json()["text"]

    assert text.endswith(NOT_MEDICAL_ADVICE)
    assert "не медицинская рекомендация" in NOT_MEDICAL_ADVICE.lower()


async def test_a_disclaimer_the_model_already_wrote_is_not_doubled(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_window(db_session)
    llm.text = "Всё ровно. Это не Медицинская рекомендация."

    text = (await ask(client)).json()["text"]

    assert text.lower().count("не медицинская рекомендация") == 1


async def test_a_block_with_a_few_days_is_marked_as_thin_in_the_prompt(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    for offset in range(7):
        await add_health(db_session, STEPS, FIRST_DAY + timedelta(days=offset), 8000)
    await add_health(db_session, EXERCISE, LAST_DAY, 30)

    response = await ask(client)

    assert response.status_code == 200
    prompt = llm.prompts[0]
    assert "Минуты тренировки: данных мало" in prompt
    assert "30" not in prompt.split("Минуты тренировки: данных мало")[1].split("\n")[0]
    assert "Добавки: данных нет" in prompt


async def test_too_little_data_is_422_and_does_not_reach_the_model(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await add_health(db_session, STEPS, LAST_DAY, 8000)

    response = await ask(client)

    assert response.status_code == 422
    assert "Данных мало" in response.json()["detail"]
    assert llm.prompts == []


async def test_nothing_at_all_is_422_too(client: AsyncClient, llm: FakeLLM) -> None:
    response = await ask(client)

    assert response.status_code == 422
    assert llm.prompts == []


@pytest.mark.parametrize("days", [6, 15, 0, -1])
async def test_a_window_outside_seven_to_fourteen_is_422(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM, days: int
) -> None:
    await fill_window(db_session)

    assert (await ask(client, days)).status_code == 422
    assert llm.prompts == []


async def test_no_backend_is_503_and_a_failing_one_is_502(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await fill_window(db_session)

    app.dependency_overrides[get_llm_client] = lambda: None
    try:
        assert (await ask(client)).status_code == 503
        app.dependency_overrides[get_llm_client] = lambda: FailingLLM()
        assert (await ask(client)).status_code == 502
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


async def test_the_advice_is_not_stored(
    client: AsyncClient, db_session: AsyncSession, llm: FakeLLM
) -> None:
    await fill_window(db_session)
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(str(args[2]).lstrip().upper())

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    try:
        await ask(client)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record)

    assert statements
    assert all(s.startswith("SELECT") for s in statements)


# --- privacy --------------------------------------------------------------------


async def test_no_name_or_health_value_reaches_a_log_line(
    client: AsyncClient,
    db_session: AsyncSession,
    llm: FakeLLM,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    await fill_window(db_session)
    llm.text = "Секретный-совет-из-модели."

    await ask(client)
    await client.get(SUMMARY_URL)
    app.dependency_overrides[get_llm_client] = lambda: FailingLLM()
    try:
        await ask(client)
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    for leaked in (MAGNESIUM, D3, "Секретный-совет", "8000", "7000"):
        assert leaked not in caplog.text
