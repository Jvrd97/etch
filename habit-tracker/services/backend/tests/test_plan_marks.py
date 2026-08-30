"""
Tests for the marks of a plan, the four kinds of empty, and the day's notebook.

Every acceptance case of `#88` is here, in the words of the ticket: three clicks
walk a line through ✓, ✕ and back to nothing; replacing the text of an item does
not move its mark; the note survives; a day nobody opened reads differently from
a day opened and left unmarked; `skipped` counts as neither closed nor failed;
`plan_mark_event` gets a row per transition including the one that clears a
mark; two tabs do not resurrect an old value; and the notebook stays a single
entry per date.
"""

# [review:need-review] PHASE-03/88
# summary: API and logic tests for the mark cycle, the mark that survives an edit of the plan, the append-only event log, the four states of "empty", the task counter that ignores `skipped`, and the notebook as one journal entry per date
import uuid
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import plan as plan_crud
from app.day.marks import MARK_CYCLE, TaskCounts, count_tasks, next_state
from app.models.journal import JournalEntry
from app.models.mark import MARK_DONE, MARK_FAILED, MARK_SKIPPED, PlanMarkEvent

DAY_URL = "/api/v1/day"

# A Monday under the current canon, the same one `#87`'s tests use.
MARK_DAY = date(2026, 8, 31)
DAY_PATH = f"{DAY_URL}/{MARK_DAY.isoformat()}"
PLAN_URL = f"{DAY_PATH}/plan"


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The rule table as a migrated database has it; `create_all` has no seed."""
    await day_crud.seed_rules(db_session)
    yield


def task(code: str, window: str = "09:00-10:00", **overrides: Any) -> dict[str, Any]:
    """A task that satisfies every row-level rule of `#87`."""
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


def document(*items: dict[str, Any]) -> dict[str, Any]:
    """A plan of one work section holding `items`."""
    return {
        "title": "План 2026-08-31 (пн)",
        "sections": [{"kind": "work", "title": "Работа", "items": list(items)}],
    }


async def post_plan(client: AsyncClient, *items: dict[str, Any]) -> dict[str, Any]:
    """Send a plan and hand back the stored one."""
    response = await client.post(PLAN_URL, json=document(*items))
    assert response.status_code == 201, response.text
    return dict(response.json())


def first_item(plan: dict[str, Any]) -> dict[str, Any]:
    """The first item of the first section of a stored plan."""
    return dict(plan["sections"][0]["items"][0])


def mark_url(item_id: str) -> str:
    return f"{DAY_PATH}/marks/{item_id}"


async def put_mark(
    client: AsyncClient, item_id: str, state: str | None, **body: Any
) -> dict[str, Any]:
    """Mark an item and hand back the answer, asserting it was accepted."""
    response = await client.put(mark_url(item_id), json={"state": state, **body})
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- the cycle -------------------------------------------------------------


def test_the_cycle_is_three_states_and_returns_to_empty() -> None:
    """The ring a click walks: пусто -> done -> failed -> пусто."""
    assert next_state(None) == MARK_DONE
    assert next_state(MARK_DONE) == MARK_FAILED
    assert next_state(MARK_FAILED) is None
    assert MARK_CYCLE == (None, MARK_DONE, MARK_FAILED)


def test_skipped_is_not_on_the_ring_and_a_click_takes_it_off() -> None:
    """
    `skipped` is set deliberately, never walked into.

    "Стало неактуально" is a judgement about the plan rather than about the
    work; a person cycling a line four times must not land on it by accident.
    """
    assert MARK_SKIPPED not in MARK_CYCLE
    assert next_state(MARK_SKIPPED) is None


async def test_three_clicks_walk_a_line_and_the_third_clears_it(
    client: AsyncClient,
) -> None:
    """The first acceptance case, and it survives a re-read of the day."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    first = await put_mark(client, item_id, MARK_DONE)
    assert first["state"] == MARK_DONE

    second = await put_mark(client, item_id, MARK_FAILED)
    assert second["state"] == MARK_FAILED

    third = await put_mark(client, item_id, None)
    assert third["state"] is None

    day = await client.get(DAY_PATH)
    assert day.json()["marks"] == []


async def test_a_mark_survives_a_reload_of_the_day(client: AsyncClient) -> None:
    """Перезагрузка страницы состояние сохраняет — the mark is a row, not a tab."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]
    await put_mark(client, item_id, MARK_DONE, note="успел до обеда")

    day = await client.get(DAY_PATH)
    marks = day.json()["marks"]

    assert len(marks) == 1
    assert marks[0]["item_id"] == item_id
    assert marks[0]["state"] == MARK_DONE
    assert marks[0]["note"] == "успел до обеда"


async def test_an_unknown_state_is_refused_by_name(client: AsyncClient) -> None:
    """A typo comes back as a 422 naming the three words, not as a 500."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    response = await client.put(mark_url(item_id), json={"state": "почти"})

    assert response.status_code == 422
    assert MARK_SKIPPED in response.text


async def test_a_mark_for_an_item_of_another_day_is_a_404(client: AsyncClient) -> None:
    """A mark is addressed as "this line of this day"; a stray uuid is not one."""
    await post_plan(client, task("W1"))

    response = await client.put(mark_url(str(uuid.uuid4())), json={"state": MARK_DONE})

    assert response.status_code == 404


# --- the mark outlives an edit of the plan ---------------------------------


async def test_replacing_the_text_of_an_item_does_not_move_its_mark(
    client: AsyncClient,
) -> None:
    """
    The acceptance case the whole move to rows exists for.

    The old key was the item's position in the DOM, so editing one line shifted
    the marks of every line below it. Here the plan is re-sent with the item's
    id, which says "the same line, new wording" — and the tick stays where it
    was, with its note and its timestamps.
    """
    plan = await post_plan(client, task("W1"), task("W2", window="11:00-12:00"))
    first, second = plan["sections"][0]["items"]
    await put_mark(client, first["id"], MARK_DONE, note="сделал")

    edited = await post_plan(
        client,
        task("W1", id=first["id"], text_md="Задача W1, переформулированная"),
        task("W2", id=second["id"], window="11:00-12:00"),
    )

    assert first_item(edited)["id"] == first["id"]
    assert first_item(edited)["text_plain"] == "Задача W1, переформулированная"

    day = await client.get(DAY_PATH)
    marks = day.json()["marks"]
    assert len(marks) == 1
    assert marks[0]["item_id"] == first["id"]
    assert marks[0]["state"] == MARK_DONE
    assert marks[0]["note"] == "сделал"


async def test_a_plan_resent_without_ids_starts_the_day_over(
    client: AsyncClient,
) -> None:
    """
    Without ids the lines are new lines, and new lines have no marks.

    That is the honest reading: a document that does not say which line is which
    is being rewritten, not edited, and guessing by text would bring back
    exactly the positional matching this ticket removes.
    """
    plan = await post_plan(client, task("W1"))
    await put_mark(client, first_item(plan)["id"], MARK_DONE)

    rewritten = await post_plan(client, task("W1"))

    assert first_item(rewritten)["id"] != first_item(plan)["id"]
    day = await client.get(DAY_PATH)
    assert day.json()["marks"] == []


async def test_an_id_sent_twice_is_refused_and_the_line_is_named(
    client: AsyncClient,
) -> None:
    """Two lines claiming one id have one mark between them; that is a 422."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    response = await client.post(
        PLAN_URL,
        json=document(
            task("W1", id=item_id),
            task("W2", id=item_id, window="11:00-12:00"),
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "duplicate_item_id"
    assert response.json()["detail"]["item_code"] == "W2"


async def test_a_reused_id_lands_even_with_the_old_rows_still_loaded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Re-inserting a row under an id the session has already seen is allowed.

    A session that read the plan holds those rows; the replace deletes them and
    writes new ones under the same primary keys. This test keeps a strong
    reference to the old objects on purpose — that is the case in which an
    identity-map conflict would surface, and it is worth a guard rather than an
    assumption, because the failure would look like a random 500 on save.
    """
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]
    await put_mark(client, item_id, MARK_DONE)

    stored = await plan_crud.get_plan(db_session, MARK_DAY)
    assert stored is not None
    live = [item for section in stored.sections for item in section.items]
    assert len(live) == 1

    again = await post_plan(client, task("W1", id=item_id, text_md="другими словами"))

    assert first_item(again)["id"] == item_id
    day = await client.get(DAY_PATH)
    assert day.json()["marks"][0]["state"] == MARK_DONE


async def test_a_deleted_item_takes_its_mark_with_it(client: AsyncClient) -> None:
    """A mark of a line no longer in any plan is not a fact about anything."""
    plan = await post_plan(client, task("W1"), task("W2", window="11:00-12:00"))
    first, second = plan["sections"][0]["items"]
    await put_mark(client, first["id"], MARK_DONE)
    await put_mark(client, second["id"], MARK_DONE)

    await post_plan(client, task("W1", id=first["id"]))

    day = await client.get(DAY_PATH)
    marks = day.json()["marks"]
    assert [mark["item_id"] for mark in marks] == [first["id"]]


# --- the four kinds of empty ----------------------------------------------


async def test_a_day_nobody_opened_differs_from_one_opened_and_left_alone(
    client: AsyncClient,
) -> None:
    """
    The distinction the files could not draw.

    A day with no marks used to read as "ничего не сделал". Now the day itself
    says whether anybody came: `opened_at` stays NULL for a read that was not a
    person on the page, which is what an agent, an import and a cron job are.
    """
    unopened = await client.get(DAY_PATH)
    assert unopened.json()["day"]["opened_at"] is None
    assert unopened.json()["marks"] == []

    opened = await client.get(DAY_PATH, params={"opened": "true"})
    assert opened.json()["day"]["opened_at"] is not None
    assert opened.json()["marks"] == []


async def test_opening_twice_keeps_the_first_time(client: AsyncClient) -> None:
    """`opened_at` is when the day was first opened, not most recently."""
    first = await client.get(DAY_PATH, params={"opened": "true"})
    second = await client.get(DAY_PATH, params={"opened": "true"})

    assert second.json()["day"]["opened_at"] == first.json()["day"]["opened_at"]
    assert second.json()["day"]["last_touched_at"] is not None


async def test_a_mark_from_the_agent_does_not_claim_the_day_was_opened(
    client: AsyncClient,
) -> None:
    """
    Only a click in the browser means a person was looking.

    The floating window of the local agent writes marks too (`source='agent'`),
    and if that counted as opening the day, "не открывал" would stop being
    establishable at all.
    """
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    await put_mark(client, item_id, MARK_DONE, source="agent")
    after_agent = await client.get(DAY_PATH)
    assert after_agent.json()["day"]["opened_at"] is None
    assert after_agent.json()["day"]["last_touched_at"] is not None

    await put_mark(client, item_id, MARK_FAILED, source="web")
    after_web = await client.get(DAY_PATH)
    assert after_web.json()["day"]["opened_at"] is not None


# --- the counter -----------------------------------------------------------


def test_skipped_counts_as_neither_closed_nor_failed() -> None:
    """The counting rule, without a database in the way."""
    ids = [uuid.uuid4() for _ in range(4)]
    kinds = {item_id: "task" for item_id in ids}
    kinds[uuid.uuid4()] = "anchor"

    counts = count_tasks(
        kinds,
        {ids[0]: MARK_DONE, ids[1]: MARK_FAILED, ids[2]: MARK_SKIPPED},
    )

    assert counts == TaskCounts(planned=4, done=1, failed=1, skipped=1, pending=1)


async def test_the_day_counts_its_tasks_and_leaves_skipped_out_of_both(
    client: AsyncClient,
) -> None:
    """The same rule as the day answers it, anchors not counted."""
    plan = await post_plan(
        client,
        task("W1"),
        task("W2", window="11:00-12:00"),
        {"kind": "anchor", "code": "подъём", "text_md": "Подъём 06:00"},
    )
    first, second, _anchor = plan["sections"][0]["items"]

    await put_mark(client, first["id"], MARK_DONE)
    await put_mark(client, second["id"], MARK_SKIPPED)

    counts = (await client.get(DAY_PATH)).json()["task_counts"]

    assert counts == {
        "planned": 2,
        "done": 1,
        "failed": 0,
        "skipped": 1,
        "pending": 0,
    }


async def test_a_day_without_a_plan_still_counts_zero(client: AsyncClient) -> None:
    """The header of an empty day says "0 из 0" rather than refusing to render."""
    response = await client.get(f"{DAY_URL}/2026-08-29")

    assert response.status_code == 200
    assert response.json()["task_counts"]["planned"] == 0


# --- the log ---------------------------------------------------------------


async def test_every_change_of_state_is_appended_including_the_one_that_clears(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    `plan_mark_event` is the history git stopped keeping.

    Three clicks are three rows, the last of them recording that the mark was
    taken off — "я снял галку в 23:50" is exactly what a person rereads a week
    later.
    """
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    await put_mark(client, item_id, MARK_DONE)
    await put_mark(client, item_id, MARK_FAILED)
    await put_mark(client, item_id, None)

    result = await db_session.execute(
        select(PlanMarkEvent)
        .where(PlanMarkEvent.item_id == uuid.UUID(item_id))
        .order_by(PlanMarkEvent.at)
    )
    events = list(result.scalars().all())

    assert [(event.from_state, event.to_state) for event in events] == [
        (None, MARK_DONE),
        (MARK_DONE, MARK_FAILED),
        (MARK_FAILED, None),
    ]
    assert {event.day_date for event in events} == {MARK_DAY}


async def test_the_same_mark_sent_twice_appends_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    A retried request and a second tab are not transitions.

    A log in which half the rows say "nothing happened" is not a log anybody
    reads to the end.
    """
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    await put_mark(client, item_id, MARK_DONE)
    await put_mark(client, item_id, MARK_DONE)

    result = await db_session.execute(
        select(PlanMarkEvent).where(PlanMarkEvent.item_id == uuid.UUID(item_id))
    )
    assert len(list(result.scalars().all())) == 1


async def test_the_log_outlives_the_item_it_points_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    An append-only log that forgets is not a log.

    The mark of a deleted item goes with the item; the record of what was once
    ticked stays, which is why `plan_mark_event.item_id` carries no foreign key.
    """
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]
    await put_mark(client, item_id, MARK_DONE)

    await post_plan(client, task("W2", window="11:00-12:00"))

    result = await db_session.execute(
        select(PlanMarkEvent).where(PlanMarkEvent.item_id == uuid.UUID(item_id))
    )
    assert len(list(result.scalars().all())) == 1


# --- two tabs --------------------------------------------------------------


async def test_two_tabs_do_not_resurrect_the_older_value(
    client: AsyncClient,
) -> None:
    """
    The last write wins, and `updated_at` says which one that was.

    `plan_server.py` needed a 409 on "empty over non-empty" and a re-read on
    `visibilitychange` because it wrote to a file with no transaction. Here the
    request names the state it wants, the upsert is atomic, and the second tab
    simply wins.
    """
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    tab_one = await put_mark(client, item_id, MARK_DONE, note="из первой вкладки")
    tab_two = await put_mark(client, item_id, None)
    tab_one_again = await put_mark(client, item_id, MARK_FAILED, note="из второй")

    assert tab_one["state"] == MARK_DONE
    assert tab_two["state"] is None
    assert tab_one_again["state"] == MARK_FAILED
    assert tab_one_again["updated_at"] >= tab_one["updated_at"]

    day = await client.get(DAY_PATH)
    assert day.json()["marks"][0]["state"] == MARK_FAILED
    assert day.json()["marks"][0]["note"] == "из второй"


async def test_editing_only_the_note_keeps_the_moment_of_the_tick(
    client: AsyncClient,
) -> None:
    """`marked_at` is about the tick; a sentence added at 23:00 does not move it."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]

    ticked = await put_mark(client, item_id, MARK_DONE)
    annotated = await put_mark(client, item_id, MARK_DONE, note="вышло дольше")

    assert annotated["marked_at"] == ticked["marked_at"]
    assert annotated["updated_at"] >= ticked["updated_at"]
    assert annotated["note"] == "вышло дольше"


# --- the notebook ----------------------------------------------------------


async def test_the_notebook_is_one_entry_per_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Saved twice, still one record — the notebook is edited in place.

    It lives in `journal_entries` rather than in a table of its own: the day
    already has a place for prose, and a second one would give "что я писал
    30-го" two answers.
    """
    first = await client.put(f"{DAY_PATH}/notebook", json={"content": "утро: тихо"})
    assert first.status_code == 200

    second = await client.put(
        f"{DAY_PATH}/notebook", json={"content": "утро: тихо\nвечер: успел"}
    )
    assert second.status_code == 200
    assert second.json()["content"] == "утро: тихо\nвечер: успел"

    result = await db_session.execute(
        select(JournalEntry).where(JournalEntry.entry_date == MARK_DAY)
    )
    entries = list(result.scalars().all())
    assert len(entries) == 1
    assert entries[0].content == "утро: тихо\nвечер: успел"


async def test_the_notebook_comes_back_with_the_day(client: AsyncClient) -> None:
    """The screen reads the notebook from the day it belongs to, not separately."""
    empty = await client.get(DAY_PATH)
    assert empty.json()["notebook"] is None

    await client.put(f"{DAY_PATH}/notebook", json={"content": "чувствую себя ровно"})

    filled = await client.get(DAY_PATH)
    assert filled.json()["notebook"] == "чувствую себя ровно"
    assert filled.json()["day"]["opened_at"] is not None
