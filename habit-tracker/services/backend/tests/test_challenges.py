"""
Обязательство от создания до вердикта на каждый день.

Здесь проверяется ровно то, чем челлендж отличается от стрика и от цели-поля у
категории. Прошедший день без единой записи — промах, а не «нет данных»:
неподтверждённый день обязательства не сделан. Сегодняшний день промахом не
бывает, пока локальные сутки не закрылись, и границу суток называет
`local_date()`, а не полночь UTC. Правка цели активного челленджа не переписывает
ни одного прошлого вердикта. И два `recompute` подряд оставляют то же число
строк — потому что материализация идёт upsert'ом по `(challenge_id, day)`.
"""

# [review:need-review] PHASE-03/127
# summary: unit tests for the pure verdict of a day (four rule kinds, an empty day, an open day) and API tests for creation, lazy materialization up to today, the edited target that leaves history alone, идемпотентность recompute, окно назад и длиннее 92 дней, и отсутствие заголовка в логах

import logging
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.challenge.rules import (
    MAX_CHALLENGE_DAYS,
    RULE_ABSTAIN,
    RULE_CHECKED,
    RULE_METRIC_AT_LEAST,
    RULE_METRIC_AT_MOST,
    VERDICT_DONE,
    VERDICT_MISS,
    VERDICT_PENDING,
    ChallengeRule,
    DaySample,
    verdict_for_day,
)
from app.core import daytime
from app.core.daytime import DayBoundary, today_local
from app.models.field import FieldType

CHALLENGES_URL = "/api/v1/challenges"

WATER_RULE = ChallengeRule(kind=RULE_METRIC_AT_LEAST, target=Decimal("2"))


def sample(*values: str) -> DaySample:
    """День, в который что-то записали."""
    return DaySample(has_entry=True, values=values)


EMPTY = DaySample(has_entry=False, values=())


class TestVerdictOfOneDay:
    """
    Чистое ядро: вердикт одного дня по тому, что о нём записано.

    Без базы — потому что интересны здесь не запросы, а четыре вида правила и
    два края: день, про который ничего не известно, и день, который ещё идёт.
    """

    def test_a_closed_day_with_nothing_recorded_is_a_miss(self) -> None:
        assert (
            verdict_for_day(WATER_RULE, FieldType.NUMBER, EMPTY, is_closed=True)
            == VERDICT_MISS
        )

    def test_the_running_day_waits_rather_than_misses(self) -> None:
        assert (
            verdict_for_day(WATER_RULE, FieldType.NUMBER, EMPTY, is_closed=False)
            == VERDICT_PENDING
        )

    def test_the_running_day_is_done_as_soon_as_the_promise_is_kept(self) -> None:
        assert (
            verdict_for_day(
                WATER_RULE, FieldType.NUMBER, sample("2.5"), is_closed=False
            )
            == VERDICT_DONE
        )

    def test_two_glasses_add_up_to_the_promise(self) -> None:
        assert (
            verdict_for_day(
                WATER_RULE, FieldType.NUMBER, sample("1.2", "0.5"), is_closed=True
            )
            == VERDICT_MISS
        )
        assert (
            verdict_for_day(
                WATER_RULE, FieldType.NUMBER, sample("1.2", "1.1"), is_closed=True
            )
            == VERDICT_DONE
        )

    def test_at_most_keeps_the_day_below_the_line_and_misses_the_one_above(
        self,
    ) -> None:
        rule = ChallengeRule(kind=RULE_METRIC_AT_MOST, target=Decimal("500"))
        assert (
            verdict_for_day(rule, FieldType.NUMBER, sample("300"), is_closed=True)
            == VERDICT_DONE
        )
        assert (
            verdict_for_day(
                rule, FieldType.NUMBER, sample("300", "400"), is_closed=True
            )
            == VERDICT_MISS
        )

    def test_at_most_still_needs_the_day_to_be_recorded(self) -> None:
        """
        Пустой день не «уложился в лимит».

        Иначе «≤ 500 ккал сахара 30 дней» выполнялся бы тем, что человек ни разу
        не открыл трекер, — а это ровно та подмена, из-за которой у обязательства
        своя материализация, а не `compute_streak`.
        """
        rule = ChallengeRule(kind=RULE_METRIC_AT_MOST, target=Decimal("500"))
        assert (
            verdict_for_day(rule, FieldType.NUMBER, EMPTY, is_closed=True)
            == VERDICT_MISS
        )

    def test_checked_wants_the_box_ticked(self) -> None:
        rule = ChallengeRule(kind=RULE_CHECKED, target=None)
        assert (
            verdict_for_day(rule, FieldType.BOOLEAN, sample("true"), is_closed=True)
            == VERDICT_DONE
        )
        assert (
            verdict_for_day(rule, FieldType.BOOLEAN, sample("false"), is_closed=True)
            == VERDICT_MISS
        )

    def test_abstain_calls_a_relapse_exactly_what_the_streak_calls_one(self) -> None:
        """
        Один предикат на двух потребителей.

        `is_relapse_value` считает срывом булеву истину и число больше нуля;
        ноль и пустое значение оставляют день чистым. Здесь проверяется, что
        `abstain` не завёл своего мнения на этот счёт.
        """
        rule = ChallengeRule(kind=RULE_ABSTAIN, target=None)
        assert (
            verdict_for_day(rule, FieldType.NUMBER, sample("0"), is_closed=True)
            == VERDICT_DONE
        )
        assert (
            verdict_for_day(rule, FieldType.NUMBER, sample("1"), is_closed=True)
            == VERDICT_MISS
        )
        assert (
            verdict_for_day(rule, FieldType.BOOLEAN, sample("true"), is_closed=True)
            == VERDICT_MISS
        )


async def make_category(
    client: AsyncClient, name: str, field_type: str = "number"
) -> tuple[int, int]:
    """Категория с одним полем — то, на что указывает правило челленджа."""
    created = await client.post("/api/v1/categories", json={"name": name})
    assert created.status_code == 201
    category_id = int(created.json()["id"])

    field = await client.post(
        f"/api/v1/categories/{category_id}/fields",
        json={"name": "amount", "field_type": field_type},
    )
    assert field.status_code == 201, field.text
    return category_id, int(field.json()["id"])


async def log_entry(
    client: AsyncClient, category_id: int, field_id: int, day: date, value: str
) -> None:
    """Одна запись трекера — единственный источник чисел для челленджа."""
    response = await client.post(
        "/api/v1/entries",
        json={
            "category_id": category_id,
            "entry_date": day.isoformat(),
            "values": [{"field_id": field_id, "value": value}],
        },
    )
    assert response.status_code == 201, response.text


async def make_challenge(
    client: AsyncClient,
    category_id: int,
    field_id: int,
    *,
    starts_on: date,
    ends_on: date,
    rule_kind: str = RULE_METRIC_AT_LEAST,
    target: str | None = "2",
    title: str = "Вода",
) -> dict[str, object]:
    """Завести обязательство и вернуть его как его читает карточка."""
    body: dict[str, object] = {
        "title": title,
        "category_id": category_id,
        "field_id": field_id,
        "rule_kind": rule_kind,
        "starts_on": starts_on.isoformat(),
        "ends_on": ends_on.isoformat(),
    }
    if target is not None:
        body["target"] = target
    response = await client.post(CHALLENGES_URL, json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.asyncio
class TestChallengeWindow:
    """Окно, которое база и схема отказываются принимать."""

    async def test_a_window_that_ends_before_it_starts_is_refused(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json={
                "title": "Вода",
                "category_id": category_id,
                "field_id": field_id,
                "rule_kind": RULE_METRIC_AT_LEAST,
                "target": "2",
                "starts_on": today.isoformat(),
                "ends_on": (today - timedelta(days=1)).isoformat(),
            },
        )
        assert response.status_code == 422
        assert "ends_on" in response.text

    async def test_a_window_longer_than_the_ceiling_is_refused(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json={
                "title": "Вода",
                "category_id": category_id,
                "field_id": field_id,
                "rule_kind": RULE_METRIC_AT_LEAST,
                "target": "2",
                "starts_on": today.isoformat(),
                "ends_on": (today + timedelta(days=MAX_CHALLENGE_DAYS)).isoformat(),
            },
        )
        assert response.status_code == 422
        assert str(MAX_CHALLENGE_DAYS) in response.text

    async def test_a_threshold_rule_without_a_threshold_is_refused(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json={
                "title": "Вода",
                "category_id": category_id,
                "field_id": field_id,
                "rule_kind": RULE_METRIC_AT_LEAST,
                "starts_on": today.isoformat(),
                "ends_on": (today + timedelta(days=6)).isoformat(),
            },
        )
        assert response.status_code == 422

    async def test_a_rule_pointing_at_a_field_of_another_category_is_refused(
        self, client: AsyncClient
    ) -> None:
        category_id, _ = await make_category(client, "Вода")
        _, other_field_id = await make_category(client, "Сон")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json={
                "title": "Вода",
                "category_id": category_id,
                "field_id": other_field_id,
                "rule_kind": RULE_METRIC_AT_LEAST,
                "target": "2",
                "starts_on": today.isoformat(),
                "ends_on": (today + timedelta(days=6)).isoformat(),
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestMaterialization:
    """Ленивый пересчёт: что видит карточка и сколько строк остаётся в базе."""

    async def test_three_kept_days_read_as_day_three_of_seven(
        self, client: AsyncClient
    ) -> None:
        """«День 3 из 7, промахов 0» — ровно то, что печатает карточка."""
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=2)

        for offset in range(3):
            await log_entry(
                client, category_id, field_id, starts_on + timedelta(days=offset), "2.5"
            )

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=6),
        )
        assert challenge["day_number"] == 3
        assert challenge["total_days"] == 7
        assert challenge["done_count"] == 3
        assert challenge["misses_used"] == 0

    async def test_a_past_day_with_no_records_is_a_miss_rather_than_no_data(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=3)
        await log_entry(client, category_id, field_id, starts_on, "2.5")

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=6),
        )
        detail = await client.get(f"{CHALLENGES_URL}/{challenge['id']}")
        assert detail.status_code == 200
        by_day = {row["day"]: row["verdict"] for row in detail.json()["days"]}

        assert by_day[starts_on.isoformat()] == VERDICT_DONE
        assert by_day[(starts_on + timedelta(days=1)).isoformat()] == VERDICT_MISS
        assert by_day[(starts_on + timedelta(days=2)).isoformat()] == VERDICT_MISS

    async def test_today_waits_and_is_never_counted_as_a_miss(
        self, client: AsyncClient
    ) -> None:
        """
        Сегодняшний день стоит в `pending`, пока не закрылись локальные сутки.

        День здесь — ответ `local_date()`, а не полночь UTC: в 00:30 карточка
        челленджа и страница дня обязаны показывать одно и то же число.
        """
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=today,
            ends_on=today + timedelta(days=6),
        )
        assert challenge["today_verdict"] == VERDICT_PENDING
        assert challenge["misses_used"] == 0

        detail = await client.get(f"{CHALLENGES_URL}/{challenge['id']}")
        days = detail.json()["days"]
        assert [row["day"] for row in days] == [today.isoformat()]

    async def test_today_flips_to_done_the_moment_the_promise_is_kept(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=today,
            ends_on=today + timedelta(days=6),
        )

        await log_entry(client, category_id, field_id, today, "2.1")
        recomputed = await client.post(f"{CHALLENGES_URL}/{challenge['id']}/recompute")
        assert recomputed.status_code == 200
        assert recomputed.json()["today_verdict"] == VERDICT_DONE

    async def test_two_recomputes_leave_the_same_rows_and_the_same_verdicts(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=4)
        await log_entry(client, category_id, field_id, starts_on, "2.5")

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=6),
        )
        url = f"{CHALLENGES_URL}/{challenge['id']}"

        first = (await client.get(url)).json()["days"]
        await client.post(f"{url}/recompute")
        await client.post(f"{url}/recompute")
        second = (await client.get(url)).json()["days"]

        assert len(first) == len(second) == 5
        assert first == second

    async def test_a_challenge_nobody_opened_for_a_week_catches_up_at_once(
        self, client: AsyncClient
    ) -> None:
        """
        Плата за отсутствие планировщика — досчёт разом при следующем открытии.

        Челлендж заводится задним числом и ни разу не читается, пока окно идёт;
        первое же чтение обязано принести вердикты за все пропущенные дни.
        """
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=7)

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=9),
        )
        detail = await client.get(f"{CHALLENGES_URL}/{challenge['id']}")
        days = detail.json()["days"]

        assert len(days) == 8
        assert [row["verdict"] for row in days[:-1]] == [VERDICT_MISS] * 7
        assert days[-1]["verdict"] == VERDICT_PENDING

    async def test_at_most_counts_the_day_below_the_line_through_the_api(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Сахар")
        today = today_local()
        starts_on = today - timedelta(days=2)
        await log_entry(client, category_id, field_id, starts_on, "300")
        await log_entry(
            client, category_id, field_id, starts_on + timedelta(days=1), "900"
        )

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=6),
            rule_kind=RULE_METRIC_AT_MOST,
            target="500",
            title="Сахар",
        )
        detail = await client.get(f"{CHALLENGES_URL}/{challenge['id']}")
        by_day = {row["day"]: row["verdict"] for row in detail.json()["days"]}

        assert by_day[starts_on.isoformat()] == VERDICT_DONE
        assert by_day[(starts_on + timedelta(days=1)).isoformat()] == VERDICT_MISS

    async def test_editing_the_target_leaves_every_past_verdict_alone(
        self, client: AsyncClient
    ) -> None:
        """
        Новая цель действует вперёд, а не назад.

        Иначе поднятая до трёх литров планка задним числом объявила бы
        несделанной неделю, которая была сделана, — и история обязательства,
        ради которой у него отдельная таблица, перестала бы что-либо значить.
        """
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=3)
        for offset in range(3):
            await log_entry(
                client, category_id, field_id, starts_on + timedelta(days=offset), "2.5"
            )

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=6),
        )
        url = f"{CHALLENGES_URL}/{challenge['id']}"
        before = (await client.get(url)).json()["days"]

        patched = await client.patch(url, json={"target": "9"})
        assert patched.status_code == 200
        assert Decimal(patched.json()["target"]) == Decimal("9")

        after = (await client.get(url)).json()["days"]
        assert [row["verdict"] for row in after] == [row["verdict"] for row in before]

    async def test_the_title_of_a_challenge_never_reaches_the_log(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """В логе — идентификаторы; что человек себе обещал, там не печатается."""
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        secret = "Бросить курить к дню рождения"

        with caplog.at_level(logging.DEBUG):
            challenge = await make_challenge(
                client,
                category_id,
                field_id,
                starts_on=today - timedelta(days=2),
                ends_on=today + timedelta(days=4),
                title=secret,
            )
            await client.post(f"{CHALLENGES_URL}/{challenge['id']}/recompute")

        assert secret not in caplog.text
        assert f"challenge {challenge['id']}" in caplog.text


@pytest.mark.asyncio
class TestOneDayBoundary:
    """
    Челлендж считает дни той же границей суток, что план и вердикт дня.

    Проверяется не «правильная дата», а единственность источника: если сдвинуть
    опубликованную границу, сегодняшний день челленджа обязан уехать вместе с
    ней. Своей полуночи у обязательства нет.
    """

    async def test_the_challenge_follows_the_published_boundary(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")

        moscow = DayBoundary(timezone="Europe/Moscow", day_start_hour=4)
        daytime.use_boundary(moscow)
        moscow_today = today_local()

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=moscow_today - timedelta(days=1),
            ends_on=moscow_today + timedelta(days=5),
        )
        detail = await client.get(f"{CHALLENGES_URL}/{challenge['id']}")
        materialized = [row["day"] for row in detail.json()["days"]]

        # Последний материализованный день — ровно тот, который `local_date()`
        # называет сегодняшним, и никакой другой.
        assert materialized[-1] == moscow_today.isoformat()
        assert detail.json()["days"][-1]["verdict"] == VERDICT_PENDING

    async def test_moving_the_boundary_moves_the_challenge_with_it(
        self, client: AsyncClient
    ) -> None:
        """
        Час границы — часть канона дня, и челлендж ему подчиняется.

        Два часовых пояса по разные стороны линии перемены дат дают разные
        ответы на «какое сегодня число». Челлендж обязан взять оба у
        `local_date()`, а не посчитать свой.
        """
        category_id, field_id = await make_category(client, "Вода")

        daytime.use_boundary(
            DayBoundary(timezone="Pacific/Kiritimati", day_start_hour=4)
        )
        east_today = today_local()
        daytime.use_boundary(DayBoundary(timezone="Pacific/Niue", day_start_hour=4))
        west_today = today_local()

        assert east_today != west_today

        challenge = await make_challenge(
            client,
            category_id,
            field_id,
            starts_on=west_today - timedelta(days=2),
            ends_on=west_today + timedelta(days=4),
        )
        west_days = [
            row["day"]
            for row in (await client.get(f"{CHALLENGES_URL}/{challenge['id']}")).json()[
                "days"
            ]
        ]
        assert west_days[-1] == west_today.isoformat()

        daytime.use_boundary(
            DayBoundary(timezone="Pacific/Kiritimati", day_start_hour=4)
        )
        east_days = [
            row["day"]
            for row in (await client.get(f"{CHALLENGES_URL}/{challenge['id']}")).json()[
                "days"
            ]
        ]
        assert east_days[-1] == east_today.isoformat()
        assert len(east_days) == len(west_days) + 1
