"""
Именованные выборки: белый список, потолки, аудит и конец цикла.

Здесь проверяется то, ради чего белый список вообще заведён. Что каждое из шести
имён возвращает верное число строк, а `health_daily` — те же числа, что отдаёт
`GET /health/metrics`. Что седьмое имя до базы не доходит и ход при этом
заканчивается ответом, а не пятисоткой. Что диапазон в три года и `table_slice`
на сто тысяч строк отвергаются схемой, а не исполняются «сколько влезет». Что
строка в `chat_retrievals` появляется на каждую выборку — включая отвергнутую, с
нулевым `row_count`. И что модель, отвечающая одним `need` за другим, упирается в
потолок заходов и договаривает словами.
"""

# [review:need-review] PHASE-03/114
# summary: tests for the named retrievals — the six names against known data, the seventh refused without reaching the database, params over the ceiling refused by schema, one `chat_retrievals` row per call including refusals, the pass ceiling ending a looping model in words, and the audit row visible under the message through GET /conversations/{id}
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_chat_llm_client, get_session_factory
from app.core.daytime import today_local
from app.crud import health as health_crud
from app.llm.chat.client import ChatChunk, ChatLLMClient
from app.llm.chat.prompt import ChatTurn
from app.llm.chat.retrieval import (
    MAX_NEED_PASSES,
    MAX_RANGE_DAYS,
    NAMED_QUERIES,
    QUERY_DAY_CARD,
    QUERY_ENTRIES_RANGE,
    QUERY_HEALTH_DAILY,
    QUERY_HINTS,
    QUERY_JOURNAL_RANGE,
    QUERY_STREAK,
    QUERY_INBOX_TASKS,
    QUERY_TABLE_SLICE,
    REFUSAL_BAD_PARAMS,
    REFUSAL_UNKNOWN_QUERY,
    NeedItem,
    parse_need,
    render_outcomes,
    run_need,
)
from app.llm.chat.session import ResumeHint
from app.main import app
from app.models.chat import ChatRetrieval
from app.models.journal import JournalEntry

CHAT_URL = "/api/v1/chat/conversations"

TODAY = today_local()
YESTERDAY = TODAY - timedelta(days=1)

STEPS = "HKQuantityTypeIdentifierStepCount"
BERLIN_SUMMER_OFFSET = 120

# Числа, которых нельзя получить ни округлением, ни суммой соседних: если они
# сойдутся с ручкой здоровья, сойдутся они именно потому, что путь один.
STEPS_TODAY = 6231.0
STEPS_YESTERDAY = 4118.0


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    """Каталог метрик, которого у базы из `create_all` нет."""
    await health_crud.seed_catalog(db_session)
    await db_session.commit()


class ScriptedChatClient(ChatLLMClient):
    """
    Транспорт, отвечающий заготовленным текстом на каждый заход хода.

    Отличие от `FakeChatClient` ровно одно и оно несущее: заходов за один ход
    теперь несколько, и заготовка — список ответов, а не список кусков. Так тест
    может сыграть «модель попросила данные и потом ответила словами», не поднимая
    ни процесса CLI, ни сети.
    """

    model: str = "scripted-chat-model"
    backend: str = "fake"

    def __init__(self, answers: Sequence[str]) -> None:
        self._answers = list(answers)
        self.calls = 0
        self.seen_turns: list[list[ChatTurn]] = []

    @property
    def cwd(self) -> str | None:
        return "/tmp/fake-chat-workspace"

    async def stream_turn(
        self,
        *,
        system_prompt: str,
        turns: Sequence[ChatTurn],
        resume: ResumeHint | None = None,
    ) -> AsyncIterator[ChatChunk]:
        index = min(self.calls, len(self._answers) - 1)
        self.calls += 1
        self.seen_turns.append(list(turns))
        yield ChatChunk.delta(self._answers[index])
        yield ChatChunk.usage(output_tokens=1)


@pytest.fixture
def install_chat(db_session: AsyncSession) -> Any:
    """Подменить фабрику сессий на тестовую и транспорт — на подставной."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    def install(transport: ChatLLMClient) -> ChatLLMClient:
        app.dependency_overrides[get_session_factory] = lambda: factory
        app.dependency_overrides[get_chat_llm_client] = lambda: transport
        return transport

    return install


def need_block(*items: dict[str, Any]) -> str:
    """Ответ модели, который просит данные, — тем же видом, что описан в промпте."""
    return "Сейчас посмотрю.\n\n```json\n" + json.dumps({"need": list(items)}) + "\n```"


async def new_conversation(client: AsyncClient) -> int:
    response = await client.post(CHAT_URL, json={})
    assert response.status_code == 201, response.text
    conversation_id = response.json()["id"]
    assert isinstance(conversation_id, int)
    return conversation_id


def journal_plan_answer(text: str) -> str:
    """Ответ словами и предложение записать текст дня рядом, как просит промпт."""
    plan = {
        "plan": {
            "entry_date": TODAY.isoformat(),
            "journal": {"op": "write_journal", "content": text},
        }
    }
    return (
        "Записал бы так.\n\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"
    )


async def last_answer(client: AsyncClient, conversation_id: int) -> dict[str, Any]:
    """Последняя реплика ассистента так, как её читает экран после перезагрузки."""
    response = await client.get(f"{CHAT_URL}/{conversation_id}")
    assert response.status_code == 200, response.text
    answers = [one for one in response.json()["messages"] if one["role"] == "assistant"]
    assert answers, "в разговоре нет ни одного ответа"
    return dict(answers[-1])


async def drain(client: AsyncClient, conversation_id: int, content: str) -> None:
    """Пройти ход целиком: важен его исход, а не отдельные кадры."""
    async with client.stream(
        "POST", f"{CHAT_URL}/{conversation_id}/messages", json={"content": content}
    ) as response:
        assert response.status_code == 200, await response.aread()
        async for _line in response.aiter_lines():
            pass


async def audit(db: AsyncSession) -> list[ChatRetrieval]:
    """Журнал выборок целиком, в порядке записи."""
    result = await db.execute(select(ChatRetrieval).order_by(ChatRetrieval.id))
    return list(result.scalars().all())


async def add_steps(client: AsyncClient, on: date, value: float) -> None:
    """Шаги одного дня — той же ручкой, которой их пишет импорт здоровья."""
    day = on.isoformat()
    response = await client.post(
        "/api/v1/health/samples",
        json={
            "samples": [
                {
                    "identifier": STEPS,
                    "value": value,
                    "unit": "count",
                    "start": f"{day}T09:00:00Z",
                    "end": f"{day}T09:30:00Z",
                    "utc_offset_minutes": BERLIN_SUMMER_OFFSET,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
class TestWhiteList:
    """Семь имён, и восьмое до базы не доходит."""

    async def test_the_registry_has_exactly_the_seven_named_queries(self) -> None:
        """Восьмое имя не появляется без правки реестра — и правка видна в диффе."""
        assert set(NAMED_QUERIES) == {
            QUERY_DAY_CARD,
            QUERY_ENTRIES_RANGE,
            QUERY_JOURNAL_RANGE,
            QUERY_HEALTH_DAILY,
            QUERY_STREAK,
            QUERY_TABLE_SLICE,
            QUERY_INBOX_TASKS,
        }

    async def test_the_prompt_describes_every_name_and_no_other(self) -> None:
        """Описание для модели не отстаёт от реестра: иначе она зовёт несуществующее."""
        assert set(QUERY_HINTS) == set(NAMED_QUERIES)

    async def test_a_name_outside_the_list_is_refused_without_touching_the_db(
        self, db_session: AsyncSession
    ) -> None:
        """Отказ по имени — текст модели и нулевой счётчик, а не запрос и не падение."""
        outcomes = await run_need(
            db_session, [NeedItem(query="raw_sql", params={"q": "select 1"})]
        )

        assert len(outcomes) == 1
        assert outcomes[0].refusal == REFUSAL_UNKNOWN_QUERY
        assert outcomes[0].row_count == 0
        # Отказ называет, что можно вместо: иначе модель переспрашивает вслепую.
        assert QUERY_HEALTH_DAILY in outcomes[0].text


@pytest.mark.asyncio
class TestSixNames:
    """Каждое имя возвращает верное число строк на известных данных."""

    async def test_day_card_returns_the_card_of_that_day(
        self, db_session: AsyncSession
    ) -> None:
        outcomes = await run_need(
            db_session,
            [NeedItem(query=QUERY_DAY_CARD, params={"date": TODAY.isoformat()})],
        )

        assert outcomes[0].refusal is None
        assert outcomes[0].row_count > 0
        assert TODAY.isoformat() in outcomes[0].text

    async def test_entries_range_counts_the_entries_it_returned(
        self, db_session: AsyncSession, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        for value in (200, 300):
            response = await client.post(
                "/api/v1/entries",
                json={
                    "category_id": water["id"],
                    "entry_date": TODAY.isoformat(),
                    "values": [
                        {"field_id": water["fields"][0]["id"], "value": str(value)}
                    ],
                },
            )
            assert response.status_code == 201, response.text

        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_ENTRIES_RANGE,
                    params={
                        "date_from": TODAY.isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )

        assert outcomes[0].refusal is None
        assert outcomes[0].row_count == 2

    async def test_journal_range_counts_entries_not_lines(
        self, db_session: AsyncSession
    ) -> None:
        """Строк в тексте много, записей две — счётчик считает записи."""
        for on in (YESTERDAY, TODAY):
            db_session.add(
                JournalEntry(
                    entry_date=on, title="день", content="первая строка\nвторая строка"
                )
            )
        await db_session.commit()

        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_JOURNAL_RANGE,
                    params={
                        "date_from": YESTERDAY.isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )

        assert outcomes[0].row_count == 2
        assert "вторая строка" in outcomes[0].text

    async def test_health_daily_matches_the_metrics_endpoint(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """
        Два числа выборки — те же два числа, что отдаёт `GET /health/metrics`.

        Это и есть приёмка «сравни сон за прошлую неделю с позапрошлой»: сравнение
        имеет смысл ровно тогда, когда путь к числу один, а не два похожих.
        """
        await add_steps(client, YESTERDAY, STEPS_YESTERDAY)
        await add_steps(client, TODAY, STEPS_TODAY)

        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_HEALTH_DAILY,
                    params={
                        "date_from": YESTERDAY.isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )

        response = await client.get(
            "/api/v1/health/metrics",
            params={
                "date_from": YESTERDAY.isoformat(),
                "date_to": TODAY.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        screen = {
            day["date"]: day["value"]
            for metric in response.json()["metrics"]
            if metric["identifier"] == STEPS
            for day in metric["days"]
        }

        assert outcomes[0].row_count == 2
        assert screen == {
            YESTERDAY.isoformat(): STEPS_YESTERDAY,
            TODAY.isoformat(): STEPS_TODAY,
        }
        for on, value in screen.items():
            assert f"{on} " in outcomes[0].text
            assert f"{value:g}" in outcomes[0].text

    async def test_streak_returns_one_row(
        self, db_session: AsyncSession, smoking: dict[str, Any]
    ) -> None:
        outcomes = await run_need(
            db_session,
            [NeedItem(query=QUERY_STREAK, params={"category_id": smoking["id"]})],
        )

        assert outcomes[0].refusal is None
        assert outcomes[0].row_count == 1

    async def test_inbox_tasks_gives_the_model_the_task_and_its_link(
        self, db_session: AsyncSession
    ) -> None:
        """
        Задачи ClickUp доезжают до модели — через контур входящих, а не по сети.

        Это и есть ответ на «чат не видит моих задач»: CLI запускается с
        `--tools ""` и наружу не ходит вовсе, поэтому единственный путь данных
        внутрь — именованная выборка, которая пишет о себе строку в
        `chat_retrievals`.
        """
        from app.crud import inbox as inbox_crud
        from app.models.inbox import InboundSignal

        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
        assert source is not None
        db_session.add(
            InboundSignal(
                source_id=source.id,
                external_id="86cb3xtv5",
                title="Починить сквозной flow покупки",
                external_url="https://app.clickup.com/t/86cb3xtv5",
                occurred_at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
                local_date=TODAY,
                state="new",
            )
        )
        await db_session.commit()

        outcomes = await run_need(
            db_session, [NeedItem(query=QUERY_INBOX_TASKS, params={})]
        )

        assert outcomes[0].refusal is None
        assert outcomes[0].row_count == 1
        assert "86cb3xtv5" in outcomes[0].text
        assert "Починить сквозной flow покупки" in outcomes[0].text

    async def test_inbox_tasks_says_so_when_nothing_arrived(
        self, db_session: AsyncSession
    ) -> None:
        """
        Пустой контур — это ответ, а не отказ.

        «Задач нет» и «источник не подключён» модель обязана различать: первое
        значит «планируй без них», второе — «скажи человеку включить источник».
        """
        outcomes = await run_need(
            db_session, [NeedItem(query=QUERY_INBOX_TASKS, params={})]
        )

        assert outcomes[0].refusal is None
        assert outcomes[0].row_count == 0

    async def test_table_slice_counts_cells(
        self, db_session: AsyncSession, client: AsyncClient, water: dict[str, Any]
    ) -> None:
        response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": water["id"],
                "entry_date": TODAY.isoformat(),
                "values": [{"field_id": water["fields"][0]["id"], "value": "250"}],
            },
        )
        assert response.status_code == 201, response.text

        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_TABLE_SLICE,
                    params={
                        "date_from": TODAY.isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )

        assert outcomes[0].refusal is None
        assert outcomes[0].row_count == 1


@pytest.mark.asyncio
class TestCeilings:
    """Параметры за потолком отвергаются схемой, а не исполняются «сколько влезет»."""

    async def test_three_year_range_is_refused(self, db_session: AsyncSession) -> None:
        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_HEALTH_DAILY,
                    params={
                        "date_from": (TODAY - timedelta(days=3 * 365)).isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )

        assert outcomes[0].refusal == REFUSAL_BAD_PARAMS
        assert outcomes[0].row_count == 0

    async def test_a_range_exactly_at_the_cap_is_allowed(
        self, db_session: AsyncSession
    ) -> None:
        """Потолок стоит на границе, а не около неё."""
        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_HEALTH_DAILY,
                    params={
                        "date_from": (
                            TODAY - timedelta(days=MAX_RANGE_DAYS - 1)
                        ).isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )

        assert outcomes[0].refusal is None

    async def test_a_hundred_thousand_rows_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_TABLE_SLICE,
                    params={
                        "date_from": TODAY.isoformat(),
                        "date_to": TODAY.isoformat(),
                        "limit": 100_000,
                    },
                )
            ],
        )

        assert outcomes[0].refusal == REFUSAL_BAD_PARAMS
        assert outcomes[0].row_count == 0
        # Отказ называет поле, а не значение: значение приехало от модели, а
        # добраться до неё оно могло только из реплики человека.
        assert "limit" in outcomes[0].text
        assert "100000" not in outcomes[0].text

    async def test_an_unknown_parameter_is_refused_rather_than_ignored(
        self, db_session: AsyncSession
    ) -> None:
        """`extra='forbid'`: параметр, которого нет, — ошибка, а не молчаливый ноль."""
        outcomes = await run_need(
            db_session,
            [NeedItem(query=QUERY_STREAK, params={"category_id": 1, "raw": "1=1"})],
        )

        assert outcomes[0].refusal == REFUSAL_BAD_PARAMS


@pytest.mark.asyncio
class TestParsing:
    """Разбор блока `need` не роняет ход и не принимает мусор за просьбу."""

    async def test_a_plain_answer_carries_no_need(self) -> None:
        assert parse_need("Вчера ты прошёл 6231 шаг.") is None

    async def test_a_broken_block_is_not_a_need(self) -> None:
        assert parse_need('{"need": [ broken') is None

    async def test_a_block_is_parsed_out_of_prose(self) -> None:
        items = parse_need(need_block({"query": QUERY_STREAK, "params": {"id": 1}}))

        assert items is not None
        assert items[0].query == QUERY_STREAK

    async def test_an_empty_retrieval_says_so_in_words(
        self, db_session: AsyncSession
    ) -> None:
        """«Записей нет» — ответ, а нулей модель дописала бы сама."""
        outcomes = await run_need(
            db_session,
            [
                NeedItem(
                    query=QUERY_JOURNAL_RANGE,
                    params={
                        "date_from": TODAY.isoformat(),
                        "date_to": TODAY.isoformat(),
                    },
                )
            ],
        )
        rendered = render_outcomes(outcomes, exhausted=False)

        assert "записей нет" in rendered


@pytest.mark.asyncio
class TestTurnWithRetrievals:
    """Ход целиком: выборка исполняется, пишется в журнал и видна под сообщением."""

    async def test_the_model_asks_gets_and_answers_in_one_turn(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """Просьба, выборка и ответ словами укладываются в один ход."""
        await add_steps(client, TODAY, STEPS_TODAY)
        transport = ScriptedChatClient(
            [
                need_block(
                    {
                        "query": QUERY_HEALTH_DAILY,
                        "params": {
                            "date_from": TODAY.isoformat(),
                            "date_to": TODAY.isoformat(),
                        },
                    }
                ),
                "Сегодня 6231 шаг.",
            ]
        )
        install_chat(transport)
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "сколько я сегодня прошёл?")

        assert transport.calls == 2
        # Второй заход видит выборку и прошлую реплику модели, а не только вопрос.
        assert any(
            "# Ответ на запрос данных" in turn.content
            for turn in transport.seen_turns[1]
        )

        rows = await audit(db_session)
        assert len(rows) == 1
        assert rows[0].query_name == QUERY_HEALTH_DAILY
        assert rows[0].row_count == 1
        assert rows[0].chars > 0

    async def test_the_audit_row_is_visible_under_the_message(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """Что было запрошено, видно с экрана — без единого чтения содержимого."""
        install_chat(
            ScriptedChatClient(
                [
                    need_block(
                        {
                            "query": QUERY_STREAK,
                            "params": {"category_id": 1},
                        }
                    ),
                    "Серии пока нет.",
                ]
            )
        )
        conversation_id = await new_conversation(client)
        await drain(client, conversation_id, "как моя серия?")

        response = await client.get(f"{CHAT_URL}/{conversation_id}")
        assert response.status_code == 200, response.text
        answers = [
            one for one in response.json()["messages"] if one["role"] == "assistant"
        ]

        assert len(answers) == 1
        shown = answers[0]["retrievals"]
        assert len(shown) == 1
        assert shown[0]["query_name"] == QUERY_STREAK
        assert shown[0]["params"] == {"category_id": 1}
        # `>= 0` здесь пройдёт всегда: колонка `chars` объявлена `Mapped[int]`
        # и отрицательной не бывает. Приёмка #114 требует непустой выборки.
        assert shown[0]["chars"] > 0

    async def test_a_name_outside_the_list_ends_the_turn_with_an_answer(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """Подставной ответ с чужим именем даёт отказ и ответ, а не 500."""
        install_chat(
            ScriptedChatClient(
                [
                    need_block({"query": "chat_messages", "params": {}}),
                    "Такого я достать не могу.",
                ]
            )
        )
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "покажи чужие сообщения")

        rows = await audit(db_session)
        assert len(rows) == 1
        assert rows[0].query_name == "chat_messages"
        assert rows[0].row_count == 0

    async def test_params_over_the_cap_leave_a_row_with_zero_rows(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        install_chat(
            ScriptedChatClient(
                [
                    need_block(
                        {
                            "query": QUERY_TABLE_SLICE,
                            "params": {
                                "date_from": TODAY.isoformat(),
                                "date_to": TODAY.isoformat(),
                                "limit": 100_000,
                            },
                        }
                    ),
                    "Столько за раз нельзя.",
                ]
            )
        )
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "выгрузи всю таблицу")

        rows = await audit(db_session)
        assert len(rows) == 1
        assert rows[0].row_count == 0

    async def test_a_looping_model_stops_at_the_pass_ceiling(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """
        Модель, зациклившаяся на `need`, останавливается сама.

        Заготовка отвечает блоком `need` на любой заход. Ход обязан закончиться
        конечным числом обращений к бэкенду, а не висеть до срока: заходов ровно
        `MAX_NEED_PASSES` плюс первый.
        """
        transport = ScriptedChatClient(
            [need_block({"query": QUERY_STREAK, "params": {"category_id": 1}})]
        )
        install_chat(transport)
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "и ещё раз")

        assert transport.calls == MAX_NEED_PASSES + 1
        rows = await audit(db_session)
        assert len(rows) == MAX_NEED_PASSES

    async def test_a_turn_without_a_need_leaves_the_audit_empty(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """Обычный ход не пишет ни строки: журнал — след выборок, а не ходов."""
        install_chat(ScriptedChatClient(["Сегодня всё по плану."]))
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "как дела?")

        assert await audit(db_session) == []


@pytest.mark.asyncio
class TestWhatTheHumanSees:
    """
    Что остаётся человеку от хода, в котором модель ходила за данными.

    Ход из нескольких заходов — это разговор модели с сервером, и только
    последний его заход адресован человеку. Блок `need` — служебная просьба:
    она уже отражена строкой `chat_retrievals` под ответом, и её место не в
    пузыре. Проверяется здесь и обратное: план, приложенный к ответу **после**
    похода за данными, обязан доехать до плашки, как доезжает план из хода без
    выборок.
    """

    async def test_the_need_block_never_reaches_the_stored_answer(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """В сообщении остаётся ответ словами, а не переписка с сервером."""
        await add_steps(client, TODAY, STEPS_TODAY)
        install_chat(
            ScriptedChatClient(
                [
                    need_block(
                        {
                            "query": QUERY_HEALTH_DAILY,
                            "params": {
                                "date_from": TODAY.isoformat(),
                                "date_to": TODAY.isoformat(),
                            },
                        }
                    ),
                    "Сегодня 6231 шаг.",
                ]
            )
        )
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "сколько я сегодня прошёл?")

        answer = await last_answer(client, conversation_id)
        assert answer["content"] == "Сегодня 6231 шаг."
        assert "need" not in answer["content"]

    async def test_a_plan_offered_after_a_retrieval_still_reaches_the_card(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Поход за данными не должен стоить предложения.

        `extract_json` берёт кусок от первой открывающей скобки до последней
        закрывающей. Пока текст хода был склейкой всех заходов, ход «сначала
        `need`, потом план» давал span, внутри которого два объекта и проза
        между ними, — то есть битый JSON, и плашка не появлялась никогда.
        """
        await add_steps(client, TODAY, STEPS_TODAY)
        install_chat(
            ScriptedChatClient(
                [
                    need_block(
                        {
                            "query": QUERY_HEALTH_DAILY,
                            "params": {
                                "date_from": TODAY.isoformat(),
                                "date_to": TODAY.isoformat(),
                            },
                        }
                    ),
                    journal_plan_answer("Прошёл 6231 шаг."),
                ]
            )
        )
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "запиши, сколько я прошёл")

        answer = await last_answer(client, conversation_id)
        assert answer["plan_id"] is not None, "план не доехал до плашки"


@pytest.mark.asyncio
class TestAuditAnswersOnItsOwn:
    """Журнал отвечает «какие данные уходили», не читая ни одного сообщения."""

    async def test_two_ranges_leave_two_rows(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """
        Сравнение недели с позапрошлой — две выборки и две строки журнала.

        Один блок `need` с двумя именами не имеет права схлопнуться в одну
        запись: диапазоны разные, и «какие данные уходили» отвечается ими, а не
        числом обращений.
        """
        await add_steps(client, TODAY, STEPS_TODAY)
        await add_steps(client, YESTERDAY, STEPS_YESTERDAY)
        install_chat(
            ScriptedChatClient(
                [
                    need_block(
                        {
                            "query": QUERY_HEALTH_DAILY,
                            "params": {
                                "date_from": TODAY.isoformat(),
                                "date_to": TODAY.isoformat(),
                            },
                        },
                        {
                            "query": QUERY_HEALTH_DAILY,
                            "params": {
                                "date_from": YESTERDAY.isoformat(),
                                "date_to": YESTERDAY.isoformat(),
                            },
                        },
                    ),
                    "Сегодня 6231, вчера 4118.",
                ]
            )
        )
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "сравни сегодня и вчера")

        rows = await audit(db_session)
        assert len(rows) == 2
        assert [one.row_count for one in rows] == [1, 1]
        assert all(one.chars > 0 for one in rows)
        assert [one.params["date_from"] for one in rows] == [
            TODAY.isoformat(),
            YESTERDAY.isoformat(),
        ]

    async def test_the_journal_never_stores_the_data_itself(
        self, client: AsyncClient, install_chat: Any, db_session: AsyncSession
    ) -> None:
        """
        В строке журнала нет данных — только имя, параметры и размер.

        Иначе таблица аудита стала бы вторым местом, где лежит текст дневника, и
        вопрос «какие мои данные покинули сервер» пришлось бы задавать ей самой.
        """
        secret = "контрольная фраза дневника — якорь-114"
        db_session.add(JournalEntry(entry_date=TODAY, title="день", content=secret))
        await db_session.commit()
        install_chat(
            ScriptedChatClient(
                [
                    need_block(
                        {
                            "query": QUERY_JOURNAL_RANGE,
                            "params": {
                                "date_from": TODAY.isoformat(),
                                "date_to": TODAY.isoformat(),
                            },
                        }
                    ),
                    "Ты записал одну заметку.",
                ]
            )
        )
        conversation_id = await new_conversation(client)

        await drain(client, conversation_id, "что я писал сегодня?")

        rows = await audit(db_session)
        assert len(rows) == 1
        stored = json.dumps(
            {
                "query_name": rows[0].query_name,
                "params": rows[0].params,
                "row_count": rows[0].row_count,
                "chars": rows[0].chars,
            },
            ensure_ascii=False,
        )
        assert secret not in stored
        # Размер при этом назван: сколько знаков ушло, видно без самих знаков.
        assert rows[0].chars >= len(secret)
