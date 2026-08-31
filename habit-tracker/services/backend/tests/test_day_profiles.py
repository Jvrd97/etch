# [review:need-review] PHASE-03/179
# summary: tests of the breathing ceiling — an unconfirmed activation decides nothing, overlapping confirmed ones are settled by the later start, an expired one returns the ceiling to the default with nobody switching it off, the proposal names the task and its due date and never repeats a refused one, and a day of eleven hours is won under `deadline` and lost the Saturday after

"""
Tests of `app.day.profiles` and of the endpoints over it.

The pure resolution is checked with literals, because «активация без
подтверждения не действует ни на один день» has to be a property of the function
rather than of the order somebody calls things in.
"""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import day_profile as profile_crud
from app.day.profiles import (
    Activation,
    DeadlineSignal,
    Profile,
    propose_profile,
    resolve_profile,
)

DAY_URL = "/api/v1/day"
RULES_URL = f"{DAY_URL}/rules"

BASELINE = Profile(
    id=1,
    code="baseline",
    title="Обычная",
    work_cap_min=480,
    work_hard_cap_min=540,
    is_default=True,
)
DEADLINE = Profile(
    id=2, code="deadline", title="Сдача", work_cap_min=720, work_hard_cap_min=720
)
RECOVERY = Profile(
    id=3, code="recovery", title="После", work_cap_min=360, work_hard_cap_min=420
)
PROFILES = [BASELINE, DEADLINE, RECOVERY]

MONDAY = date(2026, 8, 31)
FRIDAY = MONDAY + timedelta(days=4)
SATURDAY = MONDAY + timedelta(days=5)


@pytest.fixture(autouse=True)
async def seeded(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The day canon and the three profiles; `create_all` seeds neither."""
    await day_crud.seed_rules(db_session)
    await profile_crud.seed_profiles(db_session)
    await db_session.commit()
    yield


def activation(
    profile_id: int,
    valid_from: date,
    valid_to: date,
    *,
    confirmed: bool = True,
    id_: int = 1,
) -> Activation:
    return Activation(
        id=id_,
        profile_id=profile_id,
        valid_from=valid_from,
        valid_to=valid_to,
        confirmed=confirmed,
    )


# --- какой потолок действует ------------------------------------------------


class TestResolve:
    def test_no_activation_means_the_default(self) -> None:
        assert resolve_profile(PROFILES, [], MONDAY) is BASELINE

    def test_a_confirmed_activation_moves_the_ceiling(self) -> None:
        rows = [activation(DEADLINE.id, MONDAY, FRIDAY)]
        assert resolve_profile(PROFILES, rows, MONDAY) is DEADLINE

    def test_an_unconfirmed_activation_decides_nothing(self) -> None:
        """
        Решение человека 2026-08-30, выраженное фильтром, а не дисциплиной.

        Никакой порядок вызовов не может дать предложению сдвинуть потолок,
        потому что резолвер на неподтверждённую строку не смотрит вовсе.
        """
        rows = [activation(DEADLINE.id, MONDAY, FRIDAY, confirmed=False)]
        assert resolve_profile(PROFILES, rows, MONDAY) is BASELINE

    def test_an_expired_activation_is_simply_gone(self) -> None:
        """Срок кончается сам: в субботу потолок базовый, ничего не выключали."""
        rows = [activation(DEADLINE.id, MONDAY, FRIDAY)]
        assert resolve_profile(PROFILES, rows, SATURDAY) is BASELINE

    def test_the_later_activation_wins_an_overlap(self) -> None:
        """
        Неделя восстановления, объявленная внутри недели сдачи, выигрывает.

        «Старшая выигрывает» означала бы, что поправка, сделанная сегодня, не
        может подействовать, пока не истечёт прежняя.
        """
        rows = [
            activation(DEADLINE.id, MONDAY, SATURDAY, id_=1),
            activation(RECOVERY.id, FRIDAY, SATURDAY, id_=2),
        ]
        assert resolve_profile(PROFILES, rows, SATURDAY) is RECOVERY

    def test_a_directory_with_no_default_keeps_the_rules_own_ceiling(self) -> None:
        """
        Фича, которую не настроили, не меняет того, как день судился.

        База до `#179` профилей не знает; `None` здесь означает «суди строкой
        правила», а не «потолка нет».
        """
        assert resolve_profile([DEADLINE], [], MONDAY) is None


# --- предложение ------------------------------------------------------------


class TestProposal:
    def test_a_near_deadline_and_a_long_week_make_one(self) -> None:
        proposal = propose_profile(
            signals=[
                DeadlineSignal("CU-1", "Payment-сервис", MONDAY + timedelta(days=2))
            ],
            long_days=3,
            today=MONDAY,
            declined_signal_ids=frozenset(),
            active=False,
        )
        assert proposal is not None
        assert proposal.profile_code == "deadline"
        assert "Payment-сервис" in proposal.reason
        assert (MONDAY + timedelta(days=2)).isoformat() in proposal.reason

    def test_a_deadline_without_a_long_week_proposes_nothing(self) -> None:
        """
        Подъём для недели, которая на самом деле не длинная, — подъём ни за что,
        и он приучает нажимать «принять».
        """
        assert (
            propose_profile(
                signals=[DeadlineSignal("CU-1", "Payment", MONDAY)],
                long_days=1,
                today=MONDAY,
                declined_signal_ids=frozenset(),
                active=False,
            )
            is None
        )

    def test_a_far_deadline_proposes_nothing(self) -> None:
        assert (
            propose_profile(
                signals=[
                    DeadlineSignal("CU-1", "Payment", MONDAY + timedelta(days=30))
                ],
                long_days=5,
                today=MONDAY,
                declined_signal_ids=frozenset(),
                active=False,
            )
            is None
        )

    def test_a_refused_reason_is_not_proposed_again(self) -> None:
        """«Предложение, от которого отказались, не показывается снова»."""
        signals = [DeadlineSignal("CU-1", "Payment", MONDAY + timedelta(days=1))]
        assert (
            propose_profile(
                signals=signals,
                long_days=3,
                today=MONDAY,
                declined_signal_ids=frozenset({"CU-1"}),
                active=False,
            )
            is None
        )

    def test_nothing_is_proposed_while_a_raise_is_already_on(self) -> None:
        """Второй потолок поверх принятого — это как двенадцать часов станут четырнадцатью."""
        assert (
            propose_profile(
                signals=[DeadlineSignal("CU-1", "Payment", MONDAY)],
                long_days=5,
                today=MONDAY,
                declined_signal_ids=frozenset(),
                active=True,
            )
            is None
        )


# --- ручки ------------------------------------------------------------------


class TestApi:
    async def test_the_three_profiles_are_there_with_the_default_first(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(f"{RULES_URL}/profiles")
        assert response.status_code == 200, response.text
        rows = response.json()
        assert rows[0]["code"] == "baseline"
        assert rows[0]["is_default"] is True
        assert {row["code"] for row in rows} == {"baseline", "deadline", "recovery"}

    async def test_an_activation_needs_an_end_and_a_reason(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            f"{RULES_URL}/activations",
            json={"profile_code": "deadline", "valid_from": MONDAY.isoformat()},
        )
        assert response.status_code == 422

    async def test_confirming_an_activation_moves_the_ceiling_of_the_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            f"{RULES_URL}/activations",
            json={
                "profile_code": "deadline",
                "valid_from": MONDAY.isoformat(),
                "valid_to": FRIDAY.isoformat(),
                "reason": "сдача Payment-сервиса",
            },
        )
        assert response.status_code == 201, response.text

        in_force = await profile_crud.profile_for(db_session, MONDAY)
        assert in_force.profile.code == "deadline"
        assert in_force.valid_to == FRIDAY

        after = await profile_crud.profile_for(db_session, SATURDAY)
        assert after.profile.code == "baseline"
        assert after.valid_to is None

    async def test_declining_takes_the_raise_back_and_remembers_why(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        created = await client.post(
            f"{RULES_URL}/activations",
            json={
                "profile_code": "deadline",
                "valid_from": MONDAY.isoformat(),
                "valid_to": FRIDAY.isoformat(),
                "reason": "сдача",
                "source_signal_id": "CU-1",
            },
        )
        activation_id = created.json()["id"]

        dropped = await client.delete(f"{RULES_URL}/activations/{activation_id}")
        assert dropped.status_code == 200, dropped.text
        assert dropped.json()["confirmed_at"] is None
        assert dropped.json()["declined_at"] is not None

        assert (await profile_crud.profile_for(db_session, MONDAY)).profile.code == (
            "baseline"
        )
        assert await profile_crud.declined_signal_ids(db_session) == frozenset({"CU-1"})

    async def test_an_unknown_profile_code_is_a_422(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{RULES_URL}/activations",
            json={
                "profile_code": "vacation",
                "valid_from": MONDAY.isoformat(),
                "valid_to": FRIDAY.isoformat(),
                "reason": "нет такого",
            },
        )
        assert response.status_code == 422

    async def test_the_proposal_is_empty_while_nothing_names_a_deadline(
        self, client: AsyncClient
    ) -> None:
        """
        Источник дедлайнов — `#103`, и его ещё нет.

        Пусто — правильный ответ, а не деградация: предлагать нечего, пока
        никто не сказал про срок.
        """
        response = await client.get(f"{RULES_URL}/proposal")
        assert response.status_code == 200
        assert response.json() is None

    async def test_a_profile_can_be_edited_by_code(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            f"{RULES_URL}/profiles",
            json={
                "code": "deadline",
                "title": "Неделя сдачи",
                "work_cap_min": 660,
                "work_hard_cap_min": 660,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["work_cap_min"] == 660

        stored = await profile_crud.get_profile_by_code(db_session, "deadline")
        assert stored is not None
        assert stored.work_cap_min == 660


# --- день судится профилем своей даты ---------------------------------------


async def test_the_day_answer_names_the_profile_it_is_judged_by(
    client: AsyncClient,
) -> None:
    """Иначе «день выигран при одиннадцати часах» выглядит как сломанное правило."""
    today = today_local()
    await client.post(
        f"{RULES_URL}/activations",
        json={
            "profile_code": "deadline",
            "valid_from": today.isoformat(),
            "valid_to": (today + timedelta(days=2)).isoformat(),
            "reason": "сдача",
        },
    )
    response = await client.get(f"{DAY_URL}/{today.isoformat()}")
    assert response.status_code == 200, response.text
    profile: dict[str, Any] = response.json()["profile"]
    assert profile["code"] == "deadline"
    assert profile["work_cap_min"] == 720
    assert profile["valid_to"] == (today + timedelta(days=2)).isoformat()
