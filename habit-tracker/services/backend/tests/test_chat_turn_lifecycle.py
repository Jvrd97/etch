"""
Жизненный цикл хода: обрыв, замок диалога, потолок процессов, сроки.
"""

# [review:need-review] PHASE-03/116
# summary: the turn lifecycle end to end — the answer row opened as `streaming` before generation, a second POST into a busy dialogue refused with 409 without starting a second CLI, a backend dead before the first frame answered 502 rather than 500, both watchdogs (silence on the first delta, the overall deadline) ending the turn with distinct machine codes, a failed turn leaving the dialogue usable, the reset handle unsticking a turn whose worker died, and the slot ceiling holding at two
import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from fastapi.responses import StreamingResponse
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import ERROR_CODE_BACKEND, _machine_code, post_message
from app.api.deps import SessionFactory, get_chat_llm_client, get_session_factory
from app.core.config import settings
from app.crud import chat as chat_crud
from app.llm.chat.client import ChatChunk, ChatLLMClient
from app.llm.chat.limits import (
    ERROR_FIRST_DELTA_TIMEOUT,
    ERROR_SLOTS_BUSY,
    ERROR_TURN_TIMEOUT,
    SlotsBusyError,
    TurnSlots,
    guard_stream,
    reset_turn_slots,
)
from app.llm.chat.prompt import ChatTurn
from app.llm.cli import terminate_process
from app.llm.client import LLMError
from app.main import app
from app.models.chat import (
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INTERRUPTED,
    MESSAGE_STATUS_STREAMING,
    ChatMessage,
)
from app.schemas.chat import MessageCreate

# Секунды, за которые срабатывает срок в тесте. Не «поспать подольше»: ход
# должен закрыться раньше общего таймаута, и разница между сроками обязана быть
# заметна, оставаясь долями секунды.
FAST_TIMEOUT = 0.05
SLOW_TIMEOUT = 5.0


class BlockingChatClient(ChatLLMClient):
    """
    Транспорт, который отдаёт кусок и замирает, пока тест его не отпустит.

    Ровно то, чего не умеет обычный подставной клиент: ход, который идёт прямо
    сейчас. Без него «второй POST в занятый диалог» проверить нечем — все
    заготовленные куски успевают прийти до второго запроса.
    """

    model: str = "blocking-chat-model"
    backend: str = "fake"

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls = 0
        self.closed = 0

    @property
    def cwd(self) -> str | None:
        return "/tmp/fake-chat-workspace"

    async def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        self.calls += 1
        try:
            yield ChatChunk.delta("первый ")
            await self.release.wait()
            yield ChatChunk.delta("второй")
            yield ChatChunk.usage(output_tokens=2)
        finally:
            # Считает закрытия источника: именно здесь у настоящего CLI стоит
            # `kill`, и вотчдог обязан до этого места добраться.
            self.closed += 1


class SilentChatClient(ChatLLMClient):
    """Транспорт, который не говорит ничего и не заканчивается сам."""

    model: str = "silent-chat-model"
    backend: str = "fake"

    def __init__(self) -> None:
        self.closed = 0

    async def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        try:
            await asyncio.sleep(SLOW_TIMEOUT)
            yield ChatChunk.delta("слишком поздно")
        finally:
            self.closed += 1


class DeadChatClient(ChatLLMClient):
    """Транспорт, падающий до первого куска — убитый снаружи процесс CLI."""

    model: str = "dead-chat-model"
    backend: str = "fake"

    def __init__(self, message: str = "cli_exit: -9") -> None:
        self._message = message
        self.calls = 0

    async def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        self.calls += 1
        raise LLMError(self._message)
        yield ChatChunk.delta("недостижимо")  # pragma: no cover - для типа


class QuickChatClient(ChatLLMClient):
    """Обычный удачный ход в одну строку — им проверяется, что диалог свободен."""

    model: str = "quick-chat-model"
    backend: str = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        self.calls += 1
        yield ChatChunk.delta("готово")
        yield ChatChunk.usage(output_tokens=1)


@pytest.fixture(scope="function")
def install_chat(db_session: AsyncSession) -> Any:
    """
    Подменить фабрику сессий на тестовую и транспорт — на подставной.

    Фабрика отдаёт ту же сессию, что и остальные ручки теста, и не закрывает
    её: ход открывает сессию дважды, и настоящая фабрика на тестовой базе
    открыла бы вторую транзакцию, которая первую не видит.
    """

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    def install(client: ChatLLMClient) -> ChatLLMClient:
        app.dependency_overrides[get_session_factory] = lambda: factory
        app.dependency_overrides[get_chat_llm_client] = lambda: client
        return client

    install.factory = factory  # type: ignore[attr-defined]
    return install


@pytest.fixture(autouse=True)
def fresh_slots() -> AsyncIterator[None]:
    """Свой счётчик слотов на каждый тест: потолок — состояние процесса."""
    reset_turn_slots()
    yield
    reset_turn_slots()


async def _new_conversation(client: AsyncClient) -> int:
    response = await client.post("/api/v1/chat/conversations", json={})
    assert response.status_code == 201
    conversation_id = response.json()["id"]
    assert isinstance(conversation_id, int)
    return conversation_id


async def _drain(client: AsyncClient, url: str, content: str) -> int:
    """Пройти ход целиком и вернуть код ответа."""
    async with client.stream("POST", url, json={"content": content}) as response:
        if response.status_code != 200:
            await response.aread()
            return response.status_code
        async for _line in response.aiter_lines():
            pass
        return 200


async def _answers(db: AsyncSession, conversation_id: int) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.seq)
    )
    return list(result.scalars().all())


@asynccontextmanager
async def _live_turn(
    factory: SessionFactory,
    transport: ChatLLMClient,
    conversation_id: int,
    content: str,
) -> AsyncIterator[StreamingResponse]:
    """
    Ход, который идёт прямо сейчас, — и закрывается вместе с блоком.

    Ручка зовётся напрямую, минуя httpx: его ASGI-транспорт собирает тело
    ответа целиком, прежде чем вернуть управление, и «посмотреть на диалог,
    пока ход не закончился» через него невозможно в принципе.

    К моменту возврата ручки строка ответа уже записана и зафиксирована: первый
    кадр вытянут, значит `_open_turn` позади. Выход из блока закрывает поток —
    это и есть закрытая вкладка.

    Первый кадр забирается здесь же, потому что так делает сервер: ASGI начинает
    тянуть тело сразу. Закрыть ни разу не начатый генератор — значит не запустить
    его `finally`, то есть проверить не то, что происходит на самом деле.
    """
    response = await post_message(
        conversation_id,
        MessageCreate(content=content),
        factory=factory,
        client=transport,
    )
    body: AsyncIterator[Any] = response.body_iterator
    await body.__anext__()
    try:
        yield response
    finally:
        await body.aclose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
class TestDialogueLock:
    """Один ход на диалог: второй POST не поднимает второго процесса."""

    async def test_second_post_into_a_busy_dialogue_is_refused(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """
        Пока ход не закрыт, второй POST получает 409 и хода не начинает.

        Проверяется не только код ответа: `calls` подставного транспорта — это
        и есть «сколько процессов `claude` поднялось».
        """
        fake: BlockingChatClient = install_chat(BlockingChatClient())
        conversation_id = await _new_conversation(client)
        url = f"/api/v1/chat/conversations/{conversation_id}/messages"

        async with _live_turn(
            install_chat.factory, fake, conversation_id, "первый вопрос"
        ):
            second = await client.post(url, json={"content": "второй вопрос"})
            assert second.status_code == 409
            assert fake.calls == 1

    async def test_the_open_turn_is_a_row_in_streaming(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        Незакрытый ход виден строкой со статусом `streaming`, а не флагом.

        Это же состояние переживает перезапуск бэкенда: воркер умер, строка
        осталась, и по ней диалог узнают запертым.
        """
        fake: BlockingChatClient = install_chat(BlockingChatClient())
        conversation_id = await _new_conversation(client)

        async with _live_turn(install_chat.factory, fake, conversation_id, "вопрос"):
            open_turn = await chat_crud.find_open_turn(db_session, conversation_id)
            assert open_turn is not None
            assert open_turn.status == MESSAGE_STATUS_STREAMING

    async def test_reset_unsticks_a_turn_whose_worker_died(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        Ручка сброса переводит `streaming` в `interrupted`, сохраняя текст.

        Ровно случай «бэкенд перезапустили посреди генерации»: строку никто уже
        не закроет, и без сброса диалог заперт навсегда.
        """
        quick: QuickChatClient = install_chat(QuickChatClient())
        conversation = await chat_crud.create_conversation(
            db_session, started_on=date(2026, 8, 30)
        )
        stuck = await chat_crud.open_turn(
            db_session, conversation_id=conversation.id, seq=1
        )
        stuck.content = "успело прийти"
        await db_session.commit()

        url = f"/api/v1/chat/conversations/{conversation.id}/messages"
        assert await _drain(client, url, "вопрос") == 409

        reset = await client.post(f"/api/v1/chat/conversations/{conversation.id}/reset")
        assert reset.status_code == 200
        assert reset.json() == {"reset": 1}

        await db_session.refresh(stuck)
        assert stuck.status == MESSAGE_STATUS_INTERRUPTED
        assert stuck.content == "успело прийти"

        assert await _drain(client, url, "вопрос") == 200
        assert quick.calls == 1

    async def test_reset_of_a_free_dialogue_reports_nothing_to_reset(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Ноль — не ошибка: диалог и так свободен, и об этом надо сказать прямо."""
        install_chat(QuickChatClient())
        conversation_id = await _new_conversation(client)
        response = await client.post(
            f"/api/v1/chat/conversations/{conversation_id}/reset"
        )
        assert response.status_code == 200
        assert response.json() == {"reset": 0}

    async def test_reset_of_a_missing_conversation_is_404(
        self, client: AsyncClient
    ) -> None:
        """Сброс несуществующего диалога — 404, а не тихий ноль."""
        response = await client.post("/api/v1/chat/conversations/999999/reset")
        assert response.status_code == 404


@pytest.mark.asyncio
class TestFailedTurnDoesNotLock:
    """Упавший ход закрывается сам и диалог за собой не запирает."""

    async def test_a_dead_backend_answers_502_and_frees_the_dialogue(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        Процесс, умерший до первого куска: 502, `failed` с машинным кодом,
        и следующий ход в этом же диалоге проходит нормально.
        """
        install_chat(DeadChatClient())
        conversation_id = await _new_conversation(client)
        url = f"/api/v1/chat/conversations/{conversation_id}/messages"

        assert await _drain(client, url, "вопрос") == 502

        messages = await _answers(db_session, conversation_id)
        answer = messages[-1]
        assert answer.status == MESSAGE_STATUS_FAILED
        assert answer.error_code == ERROR_CODE_BACKEND
        # Текст исключения не долетел ни до базы, ни до ответа: только код.
        assert answer.content == ""

        quick: QuickChatClient = install_chat(QuickChatClient())
        assert await _drain(client, url, "второй вопрос") == 200
        assert quick.calls == 1
        assert await chat_crud.find_open_turn(db_session, conversation_id) is None

    async def test_the_error_text_never_becomes_the_error_code(self) -> None:
        """
        Код отказа берётся из белого списка, а не из текста исключения.

        Текст `LLMError` может нести кусок промпта — путь «положим `str(exc)` в
        `error_code`» ровно тем и опасен.
        """
        assert _machine_code(LLMError("cli_exit: 1")) == ERROR_CODE_BACKEND
        assert _machine_code(LLMError("дневник: сегодня")) == ERROR_CODE_BACKEND
        assert _machine_code(LLMError(ERROR_TURN_TIMEOUT)) == ERROR_TURN_TIMEOUT
        assert (
            _machine_code(LLMError(ERROR_FIRST_DELTA_TIMEOUT))
            == ERROR_FIRST_DELTA_TIMEOUT
        )


@pytest.mark.asyncio
class TestWatchdogs:
    """Два срока: молчание на старте и общий потолок хода."""

    async def test_silence_before_the_first_delta_ends_the_turn_early(self) -> None:
        """
        Ход, не сказавший ни слова, закрывается коротким сроком, а не общим.

        Проверяется и код (`first_delta_timeout`, не `turn_timeout`), и то, что
        источник закрыт: именно его `finally` убивает процесс CLI.
        """
        silent = SilentChatClient()
        guarded = guard_stream(
            silent.stream_turn(system_prompt="prompt", turns=[]),
            first_delta_timeout=FAST_TIMEOUT,
            total_timeout=SLOW_TIMEOUT,
        )
        with pytest.raises(LLMError) as failure:
            async for _chunk in guarded:
                pass
        assert str(failure.value) == ERROR_FIRST_DELTA_TIMEOUT
        assert silent.closed == 1

    async def test_the_overall_deadline_ends_a_turn_that_did_speak(self) -> None:
        """
        Заговоривший ход живёт по общему сроку, и код у него другой.

        Первый `delta` снимает короткий срок — иначе длинный ответ, у которого
        между абзацами пауза, убивался бы вотчдогом старта.
        """
        blocking = BlockingChatClient()
        guarded = guard_stream(
            blocking.stream_turn(system_prompt="prompt", turns=[]),
            first_delta_timeout=FAST_TIMEOUT,
            total_timeout=FAST_TIMEOUT * 2,
        )
        pieces: list[str] = []
        with pytest.raises(LLMError) as failure:
            async for chunk in guarded:
                pieces.append(chunk.text)
        assert pieces == ["первый "]
        assert str(failure.value) == ERROR_TURN_TIMEOUT
        assert blocking.closed == 1

    async def test_a_turn_within_its_deadlines_passes_through_untouched(self) -> None:
        """Вотчдог не вмешивается в нормальный ход: те же куски, тот же порядок."""
        quick = QuickChatClient()
        guarded = guard_stream(
            quick.stream_turn(system_prompt="prompt", turns=[]),
            first_delta_timeout=SLOW_TIMEOUT,
            total_timeout=SLOW_TIMEOUT,
        )
        kinds = [chunk.kind async for chunk in guarded]
        assert kinds == ["delta", "usage"]

    async def test_a_silent_turn_is_recorded_with_the_watchdog_code(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """Молчащий ход доезжает до базы как `failed` с кодом вотчдога."""
        install_chat(SilentChatClient())
        settings_backup = settings.CHAT_FIRST_DELTA_TIMEOUT_SECONDS
        try:
            # `ge=1` в настройке — про прод, а не про тест: короче секунды там
            # незачем. Здесь срок ставится напрямую, минуя валидатор.
            object.__setattr__(settings, "CHAT_FIRST_DELTA_TIMEOUT_SECONDS", 0)
            conversation_id = await _new_conversation(client)
            url = f"/api/v1/chat/conversations/{conversation_id}/messages"
            assert await _drain(client, url, "вопрос") == 502
        finally:
            object.__setattr__(
                settings, "CHAT_FIRST_DELTA_TIMEOUT_SECONDS", settings_backup
            )

        answer = (await _answers(db_session, conversation_id))[-1]
        assert answer.status == MESSAGE_STATUS_FAILED
        assert answer.error_code == ERROR_FIRST_DELTA_TIMEOUT


@pytest.mark.asyncio
class TestSlotCeiling:
    """Потолок одновременных процессов: два, а не по одному на диалог."""

    async def test_the_third_turn_is_refused_instead_of_starting_a_third_process(
        self, client: AsyncClient, install_chat: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Три диалога, в которые пишут разом, дают два хода и один внятный отказ.

        Ожидание слота обнулено намеренно: с ним третий ход честно ждёт, и
        проверять пришлось бы длину очереди, а не потолок.
        """
        monkeypatch.setattr(settings, "CHAT_SLOT_WAIT_SECONDS", 0)
        slots = reset_turn_slots(2)
        fake: BlockingChatClient = install_chat(BlockingChatClient())
        first_id = await _new_conversation(client)
        second_id = await _new_conversation(client)
        third_id = await _new_conversation(client)

        async with _live_turn(install_chat.factory, fake, first_id, "раз"):
            async with _live_turn(install_chat.factory, fake, second_id, "два"):
                assert slots.in_flight == 2
                third = await client.post(
                    f"/api/v1/chat/conversations/{third_id}/messages",
                    json={"content": "три"},
                )
                assert third.status_code == 429
                assert third.json()["detail"] == ERROR_SLOTS_BUSY
                assert fake.calls == 2

    async def test_a_slot_is_returned_by_a_turn_that_failed(
        self, client: AsyncClient, install_chat: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Упавший ход отдаёт слот, иначе потолок кончается на первой же поломке.

        Потолок в один слот делает утечку видимой сразу: не вернув его, второй
        ход получил бы 429 вместо ответа.
        """
        monkeypatch.setattr(settings, "CHAT_SLOT_WAIT_SECONDS", 0)
        slots = reset_turn_slots(1)
        install_chat(DeadChatClient())
        conversation_id = await _new_conversation(client)
        url = f"/api/v1/chat/conversations/{conversation_id}/messages"

        assert await _drain(client, url, "вопрос") == 502
        assert slots.in_flight == 0

        install_chat(QuickChatClient())
        assert await _drain(client, url, "второй вопрос") == 200
        assert slots.in_flight == 0

    async def test_a_refused_turn_leaves_no_question_in_the_dialogue(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        install_chat: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Отказ по потолку не записывает реплику: слот берётся до записи.

        Иначе разговор пополняется вопросами, на которые никто не собирался
        отвечать, — тот же довод, по которому 503 проверяется до записи.
        """
        monkeypatch.setattr(settings, "CHAT_SLOT_WAIT_SECONDS", 0)
        reset_turn_slots(1)
        fake: BlockingChatClient = install_chat(BlockingChatClient())
        busy_id = await _new_conversation(client)
        free_id = await _new_conversation(client)

        async with _live_turn(install_chat.factory, fake, busy_id, "занимаю слот"):
            refused = await client.post(
                f"/api/v1/chat/conversations/{free_id}/messages",
                json={"content": "мимо"},
            )
            assert refused.status_code == 429
            assert await _answers(db_session, free_id) == []

    async def test_slots_are_counted_not_guessed(self) -> None:
        """Счётчик отдаёт слоты по одному и отказывает, когда их нет."""
        slots = TurnSlots(1)
        await slots.acquire(wait_seconds=0)
        assert slots.in_flight == 1
        with pytest.raises(SlotsBusyError):
            await slots.acquire(wait_seconds=0)
        slots.release()
        assert slots.in_flight == 0
        await slots.acquire(wait_seconds=0)
        slots.release()


@pytest.mark.asyncio
class TestProcessTermination:
    """`kill` + `wait` на настоящем процессе, а не на подставном объекте."""

    async def test_a_live_process_is_killed_and_reaped(self) -> None:
        """Убитый процесс дожидается своего кода возврата, а не остаётся зомби."""
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "60",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await terminate_process(process)
        assert process.returncode is not None

    async def test_terminating_an_exited_process_is_a_no_op(self) -> None:
        """Уже завершившийся процесс не убивают повторно."""
        process = await asyncio.create_subprocess_exec(
            "true",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
        code = process.returncode
        await terminate_process(process)
        assert process.returncode == code


@pytest.mark.asyncio
class TestInterruptedTurn:
    """Обрыв клиента: частичный текст сохраняется, статус говорит правду."""

    async def test_a_dropped_connection_leaves_partial_text_and_frees_the_dialogue(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        Вкладка, закрытая на середине, оставляет `interrupted` с полученным
        текстом, а диалог после этого снова принимает сообщения.
        """
        fake: BlockingChatClient = install_chat(BlockingChatClient())
        conversation_id = await _new_conversation(client)

        async with _live_turn(install_chat.factory, fake, conversation_id, "вопрос"):
            pass

        answer = (await _answers(db_session, conversation_id))[-1]
        assert answer.status == MESSAGE_STATUS_INTERRUPTED
        assert answer.content == "первый "
        assert answer.error_code is None
        assert await chat_crud.find_open_turn(db_session, conversation_id) is None
        # Источник закрыт — у настоящего CLI ровно здесь и стоит `kill`.
        assert fake.closed == 1

        quick: QuickChatClient = install_chat(QuickChatClient())
        url = f"/api/v1/chat/conversations/{conversation_id}/messages"
        assert await _drain(client, url, "второй вопрос") == 200
        assert quick.calls == 1
