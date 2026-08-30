"""
Closing a day, and the debt of wave A that closing it stands on.

Two subjects, and they are one ticket because the verdict cannot be trusted
without the second. `POST /day/{date}/close` writes the summary and the day
starts answering with a verdict, a reason and a streak. And `opened_at` stops
being set by any day a browser happens to render: пролистанный из любопытства
август has to keep reading as «не открывал», because that is exactly the fact
`verdict = null` is distinguished from `lost` by.

`GET /day/{date}` carries the summary block whether or not the day was closed.
An unclosed day gets a live recount with `verdict = null` and the reason
`not_closed`, so «не закрыл» and «проиграл» come back different without a second
flag, and the screen can show the progress before anybody presses anything.
"""

# [review:need-review] PHASE-03/90, PHASE-03/93
# summary: API tests for POST /day/{date}/close (verdict, reason, counters, streak, override with its CHECK) and for the open window — a historical day stays "не открывали" through reads, marks and the notebook, while today and yesterday still open
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.day.evaluate import (
    REASON_ANCHORS,
    REASON_NOT_CLOSED,
    REASON_OVERTIME,
    REASON_TASKS,
    VERDICT_LOST,
    VERDICT_WON,
)
from app.models.mark import MARK_DONE
from app.models.summary import DaySummary

DAY_URL = "/api/v1/day"

# A Monday under the current canon. Fixed rather than relative to today: the
# streak after a won Monday is 1, and the same assertion on a Sunday would be 0.
CLOSE_DAY = date(2026, 8, 24)
CLOSE_PATH = f"{DAY_URL}/{CLOSE_DAY.isoformat()}"

# Пролистанный из любопытства август — well outside the open window whenever
# these tests run.
HISTORICAL = date(2026, 8, 10)

NINE_HOURS_MIN = 540
FAMILY_ANCHOR = "Вечер с близкими"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it; `create_all` has no seed.

    `seeded_goal` comes with it: every task below names goal 1 of the quarter,
    and since `#93` that column has a foreign key.
    """
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


def anchor(text: str) -> dict[str, Any]:
    return {"kind": "anchor", "text_md": text}


async def post_plan(
    client: AsyncClient, on: date, *items: dict[str, Any]
) -> list[dict[str, Any]]:
    """Send a one-section plan for `on` and hand back its stored items."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={"sections": [{"kind": "work", "title": "День", "items": list(items)}]},
    )
    assert response.status_code == 201, response.text
    return list(response.json()["sections"][0]["items"])


async def mark(client: AsyncClient, on: date, item_id: str, state: str) -> None:
    response = await client.put(
        f"{DAY_URL}/{on.isoformat()}/marks/{item_id}", json={"state": state}
    )
    assert response.status_code == 200, response.text


async def close(client: AsyncClient, on: date, **body: Any) -> dict[str, Any]:
    """Close a day and hand back the summary, asserting it was accepted."""
    response = await client.post(f"{DAY_URL}/{on.isoformat()}/close", json=body)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def summary_of(client: AsyncClient, on: date) -> dict[str, Any]:
    """The summary block as `GET /day/{date}` carries it."""
    response = await client.get(f"{DAY_URL}/{on.isoformat()}")
    assert response.status_code == 200, response.text
    return dict(response.json()["summary"])


async def a_won_day(client: AsyncClient) -> None:
    """One task and one anchor, both closed: the day that is won."""
    items = await post_plan(client, CLOSE_DAY, task("W1"), anchor("Подъём 06:00"))
    for item in items:
        await mark(client, CLOSE_DAY, item["id"], MARK_DONE)


# --- the summary the day now carries ---------------------------------------


async def test_closing_a_day_writes_the_verdict_the_reason_and_the_streak(
    client: AsyncClient,
) -> None:
    await a_won_day(client)

    closed = await close(client, CLOSE_DAY, work_minutes=400, body_md="ровный день")

    assert closed["verdict"] == VERDICT_WON
    assert closed["verdict_reason"] == ""
    assert closed["streak_after"] == 1
    assert (closed["tasks_done"], closed["tasks_total"]) == (1, 1)
    assert (closed["anchors_done"], closed["anchors_total"]) == (1, 1)

    stored = await summary_of(client, CLOSE_DAY)
    assert stored["closed"] is True
    assert (stored["verdict"], stored["streak_after"]) == (VERDICT_WON, 1)
    assert stored["work_minutes"] == 400
    assert stored["missing_data"] == []


async def test_the_summary_names_the_rule_the_day_was_judged_by(
    client: AsyncClient,
) -> None:
    """«На странице видно, по какому правилу» — the row carries the answer."""
    await a_won_day(client)
    closed = await close(client, CLOSE_DAY, work_minutes=400)

    day = await client.get(CLOSE_PATH)

    assert closed["rule_set_id"] == day.json()["rule"]["id"]


async def test_an_unclosed_day_answers_null_rather_than_lost(
    client: AsyncClient,
) -> None:
    """«Не закрыл» и «проиграл» различаются, и это одно поле, а не догадка."""
    await post_plan(client, CLOSE_DAY, task("W1"))

    stored = await summary_of(client, CLOSE_DAY)

    assert stored["closed"] is False
    assert stored["verdict"] is None
    assert stored["verdict_reason"] == REASON_NOT_CLOSED
    assert stored["streak_after"] is None
    # The counters are live all the same: the screen shows progress before
    # anybody presses anything.
    assert (stored["tasks_done"], stored["tasks_total"]) == (0, 1)


async def test_three_tasks_of_four_come_back_as_lost_by_tasks(
    client: AsyncClient,
) -> None:
    items = await post_plan(
        client,
        CLOSE_DAY,
        task("W1"),
        task("W2", "10:00-11:00"),
        task("W3", "11:00-12:00"),
        task("W4", "12:00-13:00"),
    )
    for item in items[:3]:
        await mark(client, CLOSE_DAY, item["id"], MARK_DONE)

    closed = await close(client, CLOSE_DAY, work_minutes=400)

    assert (closed["verdict"], closed["verdict_reason"]) == (VERDICT_LOST, REASON_TASKS)
    assert closed["streak_after"] == 0


async def test_a_missing_evening_with_the_family_is_named_by_its_own_line(
    client: AsyncClient,
) -> None:
    """
    The decoding the acceptance asks for: не «якоря 4/5», а какой именно.

    `relationship` has no verdict reason of its own — весом якоря равны — so the
    only way the reader learns what was missed is this list.
    """
    items = await post_plan(
        client,
        CLOSE_DAY,
        task("W1"),
        anchor("Подъём 06:00"),
        anchor(FAMILY_ANCHOR),
    )
    for item in items[:2]:
        await mark(client, CLOSE_DAY, item["id"], MARK_DONE)

    closed = await close(client, CLOSE_DAY, work_minutes=400)

    assert (closed["verdict"], closed["verdict_reason"]) == (
        VERDICT_LOST,
        REASON_ANCHORS,
    )
    assert closed["missing_anchors"] == [FAMILY_ANCHOR]


async def test_nine_hours_of_work_lose_the_day_to_overtime(
    client: AsyncClient,
) -> None:
    await a_won_day(client)

    closed = await close(client, CLOSE_DAY, work_minutes=NINE_HOURS_MIN)

    assert (closed["verdict"], closed["verdict_reason"]) == (
        VERDICT_LOST,
        REASON_OVERTIME,
    )


async def test_a_day_whose_work_was_never_measured_says_so(
    client: AsyncClient,
) -> None:
    """`work_minutes` допускает NULL до `#91`; пропуск проверки назван вслух."""
    await a_won_day(client)

    closed = await close(client, CLOSE_DAY, body_md="времени не мерил")

    assert closed["verdict"] == VERDICT_WON
    assert closed["missing_data"] == ["work_minutes"]
    assert closed["work_minutes"] is None


async def test_closing_a_day_twice_replaces_the_summary_rather_than_adding_one(
    client: AsyncClient,
) -> None:
    """Закрытие — это состояние дня, а не запись в журнале."""
    await a_won_day(client)

    await close(client, CLOSE_DAY, work_minutes=400)
    again = await close(client, CLOSE_DAY, work_minutes=NINE_HOURS_MIN)

    assert again["verdict"] == VERDICT_LOST
    assert (await summary_of(client, CLOSE_DAY))["work_minutes"] == NINE_HOURS_MIN


# --- the override, and the note it cannot be made without ------------------


async def test_an_override_without_a_note_is_refused_by_the_schema(
    client: AsyncClient,
) -> None:
    await a_won_day(client)

    response = await client.post(
        f"{CLOSE_PATH}/close", json={"work_minutes": 400, "verdict_override": True}
    )

    assert response.status_code == 422


async def test_an_override_without_a_note_is_refused_by_the_database_too(
    db_session: AsyncSession,
) -> None:
    """
    Валидатор — сообщение, CHECK — правило.

    A row written past the API — a migration, a psql session, the importer —
    has to be refused by the same rule, otherwise «переопределение остаётся
    видимым действием» holds only for callers who happen to go through FastAPI.
    """
    await day_crud.ensure_day(db_session, CLOSE_DAY)
    rule = await day_crud.rule_for_date(db_session, CLOSE_DAY)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                insert(DaySummary).values(
                    day_date=CLOSE_DAY,
                    rule_set_id=rule.id,
                    verdict=VERDICT_WON,
                    verdict_reason=REASON_TASKS,
                    verdict_override=True,
                    verdict_override_note=None,
                )
            )


async def test_an_override_with_a_note_keeps_the_machine_reason_visible(
    client: AsyncClient,
) -> None:
    """
    «День был выигран, просто я не отметил» — право человека, но вслух.

    The reason the machine reached stays on the row: an override that erased it
    would leave nothing to disagree with a month later.
    """
    items = await post_plan(client, CLOSE_DAY, task("W1"))
    assert items

    closed = await close(
        client,
        CLOSE_DAY,
        work_minutes=400,
        verdict_override=True,
        verdict_override_note="задача сделана, отметить забыл",
    )

    assert closed["verdict"] == VERDICT_WON
    assert closed["verdict_reason"] == REASON_TASKS
    assert closed["verdict_override"] is True
    assert closed["streak_after"] == 1


# --- the open window -------------------------------------------------------


async def test_browsing_a_historical_day_leaves_it_never_opened(
    client: AsyncClient,
) -> None:
    """
    The debt of wave A, and the reason the verdict needed it closed.

    `DayScreen` calls `useDay(date, true)` for every date, so пролистать август
    из любопытства used to be enough to make «не открывал» indistinguishable
    from «открыл и ничего не сделал» — the very difference `verdict = null`
    stands on.
    """
    path = f"{DAY_URL}/{HISTORICAL.isoformat()}"

    first = await client.get(path, params={"opened": "true"})
    second = await client.get(path, params={"opened": "true"})

    assert first.json()["day"]["opened_at"] is None
    assert second.json()["day"]["opened_at"] is None
    assert second.json()["summary"]["verdict"] is None


async def test_today_and_yesterday_still_open(client: AsyncClient) -> None:
    """Окно открытия — сегодня и вчера: вечернее закрытие дня в 00:30 живое."""
    today = today_local()
    yesterday = today - timedelta(days=1)

    for on in (today, yesterday):
        response = await client.get(
            f"{DAY_URL}/{on.isoformat()}", params={"opened": "true"}
        )
        assert response.json()["day"]["opened_at"] is not None, on.isoformat()


async def test_writing_into_a_historical_day_does_not_open_it_either(
    client: AsyncClient,
) -> None:
    """
    A write is not an opening when the day is out of the window.

    The agent, the import and a correction typed a week later all write into
    old days; if any of those set `opened_at`, the fourth kind of empty would
    stop existing the first time the history is touched.
    """
    path = f"{DAY_URL}/{HISTORICAL.isoformat()}"
    items = await post_plan(client, HISTORICAL, task("W1"))

    await client.put(f"{path}/notebook", json={"content": "поправил задним числом"})
    await client.put(
        f"{path}/marks/{items[0]['id']}", json={"state": MARK_DONE, "source": "web"}
    )

    assert (await client.get(path)).json()["day"]["opened_at"] is None


async def test_the_same_writes_do_open_today(client: AsyncClient) -> None:
    today = today_local()
    path = f"{DAY_URL}/{today.isoformat()}"

    await client.put(f"{path}/notebook", json={"content": "утро: тихо"})

    assert (await client.get(path)).json()["day"]["opened_at"] is not None


async def test_the_notebook_checks_its_source_the_way_a_mark_does(
    client: AsyncClient,
) -> None:
    """
    `PUT .../notebook` перестаёт открывать день не глядя.

    The local agent writes the notebook too, and a day the agent wrote into is
    not a day a person came to.
    """
    today = today_local()
    path = f"{DAY_URL}/{today.isoformat()}"

    await client.put(
        f"{path}/notebook", json={"content": "собрано агентом", "source": "agent"}
    )
    after_agent = await client.get(path)
    assert after_agent.json()["day"]["opened_at"] is None
    assert after_agent.json()["day"]["last_touched_at"] is not None

    await client.put(f"{path}/notebook", json={"content": "и рукой"})
    assert (await client.get(path)).json()["day"]["opened_at"] is not None
