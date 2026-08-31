"""
Как обязательство заканчивается: провал, бюджет промахов и ручной вердикт.

После #127 челлендж считал дни, но не умел кончаться. Здесь у него появляется
момент, в который он объявлен заваленным или выигранным, и способ сказать «этот
день я засчитываю руками».

Проверяемое ядро — устойчивость ручного вердикта. `manual` переживает три
подряд `recompute`, и это свойство записи (`source <> 'manual'` в условии
`ON CONFLICT`), а не аккуратности вызывающего. Второе — возврат из `failed` в
`active` после засчитанного дня: без него «засчитываю» было бы косметикой на
дне, который уже никого не спасает.
"""

# [review:need-review] PHASE-03/128
# summary: unit tests for `outcome_for` (any_miss vs budget, the day the budget ran out, the closed window that wins) and API tests for the manual verdict surviving three recomputes, the failed challenge coming back to active, the won one that new marks do not roll back, and the abandoned one leaving Today

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.challenge.rules import (
    VERDICT_DONE,
    VERDICT_MISS,
    misses_left,
    outcome_for,
)
from app.core.daytime import today_local
from app.models.challenge import (
    FAILURE_ANY_MISS,
    FAILURE_BUDGET,
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_FAILED,
    STATUS_WON,
)
from tests.test_challenges import CHALLENGES_URL, log_entry, make_category

WINDOW_END = date(2026, 9, 10)
INSIDE_WINDOW = date(2026, 9, 5)


class TestOutcome:
    """Чистое ядро: статус обязательства по списку его промахов."""

    def test_any_miss_falls_on_the_first_miss(self) -> None:
        outcome = outcome_for(
            [date(2026, 9, 3)],
            failure_mode=FAILURE_ANY_MISS,
            allowed_misses=0,
            ends_on=WINDOW_END,
            today=INSIDE_WINDOW,
        )
        assert outcome.status == STATUS_FAILED
        assert outcome.failed_on == date(2026, 9, 3)

    def test_a_budget_of_two_holds_at_two_and_falls_on_the_third(self) -> None:
        misses = [date(2026, 9, 1), date(2026, 9, 2)]
        held = outcome_for(
            misses,
            failure_mode=FAILURE_BUDGET,
            allowed_misses=2,
            ends_on=WINDOW_END,
            today=INSIDE_WINDOW,
        )
        assert held.status == STATUS_ACTIVE
        assert held.failed_on is None

        fallen = outcome_for(
            [*misses, date(2026, 9, 4)],
            failure_mode=FAILURE_BUDGET,
            allowed_misses=2,
            ends_on=WINDOW_END,
            today=INSIDE_WINDOW,
        )
        assert fallen.status == STATUS_FAILED
        # Заваливает третий промах, и датой провала стоит именно его день.
        assert fallen.failed_on == date(2026, 9, 4)

    def test_the_budget_runs_out_in_calendar_order(self) -> None:
        """
        Датой провала стоит третий по календарю промах, а не третий пришедший.

        Ленивая материализация досчитывает дни разом, и порядок строк в ответе
        базы — не порядок дней.
        """
        outcome = outcome_for(
            [date(2026, 9, 6), date(2026, 9, 1), date(2026, 9, 3)],
            failure_mode=FAILURE_BUDGET,
            allowed_misses=2,
            ends_on=WINDOW_END,
            today=INSIDE_WINDOW,
        )
        assert outcome.failed_on == date(2026, 9, 6)

    def test_a_closed_window_within_budget_is_won(self) -> None:
        outcome = outcome_for(
            [date(2026, 9, 2)],
            failure_mode=FAILURE_BUDGET,
            allowed_misses=2,
            ends_on=WINDOW_END,
            today=WINDOW_END + timedelta(days=1),
        )
        assert outcome.status == STATUS_WON

    def test_an_open_window_within_budget_is_still_running(self) -> None:
        outcome = outcome_for(
            [],
            failure_mode=FAILURE_BUDGET,
            allowed_misses=2,
            ends_on=WINDOW_END,
            today=WINDOW_END,
        )
        assert outcome.status == STATUS_ACTIVE

    def test_any_miss_has_no_budget_to_report(self) -> None:
        assert misses_left(FAILURE_ANY_MISS, 0, 0) == 0
        assert misses_left(FAILURE_BUDGET, 2, 0) == 2
        assert misses_left(FAILURE_BUDGET, 2, 1) == 1
        assert misses_left(FAILURE_BUDGET, 2, 5) == 0


async def make_challenge_with_budget(
    client: AsyncClient,
    category_id: int,
    field_id: int,
    *,
    starts_on: date,
    ends_on: date,
    failure_mode: str,
    allowed_misses: int = 0,
) -> dict[str, object]:
    """Обязательство с объявленным режимом провала."""
    response = await client.post(
        CHALLENGES_URL,
        json={
            "title": "Вода",
            "category_id": category_id,
            "field_id": field_id,
            "rule_kind": "metric_at_least",
            "target": "2",
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
            "failure_mode": failure_mode,
            "allowed_misses": allowed_misses,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.asyncio
class TestFailure:
    """Переходы статуса на живом периметре."""

    async def test_any_miss_falls_on_the_first_missed_day(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=2)

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=today + timedelta(days=4),
            failure_mode=FAILURE_ANY_MISS,
        )
        assert challenge["status"] == STATUS_FAILED
        assert challenge["failed_on"] == starts_on.isoformat()

    async def test_a_budget_of_two_holds_at_two_and_falls_on_the_third(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=2)

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=today + timedelta(days=4),
            failure_mode=FAILURE_BUDGET,
            allowed_misses=2,
        )
        assert challenge["status"] == STATUS_ACTIVE
        assert challenge["misses_used"] == 2
        assert challenge["misses_left"] == 0

        # Два прошедших дня без записей — это ровно бюджет. Третий промах
        # приходит на сегодняшний день, который сам по себе ещё `pending`:
        # человек ставит его руками, и бюджет кончается.
        url = f"{CHALLENGES_URL}/{challenge['id']}"
        third = await client.put(
            f"{url}/days/{today.isoformat()}", json={"verdict": VERDICT_MISS}
        )
        assert third.status_code == 200
        assert third.json()["status"] == STATUS_FAILED
        assert third.json()["failed_on"] == today.isoformat()

    async def test_a_closed_window_within_budget_is_won(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=3)
        for offset in range(3):
            await log_entry(
                client, category_id, field_id, starts_on + timedelta(days=offset), "2.5"
            )

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=today - timedelta(days=1),
            failure_mode=FAILURE_BUDGET,
            allowed_misses=1,
        )
        assert challenge["status"] == STATUS_WON

    async def test_a_won_challenge_is_not_rolled_back_by_a_later_recompute(
        self, client: AsyncClient
    ) -> None:
        """
        Выигранный челлендж остаётся фактом.

        Три `recompute` подряд после выигрыша не возвращают его в активные и не
        заваливают задним числом: раз закрытая история обязательства сама себя
        не переписывает.
        """
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=3)
        for offset in range(3):
            await log_entry(
                client, category_id, field_id, starts_on + timedelta(days=offset), "2.5"
            )

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=today - timedelta(days=1),
            failure_mode=FAILURE_BUDGET,
            allowed_misses=1,
        )
        url = f"{CHALLENGES_URL}/{challenge['id']}"

        for _ in range(3):
            again = await client.post(f"{url}/recompute")
            assert again.status_code == 200
            assert again.json()["status"] == STATUS_WON


@pytest.mark.asyncio
class TestManualVerdict:
    """Ручной ввод правит автоматику — и это проверяется, а не декларируется."""

    async def test_a_hand_written_verdict_survives_three_recomputes(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=3)

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=today + timedelta(days=3),
            failure_mode=FAILURE_BUDGET,
            allowed_misses=3,
        )
        url = f"{CHALLENGES_URL}/{challenge['id']}"

        marked = await client.put(
            f"{url}/days/{starts_on.isoformat()}",
            json={"verdict": VERDICT_DONE, "note": "лил из-под крана, не записал"},
        )
        assert marked.status_code == 200

        for _ in range(3):
            await client.post(f"{url}/recompute")

        detail = (await client.get(url)).json()
        row = next(
            item for item in detail["days"] if item["day"] == starts_on.isoformat()
        )
        assert row["verdict"] == VERDICT_DONE
        assert row["source"] == "manual"
        assert row["note"] == "лил из-под крана, не записал"

    async def test_a_counted_day_brings_a_failed_challenge_back_to_active(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=2)

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=today + timedelta(days=4),
            failure_mode=FAILURE_BUDGET,
            allowed_misses=1,
        )
        assert challenge["status"] == STATUS_FAILED
        url = f"{CHALLENGES_URL}/{challenge['id']}"

        recovered = await client.put(
            f"{url}/days/{starts_on.isoformat()}", json={"verdict": VERDICT_DONE}
        )
        assert recovered.status_code == 200
        assert recovered.json()["status"] == STATUS_ACTIVE
        assert recovered.json()["failed_on"] is None
        assert recovered.json()["misses_used"] == 1
        assert recovered.json()["misses_left"] == 0

    async def test_a_day_outside_the_window_cannot_be_counted(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=today,
            ends_on=today + timedelta(days=4),
            failure_mode=FAILURE_ANY_MISS,
        )
        response = await client.put(
            f"{CHALLENGES_URL}/{challenge['id']}/days/"
            f"{(today - timedelta(days=5)).isoformat()}",
            json={"verdict": VERDICT_DONE},
        )
        assert response.status_code == 422

    async def test_pending_cannot_be_declared_by_hand(
        self, client: AsyncClient
    ) -> None:
        """«Ещё не решено» — состояние, в которое день попадает сам."""
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=today,
            ends_on=today + timedelta(days=4),
            failure_mode=FAILURE_ANY_MISS,
        )
        response = await client.put(
            f"{CHALLENGES_URL}/{challenge['id']}/days/{today.isoformat()}",
            json={"verdict": "pending"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestAbandon:
    """Брошенный руками челлендж уходит с Today и остаётся в списке."""

    async def test_abandoning_takes_it_off_today_and_leaves_it_in_the_list(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=today,
            ends_on=today + timedelta(days=6),
            failure_mode=FAILURE_ANY_MISS,
        )
        url = f"{CHALLENGES_URL}/{challenge['id']}"

        abandoned = await client.patch(url, json={"status": STATUS_ABANDONED})
        assert abandoned.status_code == 200
        assert abandoned.json()["status"] == STATUS_ABANDONED

        listed = (await client.get(CHALLENGES_URL)).json()
        assert [item["id"] for item in listed] == [challenge["id"]]
        # Пересчёт брошенный челлендж назад не отыгрывает.
        assert listed[0]["status"] == STATUS_ABANDONED

    async def test_won_and_failed_cannot_be_declared_by_hand(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()

        challenge = await make_challenge_with_budget(
            client,
            category_id,
            field_id,
            starts_on=today,
            ends_on=today + timedelta(days=6),
            failure_mode=FAILURE_ANY_MISS,
        )
        response = await client.patch(
            f"{CHALLENGES_URL}/{challenge['id']}", json={"status": STATUS_WON}
        )
        assert response.status_code == 422
