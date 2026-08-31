"""
Ход разговора по SSE: порядок событий, запись сообщений и отказы.
"""

# [review:need-review] PHASE-03/111, PHASE-03/113
# summary: PHASE-03/113 moved the system prompt of a turn to compose_system_prompt(day card), so the prompt assertion checks the composition rather than the bare constant
# summary: SSE tests over a stubbed ChatLLMClient — event order (delta*, usage, done), the answer written with its token counters, monotonic seq across two turns, the dialogue replayed to the model on the second turn, 503 without a backend leaving no row, and a backend failure landing as `failed` with a machine code rather than as a 500
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import (
    ERROR_CODE_BACKEND,
    SSE_EVENT_ACTING,
    SSE_EVENT_STEP_END,
    SSE_EVENT_STOP,
    SSE_EVENT_THINKING,
    SSE_EVENT_WRITING,
)
from app.api.deps import get_chat_llm_client, get_session_factory
from app.crud import chat as chat_crud
from app.llm.chat.client import ChatChunk, ChatLLMClient
from app.llm.chat.prompt import (
    CHAT_SYSTEM_PROMPT,
    ChatTurn,
    compose_system_prompt,
)
from app.llm.chat.session import ResumeHint
from app.llm.client import LLMError
from app.main import app
from app.models.chat import (
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INTERRUPTED,
    ChatMessage,
)
from app.schemas.chat import (
    SSE_EVENT_DELTA,
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_RETRIEVAL,
    SSE_EVENT_USAGE,
)

CONTROL_PHRASE = "якорь-77 контрольная фраза"
FAKE_SESSION_ID = "11111111-2222-3333-4444-555555555555"
# Внутренняя речь модели о дне человека. Своя контрольная фраза, потому что
# проверяется не «нет содержимого вообще», а «мысль не оказалась там, где ответ».
INNER_SPEECH = "якорь-42 он третий день не спит, надо мягче"


class FakeChatClient(ChatLLMClient):
    """
    Подставной транспорт: отдаёт заготовленные куски и запоминает, что получил.

    Граница моков ровно здесь, как и договорено ADR: тест разговора не поднимает
    ни процесса CLI, ни сети.
    """

    model: str = "fake-chat-model"
    backend: str = "fake"

    def __init__(self, pieces: Sequence[str], *, fail: bool = False) -> None:
        self._pieces = list(pieces)
        self._fail = fail
        self.calls = 0
        self.seen_prompt: str | None = None
        self.seen_turns: list[ChatTurn] = []
        self.seen_resume: ResumeHint | None = None

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
        self.calls += 1
        self.seen_prompt = system_prompt
        self.seen_turns = list(turns)
        self.seen_resume = resume
        for piece in self._pieces:
            yield ChatChunk.delta(piece)
        if self._fail:
            raise LLMError("upstream said no")
        yield ChatChunk.usage(
            session_id=FAKE_SESSION_ID,
            input_tokens=282,
            output_tokens=12,
            cache_read_tokens=0,
        )


class ScriptedChatClient(ChatLLMClient):
    """
    Транспорт, отдающий заготовленные куски какого угодно вида.

    Отдельно от `FakeChatClient`, а не флагом на нём: тот отвечает только
    текстом, и на нём стоят проверки, которые обязаны продолжать видеть ровно
    прежний поток — иначе «старый клиент не сломался» доказывается тем же
    кодом, что и «новый заработал».
    """

    model: str = "fake-chat-model"
    backend: str = "fake"

    def __init__(self, chunks: Sequence[ChatChunk], *, fail: bool = False) -> None:
        self._chunks = list(chunks)
        self._fail = fail

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
        for chunk in self._chunks:
            yield chunk
        if self._fail:
            raise LLMError("upstream said no")


# Ход так, как его печатает живой CLI: думает, кончил думать, пишет, кончил
# писать, остановился — и только потом итог.
THINKING_TURN: list[ChatChunk] = [
    ChatChunk.thinking_step(index=0),
    ChatChunk.thinking_step(index=0, thinking_tokens=50),
    ChatChunk.step_end(index=0),
    ChatChunk.writing(index=1),
    ChatChunk.delta("Первый "),
    ChatChunk.delta("кусок"),
    ChatChunk.step_end(index=1),
    ChatChunk.stop(stop_reason="end_turn", thinking_tokens=27),
    ChatChunk.usage(
        session_id=FAKE_SESSION_ID,
        input_tokens=282,
        output_tokens=12,
        cache_read_tokens=0,
    ),
]


@pytest.fixture(scope="function")
def install_chat(db_session: AsyncSession) -> Any:
    """
    Подменить фабрику сессий на тестовую и транспорт — на подставной.

    Фабрика отдаёт ту же сессию, что и остальные ручки теста, и не закрывает
    её: эндпоинт открывает её дважды за ход, и настоящая фабрика на тестовой
    базе открыла бы вторую транзакцию, которая первую не видит.
    """

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    def install(client: ChatLLMClient | None) -> ChatLLMClient | None:
        app.dependency_overrides[get_session_factory] = lambda: factory
        app.dependency_overrides[get_chat_llm_client] = lambda: client
        return client

    return install


async def _read_events(
    client: AsyncClient, url: str, content: str
) -> list[tuple[str, dict[str, Any]]]:
    """Разобрать поток SSE в список пар «имя события, данные»."""
    events: list[tuple[str, dict[str, Any]]] = []
    async with client.stream("POST", url, json={"content": content}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        name: str | None = None
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                assert name is not None
                events.append((name, json.loads(line[len("data: ") :])))
                name = None
    return events


async def _new_conversation(client: AsyncClient) -> int:
    response = await client.post("/api/v1/chat/conversations", json={})
    assert response.status_code == 201
    conversation_id = response.json()["id"]
    assert isinstance(conversation_id, int)
    return conversation_id


@pytest.mark.asyncio
class TestConversations:
    """Заведение и чтение разговоров."""

    async def test_create_defaults_to_today_and_general(
        self, client: AsyncClient
    ) -> None:
        """Без тела разговор всё равно получает день и вид."""
        response = await client.post("/api/v1/chat/conversations", json={})

        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "general"
        assert body["started_on"]
        assert body["title"] is None

    async def test_unknown_kind_is_refused(self, client: AsyncClient) -> None:
        """Вид вне словаря — 422, а не молча записанная строка."""
        response = await client.post(
            "/api/v1/chat/conversations", json={"kind": "whatever"}
        )

        assert response.status_code == 422

    async def test_feed_lists_conversations(self, client: AsyncClient) -> None:
        """Лента отдаёт заведённые разговоры."""
        first = await _new_conversation(client)
        second = await _new_conversation(client)

        response = await client.get("/api/v1/chat/conversations")

        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert set(ids) == {first, second}

    async def test_unknown_conversation_is_404(self, client: AsyncClient) -> None:
        """Чтение несуществующего разговора — 404."""
        response = await client.get("/api/v1/chat/conversations/9999")

        assert response.status_code == 404


@pytest.mark.asyncio
class TestTurn:
    """Один ход: поток наружу, две строки внутрь."""

    async def test_events_arrive_in_order_and_answer_is_stored(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """delta по кускам, затем usage, затем done; ответ лежит в таблице."""
        install_chat(FakeChatClient(["Пер", "вый ", "кусок"]))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        names = [name for name, _ in events]
        assert names == [
            SSE_EVENT_DELTA,
            SSE_EVENT_DELTA,
            SSE_EVENT_DELTA,
            SSE_EVENT_USAGE,
            SSE_EVENT_DONE,
        ]
        assert [data["text"] for name, data in events if name == SSE_EVENT_DELTA] == [
            "Пер",
            "вый ",
            "кусок",
        ]

        rows = (
            (
                await db_session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(ChatMessage.seq)
                )
            )
            .scalars()
            .all()
        )
        assert [row.role for row in rows] == [
            MESSAGE_ROLE_USER,
            MESSAGE_ROLE_ASSISTANT,
        ]
        assert rows[0].content == CONTROL_PHRASE
        assert rows[1].content == "Первый кусок"
        assert rows[1].status == MESSAGE_STATUS_COMPLETE
        assert rows[1].input_tokens == 282
        assert rows[1].output_tokens == 12
        assert rows[1].latency_ms is not None

    async def test_seq_is_monotonic_across_two_turns(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """Четыре сообщения получают позиции 1..4 без дырок и повторов."""
        install_chat(FakeChatClient(["ответ"]))
        conversation_id = await _new_conversation(client)
        url = f"/api/v1/chat/conversations/{conversation_id}/messages"

        await _read_events(client, url, "первый вопрос")
        await _read_events(client, url, "второй вопрос")

        rows = (
            (
                await db_session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(ChatMessage.seq)
                )
            )
            .scalars()
            .all()
        )
        assert [row.seq for row in rows] == [1, 2, 3, 4]

    async def test_second_turn_replays_the_whole_dialogue(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Модель второго хода видит весь разговор, а не только новую реплику.

        Это и есть «история в таблице — источник истины»: транспорт получает
        реплики из базы, а не из памяти процесса.
        """
        fake = FakeChatClient(["ответ"])
        install_chat(fake)
        conversation_id = await _new_conversation(client)
        url = f"/api/v1/chat/conversations/{conversation_id}/messages"

        await _read_events(client, url, "первый вопрос")
        await _read_events(client, url, "второй вопрос")

        assert [turn.role for turn in fake.seen_turns] == [
            MESSAGE_ROLE_USER,
            MESSAGE_ROLE_ASSISTANT,
            MESSAGE_ROLE_USER,
        ]
        assert fake.seen_turns[0].content == "первый вопрос"
        assert fake.seen_turns[-1].content == "второй вопрос"

    async def test_the_chat_system_prompt_is_the_one_sent(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Системный промпт собирается в одном месте, а не в ручке."""
        fake = FakeChatClient(["ok"])
        install_chat(fake)
        conversation_id = await _new_conversation(client)

        await _read_events(
            client, f"/api/v1/chat/conversations/{conversation_id}/messages", "привет"
        )

        # Правила поведения и карточка дня склеиваются `compose_system_prompt`;
        # ручка не имеет права добавить к ним ни строки от себя.
        assert fake.seen_prompt is not None
        assert fake.seen_prompt.startswith(CHAT_SYSTEM_PROMPT)
        card = fake.seen_prompt[len(CHAT_SYSTEM_PROMPT) :].lstrip("\n")
        assert fake.seen_prompt == compose_system_prompt(card)

    async def test_dialogue_survives_a_restart(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Оба сообщения читаются обратно в том же порядке.

        Перезапуск контейнера здесь моделируется чтением через отдельную ручку:
        всё, что переживает перезапуск, — это строки таблицы, и именно их
        отдаёт `GET /conversations/{id}`.
        """
        install_chat(FakeChatClient(["ответ модели"]))
        conversation_id = await _new_conversation(client)
        await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        response = await client.get(f"/api/v1/chat/conversations/{conversation_id}")

        assert response.status_code == 200
        body = response.json()
        assert [one["role"] for one in body["messages"]] == [
            MESSAGE_ROLE_USER,
            MESSAGE_ROLE_ASSISTANT,
        ]
        assert body["messages"][0]["content"] == CONTROL_PHRASE
        assert body["messages"][1]["content"] == "ответ модели"
        assert body["title"] == CONTROL_PHRASE
        assert body["llm_backend"] == "fake"

    async def test_turn_into_unknown_conversation_is_404(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Ход в несуществующий разговор — 404, а не поток в никуда."""
        install_chat(FakeChatClient(["ответ"]))

        response = await client.post(
            "/api/v1/chat/conversations/4242/messages", json={"content": "привет"}
        )

        assert response.status_code == 404


@pytest.mark.asyncio
class TestFailures:
    """Отказы: выключенный бэкенд и сбой бэкенда — разные вещи."""

    async def test_no_backend_is_503_and_leaves_no_message(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """503 и ни одной строки: вопрос без ответа в ленте не оседает."""
        install_chat(None)
        conversation_id = await _new_conversation(client)

        response = await client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"content": CONTROL_PHRASE},
        )

        assert response.status_code == 503
        rows = (
            (
                await db_session.execute(
                    select(ChatMessage).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    async def test_backend_failure_lands_as_failed_with_a_machine_code(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """Сбой бэкенда — событие `error` и сообщение со статусом `failed`."""
        install_chat(FakeChatClient(["начало "], fail=True))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        assert [name for name, _ in events] == [SSE_EVENT_DELTA, SSE_EVENT_ERROR]
        assert events[-1][1]["code"] == ERROR_CODE_BACKEND

        answer = (
            (
                await db_session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .where(ChatMessage.role == MESSAGE_ROLE_ASSISTANT)
                )
            )
            .scalars()
            .one()
        )
        assert answer.status == MESSAGE_STATUS_FAILED
        assert answer.error_code == ERROR_CODE_BACKEND
        # Полученное до сбоя не теряется: обрыв на середине оставляет текст.
        assert answer.content == "начало "

    async def test_error_payload_carries_no_content(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """В событии `error` нет ни куска разговора, ни текста исключения."""
        install_chat(FakeChatClient([CONTROL_PHRASE], fail=True))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        payload = str(events[-1][1])
        assert CONTROL_PHRASE not in payload
        assert "upstream said no" not in payload


@pytest.mark.asyncio
class TestSessionAndInterruption:
    """Две вещи, ради которых ход и написан так, а не в одну функцию."""

    async def test_no_db_session_is_open_while_the_model_generates(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Соединение из пула возвращается до того, как начнётся генерация.

        Проверка не косметическая: на двух воркерах ход, держащий сессию все сто
        двадцать секунд, выедает пул, и это тот самый долг из
        `concern-charts-ai-followups.md`.
        """
        open_scopes = 0
        seen_while_streaming: list[int] = []

        @asynccontextmanager
        async def counting_factory() -> AsyncIterator[AsyncSession]:
            nonlocal open_scopes
            open_scopes += 1
            try:
                yield db_session
            finally:
                open_scopes -= 1

        class WatchingClient(FakeChatClient):
            async def stream_turn(
                self,
                *,
                system_prompt: str,
                turns: Sequence[ChatTurn],
                resume: ResumeHint | None = None,
            ) -> AsyncIterator[ChatChunk]:
                seen_while_streaming.append(open_scopes)
                async for chunk in super().stream_turn(
                    system_prompt=system_prompt, turns=turns, resume=resume
                ):
                    yield chunk

        app.dependency_overrides[get_session_factory] = lambda: counting_factory
        app.dependency_overrides[get_chat_llm_client] = lambda: WatchingClient(["ок"])
        conversation_id = await _new_conversation(client)

        await _read_events(
            client, f"/api/v1/chat/conversations/{conversation_id}/messages", "вопрос"
        )

        assert seen_while_streaming == [0]

    async def test_a_dropped_connection_keeps_what_arrived(
        self, db_session: AsyncSession
    ) -> None:
        """
        Закрытая на середине вкладка оставляет `interrupted` с полученным текстом.

        Генератор закрывают снаружи — ровно то, что делает ASGI-сервер при
        обрыве, — и запись должна произойти из `finally`, без единого события в
        уже закрытый поток.
        """
        from app.api.chat import _TurnContext, _sse, _turn_frames
        from app.llm.chat.limits import TurnSlot, TurnSlots

        @asynccontextmanager
        async def factory() -> AsyncIterator[AsyncSession]:
            yield db_session

        conversation = await chat_crud.create_conversation(
            db_session, started_on=date(2026, 8, 30)
        )
        # Строка ответа заводится до генерации (`#116`): она же замок диалога, и
        # именно её `finally` обязан закрыть, когда вкладку закрыли на середине.
        answer = await chat_crud.open_turn(
            db_session, conversation_id=conversation.id, seq=1, model=None
        )
        await db_session.commit()

        fake = FakeChatClient(["первый ", "второй"])
        frames = _turn_frames(
            factory=factory,
            client=fake,
            slot=TurnSlot(TurnSlots(capacity=1)),
            conversation_id=conversation.id,
            context=_TurnContext(
                turns=[ChatTurn(MESSAGE_ROLE_USER, "вопрос")],
                answer_seq=answer.seq,
                system_prompt=CHAT_SYSTEM_PROMPT,
                resume=ResumeHint(session_id=None, cwd=None, context_version=1),
                message_id=answer.id,
            ),
        )
        first = await frames.__anext__()
        assert "первый" in _sse(*first)
        await frames.aclose()

        answer = (
            (
                await db_session.execute(
                    select(ChatMessage).where(
                        ChatMessage.conversation_id == conversation.id
                    )
                )
            )
            .scalars()
            .one()
        )
        assert answer.status == MESSAGE_STATUS_INTERRUPTED
        assert answer.content == "первый "


@pytest.mark.asyncio
class TestTurnSteps:
    """Шаги хода наружу: лента отличает мысль от ответа."""

    async def test_every_step_reaches_the_browser_in_order(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Мысль, границы блоков и причина остановки едут своими событиями."""
        install_chat(ScriptedChatClient(THINKING_TURN))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        assert [name for name, _ in events] == [
            SSE_EVENT_THINKING,
            SSE_EVENT_THINKING,
            SSE_EVENT_STEP_END,
            SSE_EVENT_WRITING,
            SSE_EVENT_DELTA,
            SSE_EVENT_DELTA,
            SSE_EVENT_STEP_END,
            SSE_EVENT_STOP,
            SSE_EVENT_USAGE,
            SSE_EVENT_DONE,
        ]

    async def test_thinking_carries_volume_and_stop_carries_the_reason(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Чем заполнить паузу до первого слова и чем закончить ход.

        Объём мысли — единственная числовая правда о ней, раз слов нет;
        причина остановки отличает обрезанный по потолку ответ от целого.
        """
        install_chat(ScriptedChatClient(THINKING_TURN))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )
        by_name = {name: data for name, data in events}

        assert by_name[SSE_EVENT_THINKING]["thinking_tokens"] == 50
        assert by_name[SSE_EVENT_STOP] == {"reason": "end_turn", "thinking_tokens": 27}
        assert by_name[SSE_EVENT_WRITING] == {"index": 1}

    async def test_tool_step_names_the_tool(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """«Клод сейчас делает вот это» — это имя инструмента, а не догадка."""
        install_chat(
            ScriptedChatClient(
                [
                    ChatChunk.acting(tool_name="Read", index=0),
                    ChatChunk.step_end(index=0),
                    ChatChunk.delta("готово"),
                    ChatChunk.usage(session_id=FAKE_SESSION_ID),
                ]
            )
        )
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        assert (SSE_EVENT_ACTING, {"index": 0, "tool": "Read"}) in events

    async def test_a_step_before_the_failure_keeps_the_stream_open(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        Сказавший «думаю» и умерший бэкенд ломается внутри потока, а не до него.

        Раньше первым кадром хода мог быть только текст или ошибка, и отказ до
        текста становился 502. Кадр шага — тоже ответ бэкенда: человек видит
        «думает», потом `error` в открытой ленте, а строка ответа получает тот
        же машинный код, что и всегда.
        """
        install_chat(ScriptedChatClient([ChatChunk.thinking_step(index=0)], fail=True))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        assert [name for name, _ in events] == [SSE_EVENT_THINKING, SSE_EVENT_ERROR]
        answer = (
            (
                await db_session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .where(ChatMessage.role == MESSAGE_ROLE_ASSISTANT)
                )
            )
            .scalars()
            .one()
        )
        assert answer.status == MESSAGE_STATUS_FAILED
        assert answer.error_code == ERROR_CODE_BACKEND


@pytest.mark.asyncio
class TestThinkingIsNotStored:
    """Граница приватности: мысль доезжает до экрана и никуда больше."""

    async def test_thinking_words_reach_the_browser(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Бэкенд, у которого рассуждение настоящее, доносит его до экрана.

        На подписке поле приходит пустым (CLI подменяет мысль подписью), но
        провод обязан её нести: правило «куда мысли нельзя» должно стоять
        раньше, чем появится текст, а не после.
        """
        install_chat(
            ScriptedChatClient(
                [
                    ChatChunk.thinking_step(index=0, thinking=INNER_SPEECH),
                    ChatChunk.delta("ответ"),
                    ChatChunk.usage(session_id=FAKE_SESSION_ID),
                ]
            )
        )
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )
        thinking = [data for name, data in events if name == SSE_EVENT_THINKING]

        assert thinking == [
            {"index": 0, "thinking": INNER_SPEECH, "thinking_tokens": None}
        ]
        # Мысль не притворяется куском ответа: ключа `text` в кадре нет.
        assert "text" not in thinking[0]

    async def test_thinking_never_lands_in_the_message_row(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        В `chat_messages` уходит ответ, и только он.

        Внутренняя речь модели о дне человека не получает ни колонки, ни срока
        хранения: колонка означала бы «кто-то это читает позже», а у сырого
        рассуждения такого читателя нет.
        """
        install_chat(
            ScriptedChatClient(
                [
                    ChatChunk.thinking_step(index=0, thinking=INNER_SPEECH),
                    ChatChunk.delta("ответ по существу"),
                    ChatChunk.usage(session_id=FAKE_SESSION_ID),
                ]
            )
        )
        conversation_id = await _new_conversation(client)

        await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        rows = (
            (
                await db_session.execute(
                    select(ChatMessage).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
            )
            .scalars()
            .all()
        )
        stored = " ".join(row.content for row in rows)
        assert "ответ по существу" in stored
        assert INNER_SPEECH not in stored

    async def test_thinking_never_lands_in_the_log(
        self,
        client: AsyncClient,
        install_chat: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Лог хода — машинные коды; ни мысли, ни ответа в нём нет."""
        install_chat(
            ScriptedChatClient(
                [
                    ChatChunk.thinking_step(index=0, thinking=INNER_SPEECH),
                    ChatChunk.delta("ответ"),
                    ChatChunk.usage(session_id=FAKE_SESSION_ID),
                ]
            )
        )
        conversation_id = await _new_conversation(client)

        with caplog.at_level(logging.DEBUG):
            await _read_events(
                client,
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                CONTROL_PHRASE,
            )

        assert INNER_SPEECH not in caplog.text


@pytest.mark.asyncio
class TestOldClientKeepsWorking:
    """Клиент, знающий только текст, шагов хода не замечает."""

    async def test_the_legacy_five_events_are_unchanged_by_the_new_ones(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Выбросив незнакомые события, старый разборщик получает прежний поток.

        Именно так он и устроен: неизвестное имя события даёт `null` и молча
        пропускается. Тест держит обещание с той стороны — что после отсева
        останется ровно `delta*`, `usage`, `done` и тот же текст ответа.
        """
        install_chat(ScriptedChatClient(THINKING_TURN))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )
        known = {
            SSE_EVENT_DELTA,
            SSE_EVENT_USAGE,
            SSE_EVENT_DONE,
            SSE_EVENT_ERROR,
            SSE_EVENT_RETRIEVAL,
        }
        legacy = [(name, data) for name, data in events if name in known]

        assert [name for name, _ in legacy] == [
            SSE_EVENT_DELTA,
            SSE_EVENT_DELTA,
            SSE_EVENT_USAGE,
            SSE_EVENT_DONE,
        ]
        assert (
            "".join(data["text"] for name, data in legacy if name == SSE_EVENT_DELTA)
            == "Первый кусок"
        )

    async def test_a_text_only_backend_still_streams_exactly_as_before(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Бэкенд без шагов (API) шлёт ровно три вида событий, как и раньше."""
        install_chat(FakeChatClient(["Пер", "вый ", "кусок"]))
        conversation_id = await _new_conversation(client)

        events = await _read_events(
            client,
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            CONTROL_PHRASE,
        )

        assert [name for name, _ in events] == [
            SSE_EVENT_DELTA,
            SSE_EVENT_DELTA,
            SSE_EVENT_DELTA,
            SSE_EVENT_USAGE,
            SSE_EVENT_DONE,
        ]
