"""
Tests for GET /api/v1/days?from&to — the range the timeline and the sidebar read.
"""

# [review:need-review] PHASE-03/94, 309
# summary: #309 — the range asks as many statements on six hundred days of plans as on thirty, and done/total follow every state of a mark
# summary: API tests — the range answers in the shape the old /api/days had, a day nobody closed carries verdict null so three states are distinguishable, done/total count work tasks, and a backwards or oversized range is refused rather than scanned
from collections.abc import AsyncGenerator
from datetime import date, datetime, time, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.week import MAX_RANGE_DAYS
from app.crud import day as day_crud
from app.day.evaluate import VERDICT_LOST, VERDICT_WON
from app.day.rules import day_kind, is_nocode_date
from app.models.day import Day
from app.models.mark import PlanMark
from app.models.plan import DayPlan, PlanItem, PlanSection
from tests.conftest import SqlCounter, record_role_act

DAYS_URL = "/api/v1/days"
DAY_URL = "/api/v1/day"

# The week the ticket was written in: Monday 24 to Sunday 30 August 2026.
MONDAY = date(2026, 8, 24)
FRIDAY = date(2026, 8, 28)
SATURDAY = date(2026, 8, 29)
SUNDAY = date(2026, 8, 30)

# The five fields the old `/api/days` answered with. Named as a set so a field
# quietly dropped from the DTO fails here rather than in a browser. Проверяется
# вложением, а не равенством: старый читатель не ломается от нового поля рядом
# («#144» добавил `verdict_origin`), а ломается от пропавшего.
LEGACY_FIELDS = {"date", "title", "verdict", "done", "total"}


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it, plus goal 1 of the quarter.

    `create_all` never runs the migration's seed, so without this every day
    would be judged by a canon describing no date at all; `seeded_goal` is here
    because every task below names goal 1 and that column has a foreign key.
    """
    await day_crud.seed_rules(db_session)
    yield


def _plan(title: str, *, tasks: int) -> dict[str, object]:
    """A plan of `tasks` work tasks, each with the window and criterion #87 needs."""
    return {
        "title": title,
        "sections": [
            {
                "kind": "work",
                "title": "Работа",
                "items": [
                    {
                        "kind": "task",
                        "code": f"W{index}",
                        "text_md": f"Задача {index}",
                        "window": f"{8 + index:02d}:00-{9 + index:02d}:00",
                        "done_criterion": "письмо отправлено",
                        "quarter_goal_id": 1,
                    }
                    for index in range(1, tasks + 1)
                ],
            }
        ],
    }


async def _post_plan(
    client: AsyncClient, on: date, title: str, *, tasks: int
) -> list[str]:
    """Write a plan and answer with the ids of its work tasks, in order."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan", json=_plan(title, tasks=tasks)
    )
    assert response.status_code == 201, response.text
    return [item["id"] for item in response.json()["sections"][0]["items"]]


async def test_the_range_answers_in_the_shape_the_old_api_days_had(
    client: AsyncClient,
) -> None:
    """The acceptance case: the old consumer reads the answer without a rewrite."""
    await _post_plan(client, SUNDAY, "Воскресенье", tasks=2)

    response = await client.get(
        f"{DAYS_URL}?from={SUNDAY.isoformat()}&to={SUNDAY.isoformat()}"
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert LEGACY_FIELDS <= set(body[0])
    assert body[0]["date"] == SUNDAY.isoformat()
    assert body[0]["title"] == "Воскресенье"
    assert body[0]["total"] == 2
    assert body[0]["done"] == 0


async def test_an_unclosed_day_is_not_a_lost_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Three states, not two.

    `life.py` painted by a regular expression over prose and could only tell won
    from lost, so a day nobody had closed looked exactly like a day that was
    lost. Here the unclosed day carries `verdict: null`.
    """
    # Клауз роли (`#137`) закрыт только у пятницы: суббота проигрывается по
    # задачам, воскресенье не закрывают вовсе.
    await record_role_act(db_session, FRIDAY)
    items = await _post_plan(client, FRIDAY, "Пятница", tasks=1)
    await _post_plan(client, SATURDAY, "Суббота", tasks=1)
    # Friday closes with its one task done — a won day.
    await client.put(
        f"{DAY_URL}/{FRIDAY.isoformat()}/marks/{items[0]}", json={"state": "done"}
    )
    await client.post(f"{DAY_URL}/{FRIDAY.isoformat()}/close", json={"body_md": ""})
    # Saturday closes with nothing done — a lost day.
    await client.post(f"{DAY_URL}/{SATURDAY.isoformat()}/close", json={"body_md": ""})
    # Sunday is never closed at all.
    await client.get(f"{DAY_URL}/{SUNDAY.isoformat()}")

    response = await client.get(
        f"{DAYS_URL}?from={FRIDAY.isoformat()}&to={SUNDAY.isoformat()}"
    )

    assert response.status_code == 200
    verdicts = {row["date"]: row["verdict"] for row in response.json()}
    assert verdicts[FRIDAY.isoformat()] == VERDICT_WON
    assert verdicts[SATURDAY.isoformat()] == VERDICT_LOST
    assert verdicts[SUNDAY.isoformat()] is None


async def test_done_and_total_count_the_work_tasks_of_the_day(
    client: AsyncClient,
) -> None:
    items = await _post_plan(client, SUNDAY, "Воскресенье", tasks=3)
    await client.put(
        f"{DAY_URL}/{SUNDAY.isoformat()}/marks/{items[0]}", json={"state": "done"}
    )
    await client.put(
        f"{DAY_URL}/{SUNDAY.isoformat()}/marks/{items[1]}", json={"state": "failed"}
    )

    response = await client.get(
        f"{DAYS_URL}?from={SUNDAY.isoformat()}&to={SUNDAY.isoformat()}"
    )

    row = response.json()[0]
    assert row["done"] == 1
    assert row["total"] == 3


async def test_days_come_back_oldest_first(client: AsyncClient) -> None:
    await _post_plan(client, MONDAY, "Понедельник", tasks=1)
    await _post_plan(client, SUNDAY, "Воскресенье", tasks=1)

    response = await client.get(
        f"{DAYS_URL}?from={MONDAY.isoformat()}&to={SUNDAY.isoformat()}"
    )

    dates = [row["date"] for row in response.json()]
    assert dates == sorted(dates)
    assert dates[0] == MONDAY.isoformat()


async def test_a_range_with_no_days_is_empty_rather_than_a_404(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{DAYS_URL}?from=2020-01-01&to=2020-01-07")

    assert response.status_code == 200
    assert response.json() == []


async def test_a_backwards_range_is_refused(client: AsyncClient) -> None:
    response = await client.get(
        f"{DAYS_URL}?from={SUNDAY.isoformat()}&to={MONDAY.isoformat()}"
    )

    assert response.status_code == 422


async def test_an_oversized_range_is_refused_rather_than_scanned(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{DAYS_URL}?from=1970-01-01&to={SUNDAY.isoformat()}")

    assert response.status_code == 422
    assert str(MAX_RANGE_DAYS) in response.json()["detail"]


async def test_the_range_needs_the_api_key(client: AsyncClient) -> None:
    response = await client.get(
        f"{DAYS_URL}?from={SUNDAY.isoformat()}&to={SUNDAY.isoformat()}",
        headers={"X-API-Key": "wrong"},
    )

    assert response.status_code == 401


# --- the number of statements (#309) -------------------------------------------


async def _fill_plans(db: AsyncSession, first: date, count: int) -> None:
    """
    `count` days from `first`, each with a plan of two tasks and an anchor.

    Written through the models, not the endpoint: six hundred plans through
    `POST /day/{date}/plan` would test the writer for a minute; this test is
    about the reader. Every day marks its first task done.
    """
    rule = await day_crud.rule_for_date(db, first)
    for offset in range(count):
        on = first + timedelta(days=offset)
        db.add(
            Day(
                day_date=on,
                rule_set_id=rule.id,
                kind=day_kind(rule, on),
                is_nocode=is_nocode_date(rule, on),
            )
        )
        plan = DayPlan(day_date=on, title=f"План {offset}")
        section = PlanSection(plan=plan, ord=0, kind="work")
        moment = datetime.combine(on, time(9), tzinfo=timezone.utc)
        tasks = [
            PlanItem(
                section=section,
                ord=index,
                kind="task",
                text_md=f"Задача {index}",
                text_plain=f"Задача {index}",
                starts_at=moment,
                ends_at=moment + timedelta(hours=1),
                done_criterion="сделано",
                unlinked_reason="тест",
            )
            for index in range(2)
        ]
        PlanItem(
            section=section, ord=2, kind="anchor", text_md="Якорь", text_plain="Якорь"
        )
        db.add(plan)
        await db.flush()
        db.add(PlanMark(item_id=tasks[0].id, state="done"))
    await db.flush()


async def test_reading_days_costs_the_same_on_thirty_days_or_six_hundred(
    client: AsyncClient, db_session: AsyncSession, sql_counter: SqlCounter
) -> None:
    """
    The class of error: a read that grows with the plans of the range.

    Six hundred days hold six hundred sections — more than one `IN (...)` batch
    of a `selectinload`, which splits by 500 — so a loader that reads the plan
    tree in batches asks more statements here than on thirty days.
    """
    first = date(2024, 1, 1)
    await _fill_plans(db_session, first, 30)
    with sql_counter() as small:
        response = await client.get(f"{DAYS_URL}?from=2024-01-01&to=2024-01-30")
    assert response.status_code == 200
    assert {(row["done"], row["total"]) for row in response.json()} == {(1, 2)}

    await _fill_plans(db_session, first + timedelta(days=30), 570)
    last = first + timedelta(days=599)
    with sql_counter() as large:
        response = await client.get(f"{DAYS_URL}?from=2024-01-01&to={last}")
    assert len(response.json()) == 600

    assert large.queries == small.queries


async def test_done_and_total_follow_every_state_of_a_mark(
    client: AsyncClient,
) -> None:
    """`done` counts the done tasks only; `total` is every task of the plan, whatever its mark."""
    items = await _post_plan(client, SUNDAY, "Воскресенье", tasks=4)
    for item, state in zip(items, ("done", "skipped", "failed")):
        marked = await client.put(
            f"{DAY_URL}/{SUNDAY.isoformat()}/marks/{item}", json={"state": state}
        )
        assert marked.status_code == 200, marked.text

    response = await client.get(
        f"{DAYS_URL}?from={SUNDAY.isoformat()}&to={SUNDAY.isoformat()}"
    )

    row = response.json()[0]
    assert (row["done"], row["total"]) == (1, 4)
    assert row["title"] == "Воскресенье"
