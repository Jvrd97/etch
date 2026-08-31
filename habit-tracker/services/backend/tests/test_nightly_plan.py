"""
Ночной прогон-страховка: день не остаётся без плана (`#151`).

Каждый пункт Acceptance тикета здесь словами тикета: прогон на дне с планом не
пишет ничего; прогон на дне без плана пишет скелет с пометкой `needs_review`;
завтра выходной — прогон молчит и говорит об этом кодом выхода; два
одновременных прогона дают одну строку плана; завтрашняя дата берётся у
`local_date()`, а не считается своей арифметикой; пометка снимается первой
правкой или первой отметкой; модель не зовётся ни при каких условиях; задание
стоит в расписании единственного планировщика.

Advisory lock мокать бессмысленно, поэтому прогоны идут против настоящей базы, а
одновременность — двумя настоящими соединениями.
"""

# [review:need-review] PHASE-03/151
# summary: tests of the nightly safety net — nothing written where a plan exists, a `needs_review` skeleton where none does, the exit code of a day off, two concurrent runs serialised by the advisory lock into one plan, tomorrow taken from the published day boundary, the badge cleared by the first edit and by the first mark, the model never called, and the job present in the one scheduler
from collections.abc import AsyncGenerator
from pathlib import Path
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import daytime
from app.core.daytime import today_local
from app.crud import day as day_crud
from app.jobs import nightly
from app.jobs.nightly import JOB_NAME, NightlyOutcome, nightly_once
from app.models.plan import DayPlan
from app.scheduling.registry import registry

from tests.conftest import TestSessionLocal

DAY_URL = "/api/v1/day"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """Таблица правил и цель квартала; `create_all` их не заводит."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


async def workday_after(db: AsyncSession, on: date) -> date:
    """Ближайший рабочий день строго после `on` — по канону, а не по календарю."""
    rule = await day_crud.rule_for_date(db, on)
    candidate = on + timedelta(days=1)
    while candidate.isoweekday() not in rule.workdays:
        candidate += timedelta(days=1)
    return candidate


async def day_off_after(db: AsyncSession, on: date) -> date:
    """Ближайший нерабочий день строго после `on`."""
    rule = await day_crud.rule_for_date(db, on)
    candidate = on + timedelta(days=1)
    while candidate.isoweekday() in rule.workdays:
        candidate += timedelta(days=1)
    return candidate


async def plans(session: AsyncSession) -> int:
    count = await session.scalar(select(func.count()).select_from(DayPlan))
    return int(count or 0)


def task(code: str, window: str = "09:00-11:00", **overrides: Any) -> dict[str, Any]:
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


async def test_a_day_that_already_has_a_plan_is_left_alone(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """Число строк плана до и после прогона совпадает."""
    target = await workday_after(db_session, today_local())
    written = await client.post(
        f"{DAY_URL}/{target.isoformat()}/plan",
        json={
            "title": "Уже есть",
            "sections": [{"kind": "work", "items": [task("W1")]}],
        },
    )
    assert written.status_code == 201, written.text
    before = await plans(db_session)

    outcome = await nightly_once(db_session, target=target)

    assert outcome is NightlyOutcome.PLAN_EXISTS
    assert outcome.exit_code == 10
    assert await plans(db_session) == before


async def test_a_day_with_no_plan_gets_a_skeleton_marked_unreviewed(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """Скелет записан, и утром на экране дня видно, что его никто не смотрел."""
    target = await workday_after(db_session, today_local())

    outcome = await nightly_once(db_session, target=target)

    assert outcome is NightlyOutcome.WRITTEN
    assert outcome.exit_code == 0
    read = await client.get(f"{DAY_URL}/{target.isoformat()}")
    assert read.status_code == 200, read.text
    plan = read.json()["plan"]
    assert plan is not None
    assert plan["needs_review"] is True


async def test_a_day_off_is_not_planned_and_says_so_with_its_exit_code(
    db_session: AsyncSession,
) -> None:
    """Завтра выходной — прогон не пишет ничего, и это видно кодом возврата."""
    target = await day_off_after(db_session, today_local())
    before = await plans(db_session)

    outcome = await nightly_once(db_session, target=target)

    assert outcome is NightlyOutcome.DAY_OFF
    assert outcome.exit_code == 11
    assert await plans(db_session) == before


async def test_two_runs_at_once_leave_one_plan(db_session: AsyncSession) -> None:
    """
    Второй прогон уходит на advisory lock и не создаёт дубля.

    Двумя настоящими соединениями: блокировка транзакционная, и на одной сессии
    проверялось бы не то. Первая сессия коммитит, чтобы вторая её увидела.
    """
    target = await workday_after(db_session, today_local())
    await db_session.commit()

    outcomes: list[NightlyOutcome] = []
    async with TestSessionLocal() as first, TestSessionLocal() as second:
        for session in (first, second):
            await day_crud.list_rules(session)
            outcome = await nightly_once(session, target=target)
            outcomes.append(outcome)
            await session.commit()

    assert outcomes == [NightlyOutcome.WRITTEN, NightlyOutcome.PLAN_EXISTS]
    async with TestSessionLocal() as check:
        assert await plans(check) == 1


async def test_tomorrow_comes_from_the_published_day_boundary(
    db_session: AsyncSession,
) -> None:
    """
    Завтра — это `today_local() + 1`, а не арифметика по `day_start_hour`.

    Подменяется само `today_local`: если бы `nightly` считал дату сам, подмена
    ничего бы не изменила и тест бы упал.
    """
    pinned = date(2026, 8, 30)
    original = daytime.today_local
    try:
        nightly.today_local = lambda: pinned  # type: ignore[assignment]
        assert nightly.tomorrow() == date(2026, 8, 31)
    finally:
        nightly.today_local = original  # type: ignore[assignment]


async def test_the_run_never_calls_the_model(db_session: AsyncSession) -> None:
    """
    Модель не зовётся ни при каких условиях.

    Двумя заслонами сразу: подменённый вход в LLM падает, если его тронули, и
    греп по модулю не находит ни одного импорта из `app.llm`. LLM-план по дню,
    которого никто не закрывал, собрался бы из пустоты и выглядел бы
    убедительнее, чем есть.
    """
    from app.llm import client as llm_client
    from app.llm import cli as llm_cli

    called: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        called.append("llm")
        raise AssertionError("ночной прогон не имеет права звать модель")

    target = await workday_after(db_session, today_local())
    original_resolve = llm_client.resolve_insights_client
    original_cli = llm_cli.IsolatedCli
    try:
        llm_client.resolve_insights_client = refuse  # type: ignore[assignment]
        llm_cli.IsolatedCli = refuse  # type: ignore[misc, assignment]
        outcome = await nightly_once(db_session, target=target)
    finally:
        llm_client.resolve_insights_client = original_resolve  # type: ignore[assignment]
        llm_cli.IsolatedCli = original_cli  # type: ignore[misc]

    assert outcome is NightlyOutcome.WRITTEN
    assert called == []
    source = Path(nightly.__file__).read_text(encoding="utf-8")
    assert "app.llm" not in source


async def test_the_badge_is_cleared_by_the_first_edit(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """Правка пункта — это «человек посмотрел план»."""
    target = await workday_after(db_session, today_local())
    await nightly_once(db_session, target=target)
    read = await client.get(f"{DAY_URL}/{target.isoformat()}")
    item_id = read.json()["plan"]["sections"][0]["items"][0]["id"]

    edited = await client.patch(
        f"{DAY_URL}/{target.isoformat()}/plan/items/{item_id}",
        json={"text_md": "Подъём, но позже"},
    )

    assert edited.status_code == 200, edited.text
    again = await client.get(f"{DAY_URL}/{target.isoformat()}")
    assert again.json()["plan"]["needs_review"] is False


async def test_the_badge_is_cleared_by_the_first_mark(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """Отметка — тоже «посмотрел»: план перестал быть непрочитанным."""
    target = today_local()
    await nightly_once(db_session, target=target)
    read = await client.get(f"{DAY_URL}/{target.isoformat()}")
    if read.json()["plan"] is None:
        pytest.skip("сегодня выходной по канону: ночной прогон на него не пишет")
    item_id = read.json()["plan"]["sections"][0]["items"][0]["id"]

    marked = await client.put(
        f"{DAY_URL}/{target.isoformat()}/marks/{item_id}", json={"state": "done"}
    )

    assert marked.status_code == 200, marked.text
    again = await client.get(f"{DAY_URL}/{target.isoformat()}")
    assert again.json()["plan"]["needs_review"] is False


def test_the_job_is_registered_in_the_one_scheduler() -> None:
    """
    Задание стоит в реестре `#108`, а не в crontab на VPS.

    Реестр — единственный список того, что крутится в фоне; задание, которого в
    нём нет, не попадёт ни в лог расписания, ни в `deploy/README.md`.
    """
    assert JOB_NAME in registry.names
    job = registry.get(JOB_NAME)
    assert job.func is nightly.run_nightly
    assert job.timeout_seconds == nightly.NIGHTLY_TIMEOUT_SECONDS
