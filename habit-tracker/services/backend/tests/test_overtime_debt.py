# [review:need-review] PHASE-03/179
# summary: tests of the price of a raised ceiling — the debt is counted from the baseline and not from the profile in force, the oldest open one is repaid and only by a day that actually leaves room for the whole of it, a day with `work_minutes IS NULL` neither accrues nor repays, a day of eleven hours is won under `deadline` and lost the Saturday after, and a week of won days carrying an unpaid debt is not a won week

"""
Tests of `app.day.debt` and of the ledger over it.

The sentence the ticket turns on is «долг считается от базового потолка, а не от
поднятого». Measured against the profile in force, every debt would be zero and
the mechanism would be decoration on top of an abolished rule — so the first
tests here are exactly that comparison.
"""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import day_profile as profile_crud
from app.day.debt import Debt, accrue, repay, week_is_won

DAY_URL = "/api/v1/day"
RULES_URL = f"{DAY_URL}/rules"

BASELINE_CAP = 480
DEADLINE_CAP = 720

MONDAY = date(2026, 8, 31)
TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = MONDAY + timedelta(days=2)


@pytest.fixture(autouse=True)
async def seeded(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The day canon and the three profiles."""
    await day_crud.seed_rules(db_session)
    await profile_crud.seed_profiles(db_session)
    await db_session.commit()
    yield


# --- чистая арифметика ------------------------------------------------------


class TestAccrue:
    def test_a_day_over_the_baseline_owes_the_difference(self) -> None:
        """Одиннадцать часов при базовом потолке восемь — три часа долга."""
        assert accrue(660, BASELINE_CAP) == 180

    def test_the_debt_is_counted_from_the_baseline_and_not_from_the_raise(
        self,
    ) -> None:
        """
        Ровно то предложение, на котором держится весь тикет.

        При поднятом потолке 720 день на 660 минут — выигранный. Долг он всё
        равно должен: измеряй мы превышение от поднятого потолка, долг был бы
        всегда нулём.
        """
        assert accrue(660, DEADLINE_CAP) == 0
        assert accrue(660, BASELINE_CAP) == 180

    def test_a_short_day_owes_nothing(self) -> None:
        assert accrue(400, BASELINE_CAP) == 0

    def test_an_unmeasured_day_owes_nothing(self) -> None:
        """«Не измерено» — не ноль, и придумать ему ноль значило бы соврать."""
        assert accrue(None, BASELINE_CAP) == 0


class TestRepay:
    def test_the_oldest_open_debt_is_the_one_repaid(self) -> None:
        """
        Иначе старый долг вечно стоит за потоком новых, а «висит дольше недели»
        — то самое, чего экран недели не должен дать пропустить.
        """
        debts = [
            Debt(incurred_on=TUESDAY, minutes_over=30),
            Debt(incurred_on=MONDAY, minutes_over=30),
        ]
        chosen = repay(debts, 400, BASELINE_CAP)
        assert chosen is not None
        assert chosen.incurred_on == MONDAY

    def test_a_day_that_does_not_leave_room_repays_nothing(self) -> None:
        """
        Долг в час гасится днём на семь часов при потолке восемь, а не днём на
        семь пятьдесят: частичный возврат позволил бы вернуть час по пять минут
        за две недели.
        """
        debts = [Debt(incurred_on=MONDAY, minutes_over=60)]
        assert repay(debts, 470, BASELINE_CAP) is None
        assert repay(debts, 420, BASELINE_CAP) is not None

    def test_an_unmeasured_day_repays_nothing(self) -> None:
        debts = [Debt(incurred_on=MONDAY, minutes_over=60)]
        assert repay(debts, None, BASELINE_CAP) is None

    def test_a_repaid_debt_is_not_repaid_again(self) -> None:
        debts = [Debt(incurred_on=MONDAY, minutes_over=60, repaid_on=TUESDAY)]
        assert repay(debts, 300, BASELINE_CAP) is None


class TestWeek:
    def test_a_week_of_won_days_with_a_debt_is_not_won(self) -> None:
        """Гибкость покупается возвратом, а не выдаётся."""
        assert week_is_won(won_days=7, total_days=7, open_debt_minutes=60) is False

    def test_a_week_of_won_days_with_nothing_owed_is_won(self) -> None:
        assert week_is_won(won_days=7, total_days=7, open_debt_minutes=0) is True

    def test_a_week_with_a_lost_day_is_not_won(self) -> None:
        assert week_is_won(won_days=6, total_days=7, open_debt_minutes=0) is False

    def test_an_empty_week_is_not_won(self) -> None:
        assert week_is_won(won_days=0, total_days=0, open_debt_minutes=0) is False


# --- гроссбух ---------------------------------------------------------------


async def close_day(
    client: AsyncClient, on: date, work_minutes: int | None
) -> dict[str, Any]:
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/close",
        json={"work_minutes": work_minutes, "body_md": "итог"},
    )
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


async def debts(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{DAY_URL}/debt")
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestLedger:
    async def test_a_long_day_creates_a_debt_visible_with_its_date(
        self, client: AsyncClient
    ) -> None:
        await close_day(client, MONDAY, 660)
        ledger = await debts(client)
        assert ledger["open_minutes"] == 180
        assert ledger["debts"][0]["incurred_on"] == MONDAY.isoformat()
        assert ledger["debts"][0]["is_open"] is True

    async def test_a_short_day_repays_the_oldest_debt(
        self, client: AsyncClient
    ) -> None:
        await close_day(client, MONDAY, 540)
        assert (await debts(client))["open_minutes"] == 60

        await close_day(client, TUESDAY, 400)
        ledger = await debts(client)
        assert ledger["open_minutes"] == 0
        repaid = next(
            row for row in ledger["debts"] if row["incurred_on"] == MONDAY.isoformat()
        )
        assert repaid["repaid_on"] == TUESDAY.isoformat()
        assert repaid["repaid_by_day"] == TUESDAY.isoformat()

    async def test_an_unmeasured_day_neither_owes_nor_repays(
        self, client: AsyncClient
    ) -> None:
        await close_day(client, MONDAY, 540)
        await close_day(client, TUESDAY, None)
        ledger = await debts(client)
        assert ledger["open_minutes"] == 60
        assert [row["incurred_on"] for row in ledger["debts"]] == [MONDAY.isoformat()]

    async def test_closing_the_same_day_twice_does_not_owe_twice(
        self, client: AsyncClient
    ) -> None:
        """Закрытие бывает в два касания (`#143`); гроссбух не растёт от этого."""
        await close_day(client, MONDAY, 540)
        await close_day(client, MONDAY, 540)
        ledger = await debts(client)
        assert ledger["open_minutes"] == 60
        assert len(ledger["debts"]) == 1

    async def test_the_debt_counts_from_the_baseline_under_a_raised_ceiling(
        self, client: AsyncClient
    ) -> None:
        """
        The acceptance case, end to end.

        Under `deadline` a day of eleven hours is **won** and still owes three
        hours: the raise is bought, not given.
        """
        await client.post(
            f"{RULES_URL}/activations",
            json={
                "profile_code": "deadline",
                "valid_from": MONDAY.isoformat(),
                "valid_to": WEDNESDAY.isoformat(),
                "reason": "сдача Payment-сервиса",
            },
        )
        answer = await close_day(client, MONDAY, 660)
        assert answer["verdict"] == "won"

        ledger = await debts(client)
        assert ledger["open_minutes"] == 180


async def test_the_same_day_is_lost_once_the_raise_has_expired(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    В субботу тот же день на одиннадцать часов проигран, и руками ничего не
    выключали — активация кончилась сама.
    """
    await client.post(
        f"{RULES_URL}/activations",
        json={
            "profile_code": "deadline",
            "valid_from": MONDAY.isoformat(),
            "valid_to": MONDAY.isoformat(),
            "reason": "сдача",
        },
    )
    won = await close_day(client, MONDAY, 660)
    assert won["verdict"] == "won"

    lost = await close_day(client, TUESDAY, 660)
    assert lost["verdict"] == "lost"
    assert lost["verdict_reason"] == "overtime"
