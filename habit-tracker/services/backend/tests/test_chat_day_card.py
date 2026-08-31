"""
Карточка дня: что чат видит, чего он не видит и чем платит на потолке.

Здесь проверяется ровно то, из-за чего карточка вообще ограничена. Что пустой
день говорит «записей нет», а не молчит (молчание модель дописывает нулями). Что
дневная свёртка здоровья — то же число, что отдаёт `GET /health/metrics`, и что
почасовых корзин в карточке нет. Что день с полусотней записей и дневником на
двадцать тысяч знаков укладывается в потолок, теряя хвост наименее приоритетной
секции, а не обрываясь на середине числа. И что раскрывашка «что чат видит»
показывает тот же текст, который ушёл в системный промпт.
"""

# [review:need-review] PHASE-03/113
# summary: tests for build_day_card — the explicit "записей нет" of an empty day, the health fold that matches GET /health/metrics, hourly buckets staying out, the ceiling eating the least important section first, a section without a source missing entirely, and GET /chat/conversations/{id}/context returning the very text the prompt carried
import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_chat_llm_client, get_session_factory
from app.core.config import settings
from app.core.daytime import today_local
from app.crud import chat as chat_crud
from app.crud import day as day_crud
from app.crud import health as health_crud
from app.llm.chat.context import (
    DAY_CARD_SECTIONS,
    NO_DATA_LINE,
    SectionSpec,
    build_day_card,
)
from app.llm.chat.prompt import CHAT_CONTEXT_VERSION, compose_system_prompt
from app.main import app
from app.models.journal import JournalEntry
from tests.test_chat_stream import FakeChatClient

CARD_DAY = today_local()

STEPS = "HKQuantityTypeIdentifierStepCount"
BERLIN_SUMMER_OFFSET = 120

# Значение, которое нельзя получить случайно ни округлением, ни суммой соседних.
MORNING_STEPS = 3417.0
EVENING_STEPS = 5004.0

CHAT_URL = "/api/v1/chat/conversations"


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    """Каталог метрик, которого у базы из `create_all` нет."""
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


@pytest.fixture
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """Правила дня и цель квартала — предусловие любого сохранённого плана."""
    await day_crud.seed_rules(db_session)
    yield


@pytest.fixture
def install_chat(db_session: AsyncSession) -> Any:
    """
    Подменить фабрику сессий на тестовую и транспорт — на подставной.

    Та же подмена, что в `test_chat_stream`: ход открывает сессию дважды, и
    настоящая фабрика на тестовой базе завела бы вторую транзакцию, которая
    первую не видит.
    """

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    def install(client: FakeChatClient) -> FakeChatClient:
        app.dependency_overrides[get_session_factory] = lambda: factory
        app.dependency_overrides[get_chat_llm_client] = lambda: client
        return client

    return install


def sample(value: float, start: str, end: str) -> dict[str, Any]:
    return {
        "identifier": STEPS,
        "value": value,
        "unit": "count",
        "start": start,
        "end": end,
        "utc_offset_minutes": BERLIN_SUMMER_OFFSET,
    }


async def add_journal(
    db: AsyncSession, on: date, *, title: str, content: str
) -> JournalEntry:
    """Запись дневника прямо в таблицу: карточка читает её, а не ручку."""
    entry = JournalEntry(entry_date=on, title=title, content=content)
    db.add(entry)
    await db.flush()
    return entry


async def make_category(client: AsyncClient, name: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "fields": [{"name": "Отжимания", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def drain(client: AsyncClient, url: str, content: str) -> None:
    """Пройти ход целиком, не разбирая событий: важен промпт, а не поток."""
    async with client.stream("POST", url, json={"content": content}) as response:
        assert response.status_code == 200, await response.aread()
        async for _line in response.aiter_lines():
            pass


async def new_conversation(client: AsyncClient) -> int:
    response = await client.post(CHAT_URL, json={})
    assert response.status_code == 201, response.text
    conversation_id = response.json()["id"]
    assert isinstance(conversation_id, int)
    return conversation_id


@pytest.mark.asyncio
class TestEmptyDay:
    """Пустой день не молчит и не выдумывает нулей."""

    async def test_every_section_says_no_records(
        self, db_session: AsyncSession
    ) -> None:
        """За каждой секцией стоит «записей нет», а не пустое место."""
        card = await build_day_card(db_session, CARD_DAY)

        assert CARD_DAY.isoformat() in card.text
        for spec in DAY_CARD_SECTIONS:
            assert f"## {spec.title}" in card.text
        assert card.text.count(NO_DATA_LINE) == len(DAY_CARD_SECTIONS)
        assert card.truncated is False
        assert card.dropped_sections == ()

    async def test_no_digits_are_invented(self, db_session: AsyncSession) -> None:
        """В пустой карточке нет ни одного числа, кроме даты в шапке."""
        card = await build_day_card(db_session, CARD_DAY)

        body = card.text.split("\n", 1)[1]
        assert re.search(r"\d", body) is None


@pytest.mark.asyncio
class TestRegistry:
    """Реестр секций: источника нет — секции нет."""

    async def test_section_without_source_is_absent_entirely(
        self, db_session: AsyncSession
    ) -> None:
        """Строитель, вернувший None, не оставляет ни подписи, ни «записей нет»."""

        async def missing(_db: AsyncSession, _on: date) -> list[str] | None:
            return None

        async def present(_db: AsyncSession, _on: date) -> list[str] | None:
            return ["строка есть"]

        card = await build_day_card(
            db_session,
            CARD_DAY,
            sections=[
                SectionSpec("inbox", "Входящие", priority=10, build=missing),
                SectionSpec("present", "Присутствует", priority=20, build=present),
            ],
        )

        assert "Входящие" not in card.text
        assert "## Присутствует" in card.text
        assert NO_DATA_LINE not in card.text


@pytest.mark.asyncio
class TestHealthSection:
    """Дневная свёртка в карточке и почасовые корзины вне её."""

    async def test_matches_the_metrics_endpoint(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Цифра в карточке — та же, что отдаёт `GET /health/metrics` за тот день."""
        day = CARD_DAY.isoformat()
        response = await client.post(
            "/api/v1/health/samples",
            json={
                "samples": [
                    sample(MORNING_STEPS, f"{day}T06:00:00Z", f"{day}T06:30:00Z"),
                    sample(EVENING_STEPS, f"{day}T17:00:00Z", f"{day}T17:30:00Z"),
                ]
            },
        )
        assert response.status_code == 200, response.text

        metrics = await client.get(
            "/api/v1/health/metrics", params={"date_from": day, "date_to": day}
        )
        assert metrics.status_code == 200
        series = next(
            one for one in metrics.json()["metrics"] if one["identifier"] == STEPS
        )
        from_endpoint = float(series["days"][0]["value"])

        card = await build_day_card(db_session, CARD_DAY)
        line = next(
            one
            for one in card.text.splitlines()
            if one.startswith(f"{series['display_name']}:")
        )
        from_card = float(line.split(":", 1)[1].split()[0])

        assert from_card == from_endpoint
        assert from_endpoint == MORNING_STEPS + EVENING_STEPS

    async def test_hourly_buckets_stay_out(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """В карточке дневная сумма и ни одного часового слагаемого."""
        day = CARD_DAY.isoformat()
        await client.post(
            "/api/v1/health/samples",
            json={
                "samples": [
                    sample(MORNING_STEPS, f"{day}T06:00:00Z", f"{day}T06:30:00Z"),
                    sample(EVENING_STEPS, f"{day}T17:00:00Z", f"{day}T17:30:00Z"),
                ]
            },
        )

        card = await build_day_card(db_session, CARD_DAY)

        assert str(int(MORNING_STEPS + EVENING_STEPS)) in card.text
        assert str(int(MORNING_STEPS)) not in card.text
        assert str(int(EVENING_STEPS)) not in card.text


@pytest.mark.asyncio
class TestCeiling:
    """Потолок: строки выбывают с хвоста, а не режется строка."""

    async def _fill_a_loud_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Пятьдесят записей и дневник на двадцать тысяч знаков."""
        category = await make_category(client, "Тренировка")
        field_id = category["fields"][0]["id"]
        for number in range(50):
            response = await client.post(
                "/api/v1/entries",
                json={
                    "category_id": category["id"],
                    "entry_date": CARD_DAY.isoformat(),
                    "values": [{"field_id": field_id, "value": str(number + 1)}],
                },
            )
            assert response.status_code == 201, response.text

        paragraph = "Строка дневника про то, как прошёл день, и она не короткая. "
        content = "\n".join(paragraph * 2 for _ in range(200))
        assert len(content) >= 20_000
        await add_journal(db_session, CARD_DAY, title="Длинный день", content=content)
        await db_session.commit()

    async def test_loud_day_fits_the_ceiling(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Карточка не длиннее потолка, и видно, какая секция за это заплатила."""
        await self._fill_a_loud_day(client, db_session)

        # Потолок из настроек — тот самый `CHAT_CONTEXT_MAX_CHARS`, под который
        # день и собирается в бою.
        default = await build_day_card(db_session, CARD_DAY)
        tight = await build_day_card(db_session, CARD_DAY, max_chars=4_000)

        assert default.max_chars == settings.CHAT_CONTEXT_MAX_CHARS
        assert default.chars <= settings.CHAT_CONTEXT_MAX_CHARS
        assert default.truncated is True
        assert default.dropped_sections == ("journal",)

        assert tight.chars == len(tight.text)
        assert tight.chars <= 4_000
        assert tight.truncated is True
        assert "journal" in tight.dropped_sections
        assert re.search(r"… не поместилось строк: \d+", tight.text)

    async def test_ceiling_never_cuts_a_line_in_half(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Карточка кончается целой строкой-пометкой, а не обрубком абзаца."""
        await self._fill_a_loud_day(client, db_session)

        card = await build_day_card(db_session, CARD_DAY, max_chars=4_000)

        assert re.fullmatch(r"… не поместилось строк: \d+", card.text.splitlines()[-1])

    async def test_health_survives_a_ceiling_the_journal_does_not(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Дневник выбывает, дневная свёртка остаётся: приоритет у здоровья выше."""
        await self._fill_a_loud_day(client, db_session)
        day = CARD_DAY.isoformat()
        await client.post(
            "/api/v1/health/samples",
            json={
                "samples": [
                    sample(MORNING_STEPS, f"{day}T06:00:00Z", f"{day}T06:30:00Z")
                ]
            },
        )

        card = await build_day_card(db_session, CARD_DAY, max_chars=1_000)

        assert card.dropped_sections[0] == "journal"
        assert "health" not in card.dropped_sections
        assert str(int(MORNING_STEPS)) in card.text

    async def test_drop_order_follows_priority(self, db_session: AsyncSession) -> None:
        """Выбывает наименее приоритетная секция, и только потом следующая."""

        def section(name: str, priority: int) -> SectionSpec:
            async def build(_db: AsyncSession, _on: date) -> list[str] | None:
                return [f"{name} строка {number:02d}" for number in range(20)]

            return SectionSpec(name, name.upper(), priority=priority, build=build)

        specs = [section("keep", 10), section("middle", 20), section("last", 30)]
        whole = await build_day_card(
            db_session, CARD_DAY, max_chars=1_000_000, sections=specs
        )

        gentle = await build_day_card(
            db_session, CARD_DAY, max_chars=whole.chars - 100, sections=specs
        )
        harsh = await build_day_card(
            db_session, CARD_DAY, max_chars=whole.chars - 500, sections=specs
        )

        assert whole.truncated is False
        assert gentle.dropped_sections == ("last",)
        assert harsh.dropped_sections == ("last", "middle")
        # Самая приоритетная секция цела в обеих обрезках.
        for number in range(20):
            assert f"keep строка {number:02d}" in harsh.text


@pytest.mark.asyncio
class TestPromptAndDisclosure:
    """Промпт получает карточку, раскрывашка показывает ровно её."""

    async def test_context_endpoint_returns_what_the_prompt_carried(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        install_chat: Any,
    ) -> None:
        """Фраза из ответа `/context` находится в системном промпте хода."""
        await add_journal(
            db_session,
            CARD_DAY,
            title="Утро",
            content="Контрольная фраза дневника: якорь-113.",
        )
        await db_session.commit()

        fake = install_chat(FakeChatClient(["ок"]))
        conversation_id = await new_conversation(client)
        await drain(
            client, f"{CHAT_URL}/{conversation_id}/messages", "что у меня сегодня"
        )

        response = await client.get(f"{CHAT_URL}/{conversation_id}/context")

        assert response.status_code == 200
        body = response.json()
        assert body["conversation_id"] == conversation_id
        assert body["entry_date"] == CARD_DAY.isoformat()
        assert body["chars"] == len(body["text"])
        assert body["truncated"] is False
        assert "Контрольная фраза дневника: якорь-113." in body["text"]

        assert fake.seen_prompt is not None
        # Посимвольно: карточка ушла в промпт ровно этим текстом.
        assert body["text"] in fake.seen_prompt
        assert fake.seen_prompt == compose_system_prompt(body["text"])

    async def test_context_of_unknown_conversation_is_404(
        self, client: AsyncClient
    ) -> None:
        """Карточка несуществующего разговора — 404, а не пустой текст."""
        response = await client.get(f"{CHAT_URL}/9999/context")

        assert response.status_code == 404

    async def test_stale_context_version_loses_the_session_hint(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        install_chat: Any,
    ) -> None:
        """Разговор под прежним промптом теряет подсказку сессии, но не себя."""
        install_chat(FakeChatClient(["ок"]))
        conversation_id = await new_conversation(client)
        conversation = await chat_crud.get_conversation(db_session, conversation_id)
        assert conversation is not None
        conversation.context_version = CHAT_CONTEXT_VERSION - 1
        conversation.cli_session_id = "00000000-1111-2222-3333-444444444444"
        await db_session.commit()

        await drain(client, f"{CHAT_URL}/{conversation_id}/messages", "привет")

        detail = await client.get(f"{CHAT_URL}/{conversation_id}")
        assert detail.status_code == 200
        assert detail.json()["context_version"] == CHAT_CONTEXT_VERSION
        assert len(detail.json()["messages"]) == 2

        refreshed = await chat_crud.get_conversation(db_session, conversation_id)
        assert refreshed is not None
        assert refreshed.cli_session_id != "00000000-1111-2222-3333-444444444444"


@pytest.mark.asyncio
class TestPlanSection:
    """План дня и его отметки — одной секцией, а не двумя половинами."""

    async def test_plan_items_and_marks_are_in_the_card(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        seeded_rules: None,
    ) -> None:
        """Пункт плана виден с окном, а поставленная отметка — рядом с ним."""
        day = CARD_DAY.isoformat()
        plan = await client.post(
            f"/api/v1/day/{day}/plan",
            json={
                "title": f"План {day}",
                "sections": [
                    {
                        "kind": "work",
                        "title": "Работа",
                        "items": [
                            {
                                "kind": "task",
                                "code": "W1",
                                "text_md": "Починить conn_to_coll",
                                "window": "09:00-10:00",
                                "done_criterion": "тест зелёный",
                                "quarter_goal_id": 1,
                            }
                        ],
                    }
                ],
            },
        )
        assert plan.status_code == 201, plan.text
        item_id = plan.json()["sections"][0]["items"][0]["id"]
        mark = await client.put(
            f"/api/v1/day/{day}/marks/{item_id}",
            json={"state": "done", "note": "успел до обеда"},
        )
        assert mark.status_code == 200, mark.text

        card = await build_day_card(db_session, CARD_DAY)

        assert "Починить conn_to_coll" in card.text
        assert "09:00–10:00" in card.text
        assert "отметка: done" in card.text
        assert "успел до обеда" in card.text

    async def test_the_card_names_every_line_by_its_code(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        seeded_rules: None,
    ) -> None:
        """
        Код строки — то, чем чат сохраняет прожитый день при перезаписи (`#187`).

        Отметка переносится на строку, чей id вернулся в новом плане, а id
        считается из кода. Не видя кодов, модель может только стереть день, и
        проверять это надо на карточке, а не на промпте: промпт просит беречь
        коды, которых в карточке может не оказаться.
        """
        day = CARD_DAY.isoformat()
        plan = await client.post(
            f"/api/v1/day/{day}/plan",
            json={
                "title": f"План {day}",
                "sections": [
                    {
                        "kind": "work",
                        "title": "Работа",
                        "items": [
                            {
                                "kind": "task",
                                "code": "W1",
                                "rigidity": "soft",
                                "text_md": "Починить conn_to_coll",
                                "window": "09:00-10:00",
                                "done_criterion": "тест зелёный",
                                "quarter_goal_id": 1,
                            }
                        ],
                    }
                ],
            },
        )
        assert plan.status_code == 201, plan.text

        card = await build_day_card(db_session, CARD_DAY)

        assert "код W1" in card.text
        assert "[task/soft]" in card.text
        assert "тест зелёный" in card.text
