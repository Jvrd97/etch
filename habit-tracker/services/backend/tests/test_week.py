"""
The week: its ISO arithmetic, the snapshot it stores, and what a recompute may
and may not touch.

The one sentence the whole file is about: пересчёт меняет счётчики и
`computed_at`, но не трогает текст ретро. A retro asserts what was true when it
was written; a day reopened in November has to move the numbers without silently
rewriting the sentence beside them.
"""

# [review:need-review] PHASE-03/94
# summary: tests for the week — ISO codes and bounds including the year edges, a week without a retro exists and opens, recompute after reopening a day moves the counters and computed_at while the prose stays put, PUT replaces the checklist, and the parse of a `weeks/**/*.md` file splits the blocks without taking the counters from the prose
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.day.week import BadWeekCode, iso_code, week_bounds, week_codes
from app.imports import week_md

DAY_URL = "/api/v1/day"
WEEKS_URL = "/api/v1/weeks"

# The week the ticket was written in: Monday 24 to Sunday 30 August 2026.
WEEK = "2026-W35"
MONDAY = date(2026, 8, 24)
SUNDAY = date(2026, 8, 30)

# A week nobody has ever written a word about.
EMPTY_WEEK = "2026-W40"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """The rule table as a migrated database has it, plus goal 1 of the quarter."""
    await day_crud.seed_rules(db_session)
    yield


# --- the ISO arithmetic, decided without a database -------------------------


def test_a_date_names_its_iso_week() -> None:
    assert iso_code(MONDAY) == WEEK
    assert iso_code(SUNDAY) == WEEK


def test_a_week_runs_monday_to_sunday() -> None:
    assert week_bounds(WEEK) == (MONDAY, SUNDAY)


def test_the_first_of_january_can_belong_to_last_years_week() -> None:
    """
    The reason `date.isocalendar()` is used rather than hand-rolled arithmetic.

    2026-01-01 is a Thursday, so it opens `2026-W01`; 2027-01-01 is a Friday and
    belongs to `2026-W53`. A week derived from `weekday()` and a timedelta gets
    one of these wrong, and then a day quietly lands in a week it is not in.
    """
    assert iso_code(date(2026, 1, 1)) == "2026-W01"
    assert iso_code(date(2027, 1, 1)) == "2026-W53"


def test_a_code_that_names_no_week_is_refused() -> None:
    for bad in ("2026-35", "2026-W", "неделя", "2026-W35-extra", "2027-W53"):
        with pytest.raises(BadWeekCode):
            week_bounds(bad)


def test_a_range_names_every_week_it_touches() -> None:
    """A range from mid-week to mid-week touches the weeks on both of its edges."""
    codes = week_codes(date(2026, 8, 26), date(2026, 9, 2))
    assert codes == ["2026-W35", "2026-W36"]


# --- the week the API answers with ------------------------------------------


def _task(code: str, window: str = "09:00-10:00") -> dict[str, Any]:
    return {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }


async def _post_plan(client: AsyncClient, on: date) -> str:
    """A one-task plan for `on`; answers with the id of that task."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={"sections": [{"kind": "work", "title": "День", "items": [_task("W1")]}]},
    )
    assert response.status_code == 201, response.text
    item_id: str = response.json()["sections"][0]["items"][0]["id"]
    return item_id


async def _win(client: AsyncClient, on: date) -> None:
    """Plan a day, close its single task and close the day: a won day."""
    item_id = await _post_plan(client, on)
    await client.put(
        f"{DAY_URL}/{on.isoformat()}/marks/{item_id}", json={"state": "done"}
    )
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/close", json={"body_md": ""}
    )
    assert response.status_code == 200, response.text


async def test_a_week_without_a_retro_exists_and_opens(client: AsyncClient) -> None:
    """
    The acceptance case: nobody wrote about this week and it still answers.

    404 is reserved for a code that names no week at all. «Ретро не написано» is
    a fact about the week — empty prose — rather than an absence of it, because
    the days of that week happened whether or not Sunday came around.
    """
    response = await client.get(f"{WEEKS_URL}/{EMPTY_WEEK}")

    assert response.status_code == 200
    body = response.json()
    assert body["iso_code"] == EMPTY_WEEK
    assert body["retro_md"] == ""
    assert body["review_items"] == []
    assert body["won_days"] == 0
    assert body["computed_at"] is not None


async def test_a_code_that_names_no_week_is_a_404(client: AsyncClient) -> None:
    response = await client.get(f"{WEEKS_URL}/2026-W99")

    assert response.status_code == 404


async def test_the_week_counts_won_days_and_the_streak_at_its_end(
    client: AsyncClient,
) -> None:
    await _win(client, MONDAY)
    await _win(client, date(2026, 8, 25))

    response = await client.get(f"{WEEKS_URL}/{WEEK}")

    body = response.json()
    assert body["won_days"] == 2
    # Both days exist as rows, and so does every day the plan write created.
    assert body["total_days"] >= 2
    assert body["streak_end"] == 2
    assert body["starts_on"] == MONDAY.isoformat()
    assert body["ends_on"] == SUNDAY.isoformat()


async def test_the_streak_is_null_while_no_day_of_the_week_is_closed(
    client: AsyncClient,
) -> None:
    """`null` is «ни один день не закрыт», which is not «стрик 0»."""
    await _post_plan(client, MONDAY)

    body = (await client.get(f"{WEEKS_URL}/{WEEK}")).json()

    assert body["streak_end"] is None
    assert body["won_days"] == 0


async def test_recompute_moves_the_counters_and_the_stamp_but_not_the_retro(
    client: AsyncClient,
) -> None:
    """
    The acceptance case the whole table exists for.

    A retro written on Sunday says «0 из 7». Monday is then reopened and closed
    as won. The counters and `computed_at` move; the sentence does not.
    """
    retro = "## Выигранные дни\n\n**0 из 7.** Данных за понедельник нет."
    written = await client.put(
        f"{WEEKS_URL}/{WEEK}",
        json={"retro_md": retro, "blockers_md": "Отчёт пуст второй день"},
    )
    assert written.status_code == 200, written.text
    before = written.json()
    assert before["won_days"] == 0

    await _win(client, MONDAY)

    after = (await client.get(f"{WEEKS_URL}/{WEEK}")).json()

    assert after["won_days"] == 1
    assert after["computed_at"] > before["computed_at"]
    assert after["retro_md"] == retro
    assert after["blockers_md"] == "Отчёт пуст второй день"


async def test_the_write_replaces_the_sunday_checklist(client: AsyncClient) -> None:
    first = await client.put(
        f"{WEEKS_URL}/{WEEK}",
        json={
            "retro_md": "разбор",
            "review_items": [
                {"text_md": "Решить: SQLite под отметки", "done": True},
                {"text_md": "Петиция в ЕС, шаг 1", "done": False},
            ],
        },
    )
    assert first.status_code == 200, first.text
    assert [item["done"] for item in first.json()["review_items"]] == [True, False]
    assert [item["ord"] for item in first.json()["review_items"]] == [1, 2]

    second = await client.put(
        f"{WEEKS_URL}/{WEEK}",
        json={
            "retro_md": "разбор",
            "review_items": [{"text_md": "Петиция в ЕС, шаг 1", "done": True}],
        },
    )

    items = second.json()["review_items"]
    assert len(items) == 1
    assert items[0]["done"] is True


async def test_the_counters_cannot_be_sent(client: AsyncClient) -> None:
    """
    A client able to send `won_days` would be a second opinion about the week.

    `extra="forbid"` turns that into a 422 rather than a silently ignored field,
    because a number that looks accepted and is not is worse than a refusal.
    """
    response = await client.put(
        f"{WEEKS_URL}/{WEEK}", json={"retro_md": "разбор", "won_days": 7}
    )

    assert response.status_code == 422


async def test_the_bare_weeks_route_answers_the_current_week(
    client: AsyncClient,
) -> None:
    response = await client.get(WEEKS_URL)

    assert response.status_code == 200
    assert week_bounds(response.json()["iso_code"])


async def test_the_week_needs_the_api_key(client: AsyncClient) -> None:
    response = await client.get(f"{WEEKS_URL}/{WEEK}", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401


# --- the file of `weeks/` as a week row -------------------------------------


WEEK_FILE = """# Неделя 2026-W35 (24-30 августа)

Файл заведён заранее, 28.08.

## На разбор в воскресенье

- [x] **Решить: SQLite под отметки** — решено 30.08.
- [ ] Петиция в ЕС, шаг 1 — не пройден.

## Выигранные дни

**0 из 7.** За 24-27.08 summary нет вообще.

## Что мешало

**1. День без отметок неотличим от дня без работы.**

## Mgmt-ретро

**Средний горизонт за неделю: одно касание.**
"""


def test_the_file_name_is_the_key_of_the_week() -> None:
    assert week_md.iso_from_name("2026-W35") == WEEK
    assert week_md.iso_from_name("notes 13.08.2026") is None


def test_the_parse_splits_the_blocks_into_their_columns() -> None:
    parsed = week_md.parse_week(WEEK, WEEK_FILE)

    assert parsed.blockers_md.startswith("**1. День без отметок")
    assert parsed.mgmt_retro_md.startswith("**Средний горизонт")
    # «Что мешало» and «Mgmt-ретро» left `retro_md`; everything else stayed.
    assert "Выигранные дни" in parsed.retro_md
    assert "День без отметок" not in parsed.retro_md
    assert "Средний горизонт" not in parsed.retro_md


def test_the_parse_reads_the_sunday_checklist_with_its_ticks() -> None:
    parsed = week_md.parse_week(WEEK, WEEK_FILE)

    assert [item.done for item in parsed.review_items] == [True, False]
    assert parsed.review_items[1].text_md.startswith("Петиция в ЕС")


def test_the_parse_never_takes_the_counters_from_the_prose() -> None:
    """
    «0 из 7» stays a sentence and does not become a column.

    The counters are read off `day_summary` by `recompute_week`. Parsing them
    out of the retro would give one week two answers with nothing saying which
    one is current.
    """
    body = week_md.parse_week(WEEK, WEEK_FILE).as_body()

    assert not hasattr(body, "won_days")
    assert "**0 из 7.**" in body.retro_md
