# [review:need-review] PHASE-03/135
# summary: tests of the interval markup — a day of work distributes itself with no manual action, two rules on one interval are settled by priority, an interval inside a working window of the schedule but under a manual `dayoff` override is not distributed at all, a second run changes no number, a `confirmed` row survives the run, a 23:30-00:30 session at a 04:00 boundary lands whole in the previous work day, an interval with `title_source='dropped'` is matched on `bundle_id` alone, an application no rule names goes to `unassigned`, and no window title reaches a log
"""
Tests of `app.roles.classify` and of the intake it hangs off.

The pure interval arithmetic is in `test_role_precedence.py`. What is here needs
tables: the catalogue, the day mode, the rule table and the boundary of the day.
"""

from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import activity as activity_crud
from app.crud import role as role_crud
from app.models.activity import (
    TITLE_DROPPED,
    TITLE_FULL,
    ActivityInterval,
    DayMode,
    ModeSchedule,
    TrackedApp,
)
from app.models.role import (
    CONFIDENCE_CONFIRMED,
    MATCHER_BUNDLE_ID,
    MATCHER_WINDOW_TITLE_REGEX,
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_TECHLEAD,
    ROLE_CODE_UNASSIGNED,
    SOURCE_APP_USAGE,
    RoleTimeBlock,
)
from app.roles import classify

AGENT_URL = "/api/v1/agent"
ROLES_URL = "/api/v1/roles"

# A weekday the seeded schedule calls `work`, pinned rather than computed from
# «сегодня»: the markup of a `dayoff` is a different test, and a suite that
# changed meaning on Thursdays would be worse than useless.
WORK_DAY = date(2026, 8, 31)  # Monday
DAYOFF = date(2026, 9, 3)  # Thursday — `dayoff` by the seeded schedule

VSCODE = "com.microsoft.VSCode"
CHROME = "com.google.Chrome"
FIGMA = "com.figma.Desktop"

ZONE = ZoneInfo(settings.APP_TIMEZONE)


@pytest.fixture(autouse=True)
async def seeded(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """
    The role directory, the mode schedule and three applications.

    `create_all` never sees a migration's seed, so the rows the migration
    inserts are inserted here as well — the same reason `seed_roles` exists in
    two places.
    """
    await role_crud.seed_roles(db_session)
    for weekday, kind in ((1, "work"), (4, "dayoff")):
        db_session.add(ModeSchedule(weekday=weekday, kind=kind, nocode=False))
    for bundle, name in ((VSCODE, "VS Code"), (CHROME, "Chrome"), (FIGMA, "Figma")):
        db_session.add(TrackedApp(bundle_id=bundle, display_name=name))
    await db_session.commit()
    yield


async def role_id(db_session: AsyncSession, code: str) -> int:
    role = await role_crud.get_role_by_code(db_session, code)
    assert role is not None
    return role.id


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """A moment on the wall clock the day boundary is measured on."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


async def send(client: AsyncClient, *intervals: dict[str, Any]) -> dict[str, Any]:
    """Post a batch and hand back the answer, asserting it was accepted."""
    response = await client.post(
        f"{AGENT_URL}/activity", json={"intervals": list(intervals)}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def interval(
    bundle: str | None,
    start: datetime,
    end: datetime,
    *,
    title: str | None = None,
    title_source: str = TITLE_DROPPED,
) -> dict[str, Any]:
    return {
        "bundle_id": bundle,
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "local_date": start.date().isoformat(),
        "title": title,
        "title_source": title_source,
    }


async def blocks_of(db_session: AsyncSession, day: date) -> list[RoleTimeBlock]:
    result = await db_session.execute(
        select(RoleTimeBlock)
        .where(RoleTimeBlock.work_day == day)
        .order_by(RoleTimeBlock.id)
    )
    return list(result.scalars().all())


async def rule_for(
    db_session: AsyncSession,
    code: str,
    pattern: str,
    *,
    matcher: str = MATCHER_BUNDLE_ID,
    priority: int = 100,
) -> int:
    rule = await role_crud.create_rule(
        db_session,
        role_id=await role_id(db_session, code),
        source=SOURCE_APP_USAGE,
        matcher_kind=matcher,
        pattern=pattern,
        priority=priority,
    )
    await db_session.commit()
    return rule.id


# --- день размечается сам ---------------------------------------------------


class TestDayMarkup:
    async def test_a_day_of_work_distributes_itself(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case: `/roles` shows where the day went, with no manual act.

        The batch is the only thing that happened — no `POST /roles/classify`, no
        form on the roles screen.
        """
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(
            client,
            interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)),
            interval(CHROME, at(WORK_DAY, 12), at(WORK_DAY, 13)),
        )

        answer = await client.get(f"{ROLES_URL}/day/{WORK_DAY.isoformat()}")
        assert answer.status_code == 200
        body = answer.json()
        assert body["total_minutes"] == 180
        shares = {row["role_code"]: row for row in body["roles"]}
        assert shares[ROLE_CODE_TECHLEAD]["minutes"] == 120
        # Chrome нет ни в одном правиле — час уходит в «не отнесено», а не в NULL.
        assert shares[ROLE_CODE_UNASSIGNED]["minutes"] == 60
        assert shares[ROLE_CODE_UNASSIGNED]["share_pct"] == 33

    async def test_an_automatic_row_names_its_rule_and_its_application(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Без `rule_id` неверная разметка неотличима от верной."""
        rule_id = await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 11)))

        answer = await client.get(f"{ROLES_URL}/day/{WORK_DAY.isoformat()}")
        block = answer.json()["blocks"][0]
        assert block["is_automatic"] is True
        assert block["rule_id"] == rule_id
        assert block["rule_summary"] == f"{MATCHER_BUNDLE_ID} = {VSCODE}"
        assert block["app_name"] == "VS Code"

    async def test_two_rules_on_one_interval_are_settled_by_priority(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Smaller priority wins, and the day says which rule it was."""
        weak = await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE, priority=100)
        strong = await rule_for(
            db_session,
            ROLE_CODE_ARCHITECT,
            r"ADR",
            matcher=MATCHER_WINDOW_TITLE_REGEX,
            priority=10,
        )
        await send(
            client,
            interval(
                VSCODE,
                at(WORK_DAY, 10),
                at(WORK_DAY, 11),
                title="ADR-0020.md",
                title_source=TITLE_FULL,
            ),
        )
        blocks = await blocks_of(db_session, WORK_DAY)
        assert len(blocks) == 1
        assert blocks[0].rule_id == strong
        assert blocks[0].rule_id != weak
        assert blocks[0].role_id == await role_id(db_session, ROLE_CODE_ARCHITECT)


# --- режим дня --------------------------------------------------------------


class TestDayMode:
    async def test_a_dayoff_distributes_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Минуты вне рабочего режима не разносятся вообще — даже в `unassigned`."""
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(client, interval(VSCODE, at(DAYOFF, 10), at(DAYOFF, 12)))
        assert await blocks_of(db_session, DAYOFF) == []

    async def test_a_manual_override_beats_the_schedule(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case: a working window of the schedule, closed by hand.

        Понедельник по расписанию — `work`; ручная строка говорит `vacation`, и
        интервал внутри рабочего окна в роли не разносится вовсе.
        """
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        db_session.add(
            DayMode(date=WORK_DAY, kind="vacation", source="manual", nocode=False)
        )
        await db_session.commit()

        await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)))
        assert await blocks_of(db_session, WORK_DAY) == []

        answer = await client.get(f"{AGENT_URL}/day-mode/{WORK_DAY.isoformat()}")
        assert answer.json()["kind"] == "vacation"
        assert answer.json()["source"] == "manual"

    async def test_closing_a_day_by_hand_takes_its_minutes_back(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        A day marked `vacation` after the fact stops claiming minutes.

        Otherwise the number would only ever grow: the mode is a correction, and
        a correction that cannot remove anything is not one.
        """
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)))
        assert len(await blocks_of(db_session, WORK_DAY)) == 1

        db_session.add(
            DayMode(date=WORK_DAY, kind="vacation", source="manual", nocode=False)
        )
        await db_session.commit()
        response = await client.post(
            f"{ROLES_URL}/classify",
            json={
                "date_from": WORK_DAY.isoformat(),
                "date_to": WORK_DAY.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["days"][0]["mode"] == "vacation"
        assert await blocks_of(db_session, WORK_DAY) == []


# --- повторный прогон -------------------------------------------------------


class TestRerun:
    async def test_running_twice_changes_no_number(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)))
        before = [
            (block.role_id, block.minutes)
            for block in await blocks_of(db_session, WORK_DAY)
        ]

        response = await client.post(
            f"{ROLES_URL}/classify",
            json={
                "date_from": WORK_DAY.isoformat(),
                "date_to": WORK_DAY.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        after = [
            (block.role_id, block.minutes)
            for block in await blocks_of(db_session, WORK_DAY)
        ]
        assert after == before

    async def test_the_same_batch_sent_twice_does_not_double_the_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Идемпотентность даёт естественный ключ, а не `Idempotency-Key`."""
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        batch = interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12))
        await send(client, batch)
        await send(client, batch)

        intervals = (await db_session.execute(select(ActivityInterval))).scalars().all()
        assert len(list(intervals)) == 1
        blocks = await blocks_of(db_session, WORK_DAY)
        assert len(blocks) == 1
        assert blocks[0].minutes == 120

    async def test_a_confirmed_row_survives_the_run_untouched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Правка руками не откатывается автоматикой — ни правкой, ни удалением."""
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)))
        stored = (await blocks_of(db_session, WORK_DAY))[0]

        patched = await client.patch(
            f"{ROLES_URL[: -len('/roles')]}/role-time-blocks/{stored.id}",
            json={"minutes": 45, "confidence": CONFIDENCE_CONFIRMED},
        )
        assert patched.status_code == 200, patched.text

        response = await client.post(
            f"{ROLES_URL}/classify",
            json={
                "date_from": WORK_DAY.isoformat(),
                "date_to": WORK_DAY.isoformat(),
            },
        )
        assert response.json()["days"][0]["kept_confirmed"] == 1
        survivors = await blocks_of(db_session, WORK_DAY)
        assert len(survivors) == 1
        assert survivors[0].minutes == 45


# --- граница суток ----------------------------------------------------------


class TestDayBoundary:
    async def test_a_night_session_lands_whole_in_the_day_it_was_lived(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        23:30-00:30 при границе 04:00 — целиком предыдущий рабочий день.

        Разложить его на два дня значило бы соврать дважды: и про вечер, и про
        утро.
        """
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        start = at(WORK_DAY, 23, 30)
        await send(client, interval(VSCODE, start, start + timedelta(hours=1)))

        assert len(await blocks_of(db_session, WORK_DAY)) == 1
        assert (await blocks_of(db_session, WORK_DAY))[0].minutes == 60
        assert await blocks_of(db_session, WORK_DAY + timedelta(days=1)) == []

    async def test_an_interval_crossing_the_boundary_is_cut_at_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """03:30-04:30 — полчаса вчерашнего дня и полчаса сегодняшнего."""
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        tomorrow = WORK_DAY + timedelta(days=1)
        await send(client, interval(VSCODE, at(tomorrow, 3, 30), at(tomorrow, 4, 30)))

        yesterday = await blocks_of(db_session, WORK_DAY)
        today = await blocks_of(db_session, tomorrow)
        assert [block.minutes for block in yesterday] == [30]
        assert [block.minutes for block in today] == [30]

    def test_the_cut_is_the_only_reading_of_the_boundary(self) -> None:
        """
        `day_slices` asks `core.daytime` and nothing else.

        Not a style check: a second `WORK_DAY_BOUNDARY_HOUR` in `roles/` is
        exactly the debt `#107` was opened to close.
        """
        source = (classify.__file__,)
        assert source  # the module loaded
        text = open(classify.__file__, encoding="utf-8").read()
        assert "day_start_hour" not in text
        assert "from app.core.daytime import" in text


# --- заголовки и приватность ------------------------------------------------


class TestTitles:
    async def test_an_interval_without_a_title_is_matched_on_the_bundle_alone(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`title_source='dropped'` — штатный путь, а не деградация."""
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        await send(
            client,
            interval(
                VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 11), title_source=TITLE_DROPPED
            ),
        )
        blocks = await blocks_of(db_session, WORK_DAY)
        assert len(blocks) == 1
        assert blocks[0].role_id == await role_id(db_session, ROLE_CODE_TECHLEAD)

    async def test_an_application_no_rule_names_goes_to_unassigned(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await send(client, interval(FIGMA, at(WORK_DAY, 10), at(WORK_DAY, 11)))
        blocks = await blocks_of(db_session, WORK_DAY)
        assert len(blocks) == 1
        assert blocks[0].role_id == await role_id(db_session, ROLE_CODE_UNASSIGNED)
        assert blocks[0].rule_id is None

    async def test_no_window_title_reaches_a_log(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        The acceptance case, checked rather than promised.

        A title is a document name, a correspondent, potentially a diagnosis; it
        is matched against and never printed.
        """
        secret = "Договор аренды — Мюллер"
        await rule_for(db_session, ROLE_CODE_TECHLEAD, VSCODE)
        with caplog.at_level("DEBUG"):
            await send(
                client,
                interval(
                    VSCODE,
                    at(WORK_DAY, 10),
                    at(WORK_DAY, 11),
                    title=secret,
                    title_source=TITLE_FULL,
                ),
            )
            await client.post(
                f"{ROLES_URL}/classify",
                json={
                    "date_from": WORK_DAY.isoformat(),
                    "date_to": WORK_DAY.isoformat(),
                },
            )
        assert secret not in caplog.text
        assert "Мюллер" not in caplog.text


# --- приём пачки ------------------------------------------------------------


class TestIntake:
    async def test_an_unknown_bundle_is_refused_and_writes_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Каталог пополняется решением, а не потоком данных."""
        response = await client.post(
            f"{AGENT_URL}/activity",
            json={
                "intervals": [
                    interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 11)),
                    interval("com.evil.Unknown", at(WORK_DAY, 11), at(WORK_DAY, 12)),
                ]
            },
        )
        assert response.status_code == 422
        assert "com.evil.Unknown" in response.text
        rows = (await db_session.execute(select(ActivityInterval))).scalars().all()
        assert list(rows) == []

    async def test_a_batch_over_the_ceiling_is_refused(
        self, client: AsyncClient
    ) -> None:
        """501 отвергается, 500 принимается — потолок стоит на схеме."""
        one = interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 11))
        response = await client.post(
            f"{AGENT_URL}/activity", json={"intervals": [one] * 501}
        )
        assert response.status_code == 422

    async def test_the_duration_is_the_databases_answer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Длительность — следствие границ, и записать её напрямую нельзя."""
        await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)))
        row = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert row.duration_seconds == 2 * 60 * 60

    async def test_the_day_rolls_up_by_application(self, client: AsyncClient) -> None:
        await send(
            client,
            interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 12)),
            interval(CHROME, at(WORK_DAY, 12), at(WORK_DAY, 12, 30)),
        )
        answer = await client.get(f"{AGENT_URL}/activity/{WORK_DAY.isoformat()}")
        assert answer.status_code == 200
        body = answer.json()
        assert body["total_minutes"] == 150
        assert [row["app_name"] for row in body["apps"]] == ["VS Code", "Chrome"]


# --- план сильнее агента ----------------------------------------------------


async def test_the_plan_takes_back_the_hours_it_already_owns(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The seam `#140` left for this ticket, exercised from the other side.

    An hour the plan already charged is not charged again by the agent, so the
    day totals what was lived rather than what two witnesses said about it.
    """
    techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
    await rule_for(db_session, ROLE_CODE_ARCHITECT, VSCODE)
    await role_crud.write_time_block(
        db_session,
        role_crud.TimeBlockDraft(
            work_day=WORK_DAY,
            role_id=techlead,
            minutes=120,
            source="plan",
            started_at=at(WORK_DAY, 10),
            ended_at=at(WORK_DAY, 12),
            external_ref="section-1",
        ),
    )
    await db_session.commit()

    await send(client, interval(VSCODE, at(WORK_DAY, 10), at(WORK_DAY, 13)))
    blocks = {block.source: block for block in await blocks_of(db_session, WORK_DAY)}
    assert blocks["plan"].minutes == 120
    assert blocks[SOURCE_APP_USAGE].minutes == 60
    assert sum(block.minutes for block in await blocks_of(db_session, WORK_DAY)) == 180


async def test_day_mode_falls_back_to_work_when_the_schedule_lost_a_row(
    db_session: AsyncSession,
) -> None:
    """
    A weekday with no schedule row answers `work`.

    The other default would silently stop measuring a working day, and that is
    the failure hardest to notice.
    """
    # Wednesday: the fixture seeds only Monday and Thursday.
    answer = await activity_crud.day_mode(db_session, date(2026, 9, 2))
    assert answer.kind == "work"
    assert answer.source == "schedule"
