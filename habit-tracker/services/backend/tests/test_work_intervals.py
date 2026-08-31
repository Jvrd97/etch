"""
The measured time of a day: intervals, their sum, and the verdict standing on it.

Until now `work_minutes` arrived from outside and was almost always NULL, which
made «переработка = проигранный день» a rule nothing could enforce. Here the day
has a source: intervals a person types, intervals the agent proposes, and one
table both live in so that there is exactly one sum to judge from.

Four things are worth reading in the assertions below. An interval belongs to
the day of its *start* — 23:00 to 01:00 is one interval of one day, not two
halves — and the day is asked of `local_date()` rather than computed here. An
agent's interval corrected by hand keeps what the agent proposed beside the new
value. A day with no intervals at all says «не измерено» and is not judged on
overtime. And no answer anywhere carries a window title, because the table has
no column for one.
"""

# [review:need-review] PHASE-03/91
# summary: unit tests for the pure minute arithmetic (empty day is None, an open interval counts to now and no further than its day, a pause adds nothing) and API tests for the CRUD of intervals, the day they land in, the correction that keeps the agent's proposal, the overtime verdict at nine hours and the absence of window titles in the response
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.crud import day as day_crud
from app.day.evaluate import (
    MISSING_ANCHOR_KINDS,
    MISSING_WORK_MINUTES,
    REASON_OVERTIME,
    VERDICT_LOST,
    VERDICT_WON,
)
from app.day.work import (
    MODE_OFF,
    MODE_WORK,
    SOURCE_AGENT,
    SOURCE_CORRECTED,
    SOURCE_MANUAL,
    IntervalSpan,
    day_work_minutes,
    span_minutes,
)
from app.models.work_interval import WorkInterval

DAY_URL = "/api/v1/day"

# A Monday under the current canon (480 min a day, 540 as the exception ceiling,
# all tasks closed). Fixed rather than relative to today: the streak after a won
# Monday is 1, and the assertions about overtime name real numbers.
WORK_DAY = date(2026, 8, 24)
WORK_PATH = f"{DAY_URL}/{WORK_DAY.isoformat()}"

# The zone of the seeded canon; the wall clock a person actually types.
BERLIN = ZoneInfo("Europe/Berlin")

NINE_HOURS_MIN = 540
HALF_HOUR_MIN = 30


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """A local wall-clock moment of `day`, with its offset attached."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BERLIN)


def moment(raw: str | None) -> datetime | None:
    """
    A moment from the wire, compared as an instant rather than as a spelling.

    The API answers in UTC, a person types Berlin wall clock, and both are the
    same instant; `fromisoformat` of python 3.10 does not read a trailing `Z`.
    """
    return None if raw is None else datetime.fromisoformat(raw.replace("Z", "+00:00"))


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The rule table as a migrated database has it; `create_all` has no seed."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


def task(code: str, window: str = "09:00-10:00") -> dict[str, Any]:
    """A task that satisfies every row-level rule of `#87`."""
    return {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }


async def post_plan(
    client: AsyncClient, on: date, *items: dict[str, Any]
) -> list[dict[str, Any]]:
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={"sections": [{"kind": "work", "title": "День", "items": list(items)}]},
    )
    assert response.status_code == 201, response.text
    return list(response.json()["sections"][0]["items"])


async def add_interval(client: AsyncClient, on: date, **body: Any) -> dict[str, Any]:
    """Create one interval and hand it back, asserting it was accepted."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/work-intervals", json=body
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def work_of(client: AsyncClient, on: date) -> dict[str, Any]:
    """The work block of a day as its own endpoint answers it."""
    response = await client.get(f"{DAY_URL}/{on.isoformat()}/work-intervals")
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- the arithmetic, without postgres ---------------------------------------


def test_a_day_with_no_intervals_is_not_measured_rather_than_zero() -> None:
    """`None` is what makes `evaluate_day` skip the overtime check."""
    assert day_work_minutes([], WORK_DAY) is None


def test_a_day_of_pauses_only_is_measured_and_answers_zero() -> None:
    """Recorded «не работал» is a measurement; the absence of rows is not."""
    pause = IntervalSpan(at(WORK_DAY, 9), at(WORK_DAY, 13), MODE_OFF)

    assert day_work_minutes([pause], WORK_DAY) == 0


def test_a_closed_interval_is_its_own_length() -> None:
    span = IntervalSpan(at(WORK_DAY, 9, 30), at(WORK_DAY, 13), MODE_WORK)

    assert span_minutes(span, WORK_DAY) == 210


def test_an_open_interval_counts_up_to_now() -> None:
    """Идущий интервал — это «уже столько», а не ноль и не ошибка."""
    span = IntervalSpan(at(WORK_DAY, 9), None, MODE_WORK)

    assert span_minutes(span, WORK_DAY, now=at(WORK_DAY, 11, 30)) == 150


def test_an_open_interval_stops_at_the_end_of_its_own_day() -> None:
    """
    A forgotten interval must not report forty hours a week later.

    The day ends at the boundary hour of the next date — 04:00 — and that is
    where the clamp comes from, asked of `day_bounds()` rather than computed.
    """
    span = IntervalSpan(at(WORK_DAY, 9), None, MODE_WORK)
    a_week_later = at(WORK_DAY + timedelta(days=7), 12)

    minutes = span_minutes(span, WORK_DAY, now=a_week_later)

    # 09:00 to 04:00 of the next date is nineteen hours, and not one more.
    assert minutes == 19 * 60


def test_an_open_interval_of_a_day_not_yet_over_does_not_go_negative() -> None:
    """A start in the future is zero minutes, never a negative sum."""
    span = IntervalSpan(at(WORK_DAY, 15), None, MODE_WORK)

    assert span_minutes(span, WORK_DAY, now=at(WORK_DAY, 14)) == 0


# --- the day an interval lands in -------------------------------------------


async def test_an_interval_entered_by_hand_is_kept_and_summed(
    client: AsyncClient,
) -> None:
    """Приёмка: 09:30-13:00 заведён руками, сумма его учитывает, перезагрузка сохраняет."""
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9, 30).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )

    assert created["source"] == SOURCE_MANUAL
    assert created["minutes"] == 210
    assert created["running"] is False

    # "Перезагрузка сохраняет" — a fresh read, not the answer to the write.
    reloaded = await work_of(client, WORK_DAY)
    assert reloaded["work_minutes"] == 210
    assert [row["id"] for row in reloaded["intervals"]] == [created["id"]]


async def test_the_day_answer_carries_the_intervals_and_the_sum(
    client: AsyncClient,
) -> None:
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9, 30).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )

    response = await client.get(WORK_PATH)

    assert response.status_code == 200, response.text
    work = response.json()["work"]
    assert work["work_minutes"] == 210
    assert len(work["intervals"]) == 1
    # An unclosed day now shows the measurement instead of «не измерено».
    assert response.json()["summary"]["work_minutes"] == 210
    # `anchor_kinds` is the honest gap of #142: the plans built here name no
    # anchor codes, so the composition of the day's anchors is measured by the
    # counter rather than read off the lines, and the итог says so.
    assert response.json()["summary"]["missing_data"] == [MISSING_ANCHOR_KINDS]


async def test_an_interval_across_midnight_belongs_to_the_day_it_began_on(
    client: AsyncClient,
) -> None:
    """
    Приёмка: 23:00-01:00 при `day_start_hour = 4` — один интервал дня начала.

    The day is the one `local_date()` gives for the start, and the assertion
    below pins that: nothing splits the interval and nothing files the tail
    under the next date.
    """
    started = at(WORK_DAY, 23)
    ended = at(WORK_DAY + timedelta(days=1), 1)
    assert local_date(started) == WORK_DAY

    created = await add_interval(
        client, WORK_DAY, started_at=started.isoformat(), ended_at=ended.isoformat()
    )

    assert created["day_date"] == WORK_DAY.isoformat()
    assert created["minutes"] == 120
    assert (await work_of(client, WORK_DAY))["work_minutes"] == 120
    # And the next date does not carry half of it.
    next_day = await work_of(client, WORK_DAY + timedelta(days=1))
    assert next_day["work_minutes"] is None


async def test_an_interval_starting_on_another_day_is_refused(
    client: AsyncClient,
) -> None:
    """Filing it silently elsewhere would make the save look lost to the reader."""
    response = await client.post(
        f"{WORK_PATH}/work-intervals",
        json={"started_at": at(WORK_DAY + timedelta(days=2), 10).isoformat()},
    )

    assert response.status_code == 422, response.text
    assert (WORK_DAY + timedelta(days=2)).isoformat() in response.json()["detail"]


# --- what the table refuses --------------------------------------------------


async def test_an_interval_that_ends_before_it_starts_is_refused(
    client: AsyncClient,
) -> None:
    """Приёмка: `ended_at` раньше `started_at` не сохраняется."""
    response = await client.post(
        f"{WORK_PATH}/work-intervals",
        json={
            "started_at": at(WORK_DAY, 13).isoformat(),
            "ended_at": at(WORK_DAY, 9, 30).isoformat(),
        },
    )

    assert response.status_code == 422, response.text
    assert (await work_of(client, WORK_DAY))["work_minutes"] is None


async def test_the_database_refuses_a_reversed_interval_too(
    db_session: AsyncSession,
) -> None:
    """
    The rule is the CHECK, not the validator: the agent writes here as well.

    A row inserted straight through the session bypasses every pydantic model,
    which is exactly the writer the constraint exists for.
    """
    await day_crud.ensure_day(db_session, WORK_DAY)
    db_session.add(
        WorkInterval(
            day_date=WORK_DAY,
            started_at=at(WORK_DAY, 13),
            ended_at=at(WORK_DAY, 9),
            source=SOURCE_MANUAL,
            mode=MODE_WORK,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_window_title_is_refused_rather_than_quietly_dropped(
    client: AsyncClient,
) -> None:
    """
    Граница приватности: под заголовок окна нет ни колонки, ни поля.

    `extra="forbid"` turns a client that sends one into a 422 instead of a
    silent success that would leave the sender believing the text was stored.
    """
    response = await client.post(
        f"{WORK_PATH}/work-intervals",
        json={
            "started_at": at(WORK_DAY, 9).isoformat(),
            "window_title": "Переписка с врачом",
        },
    )

    assert response.status_code == 422, response.text


async def test_the_day_response_contains_no_window_title_anywhere(
    client: AsyncClient,
) -> None:
    """Приёмка: искать в JSON ответа дня нечего — заголовков там нет."""
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
        source=SOURCE_AGENT,
        app_bundle_id="com.apple.dt.Xcode",
    )

    response = await client.get(WORK_PATH)
    work = response.json()["work"]

    # Every field an interval can carry, spelled out: a column added later that
    # happens to hold a title has to break this list before it reaches a screen.
    assert set(work["intervals"][0]) == {
        "id",
        "day_date",
        "started_at",
        "ended_at",
        "running",
        "minutes",
        "source",
        "mode",
        "auto_started_at",
        "auto_ended_at",
        "app_bundle_id",
        "note",
        "edited_at",
    }
    assert "window_title" not in response.text
    assert work["intervals"][0]["app_bundle_id"] == "com.apple.dt.Xcode"


# --- the correction that keeps the proposal ---------------------------------


async def test_correcting_an_agent_interval_keeps_what_the_agent_proposed(
    client: AsyncClient,
) -> None:
    """Приёмка: исправленный интервал отдаёт и новое значение, и предложение агента."""
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 18).isoformat(),
        source=SOURCE_AGENT,
    )

    response = await client.patch(
        f"{WORK_PATH}/work-intervals/{created['id']}",
        json={"ended_at": at(WORK_DAY, 16).isoformat()},
    )

    assert response.status_code == 200, response.text
    corrected = response.json()
    assert corrected["source"] == SOURCE_CORRECTED
    assert moment(corrected["ended_at"]) == at(WORK_DAY, 16)
    assert moment(corrected["auto_ended_at"]) == at(WORK_DAY, 18)
    assert moment(corrected["auto_started_at"]) == at(WORK_DAY, 9)
    assert corrected["edited_at"] is not None
    assert corrected["minutes"] == 7 * 60


async def test_a_second_correction_leaves_the_proposal_where_it_is(
    client: AsyncClient,
) -> None:
    """What the agent proposed is one value, not a history of edits."""
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 18).isoformat(),
        source=SOURCE_AGENT,
    )
    await client.patch(
        f"{WORK_PATH}/work-intervals/{created['id']}",
        json={"ended_at": at(WORK_DAY, 16).isoformat()},
    )

    again = await client.patch(
        f"{WORK_PATH}/work-intervals/{created['id']}",
        json={"ended_at": at(WORK_DAY, 15).isoformat()},
    )

    assert moment(again.json()["auto_ended_at"]) == at(WORK_DAY, 18)
    assert moment(again.json()["ended_at"]) == at(WORK_DAY, 15)


async def test_a_hand_written_interval_has_no_proposal_to_keep(
    client: AsyncClient,
) -> None:
    """`manual` stays `manual`: there was never an agent's value to preserve."""
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )

    response = await client.patch(
        f"{WORK_PATH}/work-intervals/{created['id']}",
        json={"ended_at": at(WORK_DAY, 12).isoformat()},
    )

    assert response.json()["source"] == SOURCE_MANUAL
    assert response.json()["auto_ended_at"] is None
    assert response.json()["edited_at"] is not None


async def test_an_edit_touches_only_the_fields_the_body_names(
    client: AsyncClient,
) -> None:
    """Правка заметки не воскрешает закрытый интервал."""
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )

    response = await client.patch(
        f"{WORK_PATH}/work-intervals/{created['id']}", json={"note": "ревью PR"}
    )

    assert moment(response.json()["ended_at"]) == at(WORK_DAY, 13)
    assert response.json()["note"] == "ревью PR"


async def test_an_interval_of_another_day_is_not_addressable_here(
    client: AsyncClient,
) -> None:
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )
    other = (WORK_DAY + timedelta(days=1)).isoformat()

    response = await client.patch(
        f"{DAY_URL}/{other}/work-intervals/{created['id']}", json={"note": "нет"}
    )

    assert response.status_code == 404, response.text


async def test_deleting_the_last_interval_returns_the_day_to_unmeasured(
    client: AsyncClient,
) -> None:
    created = await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )

    response = await client.delete(f"{WORK_PATH}/work-intervals/{created['id']}")

    assert response.status_code == 204, response.text
    assert (await work_of(client, WORK_DAY))["work_minutes"] is None


# --- the open interval on screen --------------------------------------------


async def test_an_open_interval_reads_as_running_and_still_sums(
    client: AsyncClient,
) -> None:
    """Приёмка: открытый интервал виден как идущий и не ломает сумму дня."""
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 10).isoformat(),
    )
    running = await add_interval(
        client, WORK_DAY, started_at=at(WORK_DAY, 10, 30).isoformat()
    )

    assert running["running"] is True
    assert running["ended_at"] is None

    work = await work_of(client, WORK_DAY)
    assert work["running"] is True
    # The closed hour is there whatever the clock says about the open one.
    assert work["work_minutes"] is not None
    assert work["work_minutes"] >= 60


# --- the verdict the intervals decide ---------------------------------------


async def a_day_of_four_closed_tasks(client: AsyncClient) -> None:
    """4/4 задачи закрыты и якорей нет: всё, кроме времени, в порядке."""
    items = await post_plan(
        client,
        WORK_DAY,
        task("W1"),
        task("W2", "10:00-11:00"),
        task("W3", "11:00-12:00"),
        task("W4", "12:00-13:00"),
    )
    for item in items:
        response = await client.put(
            f"{WORK_PATH}/marks/{item['id']}", json={"state": "done"}
        )
        assert response.status_code == 200, response.text


async def test_four_of_four_tasks_and_nine_hours_is_lost_by_overtime(
    client: AsyncClient,
) -> None:
    """
    Приёмка: 4/4 задачи плюс девять часов — `lost` с причиной `overtime`.

    Nine hours is over the everyday ceiling of the canon in force (480 min), and
    the ticket's whole point is that this is now decided by measured intervals
    rather than by a number somebody typed.
    """
    await a_day_of_four_closed_tasks(client)
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 8).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 13, 30).isoformat(),
        ended_at=at(WORK_DAY, 17, 30).isoformat(),
    )
    assert (await work_of(client, WORK_DAY))["work_minutes"] == NINE_HOURS_MIN

    response = await client.post(f"{WORK_PATH}/close", json={})

    assert response.status_code == 200, response.text
    closed = response.json()
    assert (closed["verdict"], closed["verdict_reason"]) == (
        VERDICT_LOST,
        REASON_OVERTIME,
    )
    assert closed["work_minutes"] == NINE_HOURS_MIN
    # `anchor_kinds` is the honest gap of #142: the plans built here name no
    # anchor codes, so the composition of the day's anchors is measured by the
    # counter rather than read off the lines, and the итог says so.
    assert closed["missing_data"] == [MISSING_ANCHOR_KINDS]


async def test_a_day_without_intervals_is_not_judged_on_overtime(
    client: AsyncClient,
) -> None:
    """Приёмка: без интервалов нет `overtime`, а в итоге видно «время не измерено»."""
    await a_day_of_four_closed_tasks(client)

    response = await client.post(f"{WORK_PATH}/close", json={})

    closed = response.json()
    assert closed["verdict"] == VERDICT_WON
    assert closed["verdict_reason"] != REASON_OVERTIME
    assert closed["work_minutes"] is None
    # `anchor_kinds` is the honest gap of #142: the plans built here name no
    # anchor codes, so the composition of the day's anchors is measured by the
    # counter rather than read off the lines, and the итог says so.
    assert closed["missing_data"] == [MISSING_WORK_MINUTES, MISSING_ANCHOR_KINDS]


async def test_the_measurement_replaces_the_number_typed_at_close(
    client: AsyncClient,
) -> None:
    """
    Интервалы — измерение, число в теле закрытия — оценка; измерение сильнее.

    Otherwise a day would show one number in its list of intervals and stand its
    verdict on another, and neither would be knowable as the real one.
    """
    await a_day_of_four_closed_tasks(client)
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 8).isoformat(),
        ended_at=at(WORK_DAY, 17, 30).isoformat(),
    )

    response = await client.post(f"{WORK_PATH}/close", json={"work_minutes": 120})

    assert response.json()["work_minutes"] == NINE_HOURS_MIN + HALF_HOUR_MIN
    assert response.json()["verdict_reason"] == REASON_OVERTIME


async def test_a_day_closed_without_intervals_keeps_the_number_it_was_given(
    client: AsyncClient,
) -> None:
    """История, закрытая до появления интервалов, своё число не теряет."""
    await a_day_of_four_closed_tasks(client)

    response = await client.post(f"{WORK_PATH}/close", json={"work_minutes": 400})

    assert response.json()["work_minutes"] == 400
    # `anchor_kinds` is the honest gap of #142: the plans built here name no
    # anchor codes, so the composition of the day's anchors is measured by the
    # counter rather than read off the lines, and the итог says so.
    assert response.json()["missing_data"] == [MISSING_ANCHOR_KINDS]
    assert response.json()["verdict"] == VERDICT_WON


async def test_a_pause_does_not_count_towards_the_day(client: AsyncClient) -> None:
    """`mode='off'` — записанная пауза, а не более короткая работа."""
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 9).isoformat(),
        ended_at=at(WORK_DAY, 13).isoformat(),
    )
    await add_interval(
        client,
        WORK_DAY,
        started_at=at(WORK_DAY, 13).isoformat(),
        ended_at=at(WORK_DAY, 14).isoformat(),
        mode=MODE_OFF,
    )

    work = await work_of(client, WORK_DAY)

    assert work["work_minutes"] == 240
    assert len(work["intervals"]) == 2


async def test_a_naive_start_is_refused_rather_than_read_as_utc(
    client: AsyncClient,
) -> None:
    """
    Без смещения момент читался бы как UTC и уезжал бы на два часа.

    Near the boundary hour that is a different day, which is exactly the class of
    bug `local_date()` refuses a naive datetime for.
    """
    response = await client.post(
        f"{WORK_PATH}/work-intervals", json={"started_at": "2026-08-24T09:30:00"}
    )

    assert response.status_code == 422, response.text


def test_utc_and_local_spellings_of_one_moment_agree() -> None:
    """The same instant written two ways is one interval of one length."""
    local = IntervalSpan(at(WORK_DAY, 9), at(WORK_DAY, 13), MODE_WORK)
    utc = IntervalSpan(
        at(WORK_DAY, 9).astimezone(timezone.utc),
        at(WORK_DAY, 13).astimezone(timezone.utc),
        MODE_WORK,
    )

    assert span_minutes(local, WORK_DAY) == span_minutes(utc, WORK_DAY)
