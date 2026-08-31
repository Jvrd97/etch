"""
Челлендж, предложенный моделью, и человек, который его принимает.

Проверяется одно свойство и его края: **модель не может завести человеку
обязательство**. Предложение живёт без единого вердикта, счёт по нему не идёт,
пересчёт его не трогает, руками день ему не засчитать. Обязательством оно
становится ровно одним действием — «принять», — и с этого момента считается с
`starts_on`, включая прожитые дни.

Отдельно проверяется, что заголовок предложения не попадает в логи: человек
называет челлендж диагнозом, и правило PII здесь то же, что у `transcripts`.
"""

# [review:need-review] PHASE-03/129
# summary: API tests for the proposal path — origin='ai' cannot be created active, a proposal materializes no day and is skipped by recompute, accept counts the window from starts_on including past days, decline is abandoned and stays declined, a proposal pointing at a foreign field is refused at parse time, and no title reaches the log

import logging
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.challenge.rules import RULE_METRIC_AT_LEAST
from app.core.daytime import today_local
from app.llm.challenge_proposal import (
    ChallengeProposalError,
    ChallengeProposals,
    parse_proposals,
    validate_proposals,
)
from app.models.category import Category
from app.models.field import Field, FieldType

CHALLENGES_URL = "/api/v1/challenges"

TITLE = "месяц без обезболивающих"


async def make_category(client: AsyncClient, name: str) -> tuple[int, int]:
    """Категория с одним числовым полем — то, на что указывает правило."""
    created = await client.post("/api/v1/categories", json={"name": name})
    assert created.status_code == 201
    category_id = int(created.json()["id"])
    field = await client.post(
        f"/api/v1/categories/{category_id}/fields",
        json={"name": "amount", "field_type": "number"},
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


def proposal_body(
    category_id: int,
    field_id: int,
    *,
    starts_on: date,
    ends_on: date,
    origin: str = "ai",
    status: str | None = None,
    title: str = TITLE,
) -> dict[str, object]:
    """Тело `POST /challenges`, каким его шлёт машинный источник."""
    body: dict[str, object] = {
        "title": title,
        "category_id": category_id,
        "field_id": field_id,
        "rule_kind": RULE_METRIC_AT_LEAST,
        "target": "2",
        "starts_on": starts_on.isoformat(),
        "ends_on": ends_on.isoformat(),
        "origin": origin,
    }
    if status is not None:
        body["status"] = status
    return body


@pytest.mark.asyncio
class TestModelCannotTakeOnAnObligation:
    """Единственное свойство среза: обязательство берёт на себя человек."""

    async def test_a_machine_origin_is_born_proposed(self, client: AsyncClient) -> None:
        category_id, field_id = await make_category(client, "Обезболивающие")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today - timedelta(days=2),
                ends_on=today + timedelta(days=4),
            ),
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "proposed"
        assert response.json()["origin"] == "ai"

    async def test_asking_for_active_with_a_machine_origin_is_refused(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Обезболивающие")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today,
                ends_on=today + timedelta(days=6),
                status="active",
            ),
        )

        assert response.status_code == 422, response.text

    async def test_a_person_still_creates_an_active_challenge(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        response = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today,
                ends_on=today + timedelta(days=6),
                origin="human",
            ),
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "active"
        assert response.json()["origin"] == "human"

    async def test_a_proposal_has_no_verdict_of_any_day(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        await log_entry(client, category_id, field_id, today - timedelta(days=1), "3")
        created = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today - timedelta(days=3),
                ends_on=today + timedelta(days=3),
            ),
        )
        challenge_id = created.json()["id"]

        detail = await client.get(f"{CHALLENGES_URL}/{challenge_id}")

        assert detail.status_code == 200, detail.text
        assert detail.json()["days"] == []
        assert detail.json()["done_count"] == 0
        assert detail.json()["today_verdict"] is None

    async def test_recompute_leaves_a_proposal_alone(self, client: AsyncClient) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        created = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today - timedelta(days=3),
                ends_on=today + timedelta(days=3),
            ),
        )
        challenge_id = created.json()["id"]

        recomputed = await client.post(f"{CHALLENGES_URL}/{challenge_id}/recompute")

        assert recomputed.status_code == 200, recomputed.text
        assert recomputed.json()["status"] == "proposed"
        detail = await client.get(f"{CHALLENGES_URL}/{challenge_id}")
        assert detail.json()["days"] == []

    async def test_a_day_of_a_proposal_cannot_be_counted_by_hand(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        created = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today - timedelta(days=1),
                ends_on=today + timedelta(days=3),
            ),
        )
        challenge_id = created.json()["id"]

        response = await client.put(
            f"{CHALLENGES_URL}/{challenge_id}/days/{today.isoformat()}",
            json={"verdict": "done"},
        )

        assert response.status_code == 422, response.text


@pytest.mark.asyncio
class TestAcceptAndDecline:
    """Два действия человека над предложением, и их последствия."""

    async def test_accepting_counts_the_window_from_its_start(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        starts_on = today - timedelta(days=2)
        # Оба прожитых дня обещание выполнено. Пропуск любого из них завалил бы
        # челлендж в тот же момент, когда его приняли, — режим `any_miss`
        # работает и на прошлом, и это отдельное свойство, не это.
        await log_entry(client, category_id, field_id, starts_on, "3")
        await log_entry(
            client, category_id, field_id, starts_on + timedelta(days=1), "3"
        )
        created = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=starts_on,
                ends_on=today + timedelta(days=4),
            ),
        )
        challenge_id = created.json()["id"]

        accepted = await client.post(f"{CHALLENGES_URL}/{challenge_id}/accept")

        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"
        # Дни считаются от starts_on, а не от согласия: прожитый день, в
        # который обещание было выполнено, засчитан.
        assert accepted.json()["done_count"] == 2
        detail = await client.get(f"{CHALLENGES_URL}/{challenge_id}")
        days = detail.json()["days"]
        assert [row["day"] for row in days][0] == starts_on.isoformat()
        assert len(days) == 3

    async def test_accepting_twice_is_refused(self, client: AsyncClient) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        created = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today,
                ends_on=today + timedelta(days=4),
            ),
        )
        challenge_id = created.json()["id"]
        await client.post(f"{CHALLENGES_URL}/{challenge_id}/accept")

        again = await client.post(f"{CHALLENGES_URL}/{challenge_id}/accept")

        assert again.status_code == 422, again.text

    async def test_accepting_something_that_is_not_there_is_a_404(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(f"{CHALLENGES_URL}/424242/accept")
        assert response.status_code == 404

    async def test_a_declined_proposal_stays_declined(
        self, client: AsyncClient
    ) -> None:
        category_id, field_id = await make_category(client, "Вода")
        today = today_local()
        created = await client.post(
            CHALLENGES_URL,
            json=proposal_body(
                category_id,
                field_id,
                starts_on=today,
                ends_on=today + timedelta(days=4),
            ),
        )
        challenge_id = created.json()["id"]

        declined = await client.patch(
            f"{CHALLENGES_URL}/{challenge_id}", json={"status": "abandoned"}
        )
        assert declined.status_code == 200, declined.text
        assert declined.json()["status"] == "abandoned"

        # Повторный разбор того же дня не воскрешает отклонённое: оно осталось
        # строкой со статусом, а не исчезло, и «принять» ему больше не светит.
        accepted = await client.post(f"{CHALLENGES_URL}/{challenge_id}/accept")
        assert accepted.status_code == 422, accepted.text
        listed = await client.get(CHALLENGES_URL)
        statuses = [row["status"] for row in listed.json()]
        assert statuses.count("proposed") == 0


@pytest.mark.asyncio
class TestParsingTheModelsAnswer:
    """Разбор ответа модели: форма, потом смысл."""

    async def test_a_proposal_pointing_at_a_foreign_field_is_refused(
        self, client: AsyncClient
    ) -> None:
        water_id, water_field = await make_category(client, "Вода")
        _, other_field = await make_category(client, "Сон")
        today = today_local()
        proposals = parse_proposals(
            f'{{"proposals": [{{"title": "{TITLE}", "category_id": {water_id}, '
            f'"field_id": {other_field}, "rule_kind": "metric_at_least", '
            f'"target": 2, "starts_on": "{today.isoformat()}", '
            f'"ends_on": "{(today + timedelta(days=6)).isoformat()}"}}]}}'
        )
        categories = [
            Category(
                id=water_id,
                name="Вода",
                fields=[
                    Field(
                        id=water_field,
                        category_id=water_id,
                        name="amount",
                        field_type=FieldType.NUMBER,
                    )
                ],
            )
        ]

        with pytest.raises(ChallengeProposalError):
            validate_proposals(proposals, categories)

    async def test_a_metric_rule_on_a_checkbox_is_refused(
        self, client: AsyncClient
    ) -> None:
        today = today_local()
        proposals = parse_proposals(
            f'{{"proposals": [{{"title": "{TITLE}", "category_id": 1, '
            f'"field_id": 2, "rule_kind": "metric_at_least", "target": 2, '
            f'"starts_on": "{today.isoformat()}", '
            f'"ends_on": "{(today + timedelta(days=6)).isoformat()}"}}]}}'
        )
        categories = [
            Category(
                id=1,
                name="Витамины",
                fields=[
                    Field(
                        id=2,
                        category_id=1,
                        name="D3",
                        field_type=FieldType.BOOLEAN,
                    )
                ],
            )
        ]

        with pytest.raises(ChallengeProposalError):
            validate_proposals(proposals, categories)

    async def test_an_empty_answer_is_a_valid_answer(self) -> None:
        proposals = parse_proposals('{"proposals": []}')
        validate_proposals(proposals, [])
        assert proposals == ChallengeProposals(proposals=[])

    async def test_a_proposal_never_carries_a_status_of_its_own(self) -> None:
        today = today_local()
        proposals = parse_proposals(
            f'{{"proposals": [{{"title": "{TITLE}", "category_id": 1, '
            f'"field_id": 2, "rule_kind": "checked", '
            f'"starts_on": "{today.isoformat()}", '
            f'"ends_on": "{(today + timedelta(days=6)).isoformat()}"}}]}}'
        )
        body = proposals.proposals[0].as_challenge()

        assert body.origin == "ai"
        assert body.initial_status() == "proposed"


@pytest.mark.asyncio
class TestTheTitleStaysOutOfTheLog:
    """Заголовок челленджа человек называет диагнозом. В логах его нет."""

    async def test_no_log_line_carries_the_title(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        category_id, field_id = await make_category(client, "Обезболивающие")
        today = today_local()

        with caplog.at_level(logging.DEBUG):
            created = await client.post(
                CHALLENGES_URL,
                json=proposal_body(
                    category_id,
                    field_id,
                    starts_on=today - timedelta(days=1),
                    ends_on=today + timedelta(days=5),
                ),
            )
            challenge_id = created.json()["id"]
            await client.post(f"{CHALLENGES_URL}/{challenge_id}/accept")

        assert TITLE not in caplog.text
