"""
Возобновление сессии CLI и отказоустойчивый реплей.
"""

# [review:need-review] PHASE-03/112
# summary: the strategy of one turn under every way it can degrade — no session, deleted session file, moved cwd, bumped context version, API backend — plus the replay ordered by `seq` and not by `created_at`, the ten-turn dialogue whose prompt never grows, and the resume flag the conversation header reads
import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_chat_llm_client, get_session_factory
from app.core.daytime import now_utc
from app.llm.chat.client import (
    CHUNK_USAGE,
    BACKEND_API,
    ChatChunk,
    ChatLLMClient,
    CliChatClient,
)
from app.llm.chat.prompt import (
    CHAT_CONTEXT_VERSION,
    ChatTurn,
    render_resume,
    render_transcript,
    resume_tail,
)
from app.llm.chat.session import (
    MODE_REPLAY,
    MODE_RESUME,
    ResumeHint,
    can_resume,
    choose_strategy,
    project_slug,
    session_file,
)
from app.main import app
from app.models.chat import (
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_SYSTEM_NOTE,
    MESSAGE_ROLE_USER,
    ChatConversation,
    ChatMessage,
)

SYSTEM_PROMPT = "системный промпт чата"
# Число, которое человек просит запомнить первым сообщением. Приёмка тикета
# держится на нём: чем бы ни кончилась сессия CLI, третий ход обязан его знать.
ANCHOR = "4271"
SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_SESSION_ID = "99999999-8888-7777-6666-555555555555"
WORKSPACE = "/data/claude-chat/workspace"


def _make_session_file(config_dir: Path, cwd: str, session_id: str) -> Path:
    """Положить файл сессии туда, где его ищет CLI."""
    path = session_file(str(config_dir), cwd, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path


def _hint(
    session_id: str | None = SESSION_ID,
    cwd: str | None = WORKSPACE,
    context_version: int = CHAT_CONTEXT_VERSION,
) -> ResumeHint:
    return ResumeHint(session_id=session_id, cwd=cwd, context_version=context_version)


# --- слаг и путь к файлу сессии --------------------------------------------


class TestSessionFile:
    """Где CLI держит сессию. Путь считается здесь, а кладёт файл чужой процесс."""

    def test_slug_replaces_every_unsafe_character_with_a_dash(self) -> None:
        """Слеши, точки и подчёркивания — дефисы; дефис исходного пути остаётся."""
        assert project_slug("/data/claude-chat/workspace") == (
            "-data-claude-chat-workspace"
        )
        assert project_slug("/tmp/a_b.c") == "-tmp-a-b-c"

    def test_session_lives_under_projects_by_cwd_and_id(self, tmp_path: Path) -> None:
        """`<config>/projects/<слаг-cwd>/<session_id>.jsonl` — и никак иначе."""
        path = session_file(str(tmp_path), WORKSPACE, SESSION_ID)

        assert path == (
            tmp_path
            / "projects"
            / "-data-claude-chat-workspace"
            / f"{SESSION_ID}.jsonl"
        )


# --- выбор стратегии --------------------------------------------------------


class TestStrategy:
    """Четыре условия продолжения, и каждое ломается отдельно."""

    def test_a_live_session_in_the_same_place_resumes(self, tmp_path: Path) -> None:
        """Всё совпало и файл на месте — второй ход продолжает первый."""
        _make_session_file(tmp_path, WORKSPACE, SESSION_ID)

        strategy = choose_strategy(
            hint=_hint(),
            cwd=WORKSPACE,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )

        assert strategy.mode == MODE_RESUME
        assert strategy.resumes is True
        assert strategy.session_id == SESSION_ID

    def test_first_turn_opens_a_new_session_id(self, tmp_path: Path) -> None:
        """Продолжать нечего — реплей, и id сессии придумывается до запуска."""
        strategy = choose_strategy(
            hint=_hint(session_id=None),
            cwd=WORKSPACE,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )

        assert strategy.mode == MODE_REPLAY
        assert strategy.session_id
        assert strategy.session_id != SESSION_ID

    def test_deleted_session_file_falls_back_to_replay(self, tmp_path: Path) -> None:
        """Файл сессии удалили руками — ход дороже, но не сломан."""
        path = _make_session_file(tmp_path, WORKSPACE, SESSION_ID)
        assert can_resume(
            hint=_hint(),
            cwd=WORKSPACE,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )

        path.unlink()

        assert not can_resume(
            hint=_hint(),
            cwd=WORKSPACE,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )

    def test_a_moved_working_directory_falls_back_to_replay(
        self, tmp_path: Path
    ) -> None:
        """cwd сменился — файл сессии лежит под другим слагом, и его не найти."""
        _make_session_file(tmp_path, WORKSPACE, SESSION_ID)

        assert not can_resume(
            hint=_hint(cwd="/data/claude-chat/other"),
            cwd=WORKSPACE,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )

    def test_a_bumped_context_version_falls_back_to_replay(
        self, tmp_path: Path
    ) -> None:
        """Системный промпт переписали — сессию под прежним продолжать нельзя."""
        _make_session_file(tmp_path, WORKSPACE, SESSION_ID)

        assert not can_resume(
            hint=_hint(context_version=CHAT_CONTEXT_VERSION - 1),
            cwd=WORKSPACE,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )

    def test_a_backend_without_a_working_directory_never_resumes(
        self, tmp_path: Path
    ) -> None:
        """У API-бэкенда каталога нет, значит и сессии нет. Это не ошибка."""
        _make_session_file(tmp_path, WORKSPACE, SESSION_ID)

        assert not can_resume(
            hint=_hint(),
            cwd=None,
            config_dir=str(tmp_path),
            context_version=CHAT_CONTEXT_VERSION,
        )


# --- что уходит в промпт ----------------------------------------------------


class TestResumePrompt:
    """Продолжение платит только за новую реплику, реплей — за весь разговор."""

    def test_resume_sends_only_the_turns_after_the_last_answer(self) -> None:
        """Сессия помнит всё до своей последней реплики; дважды это не шлётся."""
        turns = [
            ChatTurn(MESSAGE_ROLE_USER, f"запомни: {ANCHOR}"),
            ChatTurn(MESSAGE_ROLE_ASSISTANT, "запомнил"),
            ChatTurn(MESSAGE_ROLE_USER, "какое число?"),
        ]

        assert list(resume_tail(turns)) == [turns[2]]
        assert render_resume(turns) == "какое число?"

    def test_a_note_between_turns_is_not_lost_on_resume(self) -> None:
        """Между ходами легла заметка сервера — она едет вместе с репликой."""
        turns = [
            ChatTurn(MESSAGE_ROLE_USER, "первый"),
            ChatTurn(MESSAGE_ROLE_ASSISTANT, "ответ"),
            ChatTurn(MESSAGE_ROLE_SYSTEM_NOTE, "прошлый ход оборвался"),
            ChatTurn(MESSAGE_ROLE_USER, "второй"),
        ]

        text = render_resume(turns)

        assert "прошлый ход оборвался" in text
        assert "Человек: второй" in text
        assert "первый" not in text

    def test_a_dialogue_without_an_answer_yet_replays_whole(self) -> None:
        """Модель ещё не отвечала — резать нечего, едет весь разговор."""
        turns = [ChatTurn(MESSAGE_ROLE_USER, "первый")]

        assert list(resume_tail(turns)) == turns

    def test_replay_carries_the_anchor_the_lost_session_knew(self) -> None:
        """Реплей несёт то самое число: источник истины — таблица, не файл."""
        turns = [
            ChatTurn(MESSAGE_ROLE_USER, f"запомни: {ANCHOR}"),
            ChatTurn(MESSAGE_ROLE_ASSISTANT, "запомнил"),
            ChatTurn(MESSAGE_ROLE_USER, "какое число?"),
        ]

        assert ANCHOR in render_transcript(turns)


# --- подставной процесс CLI -------------------------------------------------


class FakeStdin:
    def __init__(self) -> None:
        self.written = b""

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class FakeProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(lines)
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


class RecordingExec:
    """Замена `create_subprocess_exec`, помнящая каждый запуск целиком."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self.runs: list[tuple[str, ...]] = []
        self.prompts: list[str] = []
        self._processes: list[FakeProcess] = []

    async def __call__(self, *args: str, **kwargs: Any) -> FakeProcess:
        self.runs.append(args)
        process = FakeProcess(list(self._lines))
        self._processes.append(process)
        return process

    def flush_prompts(self) -> None:
        """Промпты становятся видны только после того, как ход дочитан."""
        self.prompts = [one.stdin.written.decode() for one in self._processes]


def _result_line(session_id: str, cache_read: int) -> bytes:
    return (
        b'{"type":"result","session_id":"' + session_id.encode() + b'","usage":'
        b'{"input_tokens":40,"cache_creation_input_tokens":0,'
        b'"cache_read_input_tokens":' + str(cache_read).encode() + b","
        b'"output_tokens":9}}\n'
    )


async def _run(
    client: CliChatClient, turns: Sequence[ChatTurn], resume: ResumeHint | None
) -> list[ChatChunk]:
    return [
        chunk
        async for chunk in client.stream_turn(
            system_prompt=SYSTEM_PROMPT, turns=turns, resume=resume
        )
    ]


@pytest.mark.asyncio
class TestCliTurn:
    """Что именно уходит в процесс на первом ходу и на последующих."""

    async def test_first_turn_names_the_session_it_opens(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`--session-id` с нашим uuid: id известен до того, как процесс ответил."""
        runner = RecordingExec([_result_line(SESSION_ID, 0)])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", runner)
        workspace = str(tmp_path / "workspace")
        client = CliChatClient(config_dir=str(tmp_path / "cfg"), cwd=workspace)

        await _run(client, [ChatTurn(MESSAGE_ROLE_USER, f"запомни: {ANCHOR}")], None)

        argv = runner.runs[0]
        assert "--session-id" in argv
        assert "--resume" not in argv

    async def test_second_turn_resumes_and_sends_only_the_new_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Сессия жива — уходит `--resume` и одна новая реплика, а не весь разговор."""
        runner = RecordingExec([_result_line(SESSION_ID, 21_685)])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", runner)
        config_dir = tmp_path / "cfg"
        workspace = str(tmp_path / "workspace")
        _make_session_file(config_dir, workspace, SESSION_ID)
        client = CliChatClient(config_dir=str(config_dir), cwd=workspace)

        turns = [
            ChatTurn(MESSAGE_ROLE_USER, f"запомни: {ANCHOR}"),
            ChatTurn(MESSAGE_ROLE_ASSISTANT, "запомнил"),
            ChatTurn(MESSAGE_ROLE_USER, "какое число?"),
        ]
        await _run(client, turns, _hint(cwd=workspace))
        runner.flush_prompts()

        argv = runner.runs[0]
        assert argv[argv.index("--resume") + 1] == SESSION_ID
        assert runner.prompts[0] == "какое число?"

    async def test_a_deleted_session_file_replays_the_whole_dialogue(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Файла нет — в промпт уходит вся история, и число в ней есть."""
        runner = RecordingExec([_result_line(OTHER_SESSION_ID, 0)])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", runner)
        workspace = str(tmp_path / "workspace")
        client = CliChatClient(config_dir=str(tmp_path / "cfg"), cwd=workspace)

        turns = [
            ChatTurn(MESSAGE_ROLE_USER, f"запомни: {ANCHOR}"),
            ChatTurn(MESSAGE_ROLE_ASSISTANT, "запомнил"),
            ChatTurn(MESSAGE_ROLE_USER, "какое число?"),
        ]
        await _run(client, turns, _hint(cwd=workspace))
        runner.flush_prompts()

        argv = runner.runs[0]
        assert "--resume" not in argv
        assert ANCHOR in runner.prompts[0]

    async def test_a_result_without_a_session_id_still_names_the_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLI промолчал — в таблицу уходит тот id, под которым ход и запускали."""
        runner = RecordingExec([b'{"type":"result","usage":{"input_tokens":40}}\n'])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", runner)
        workspace = str(tmp_path / "workspace")
        client = CliChatClient(config_dir=str(tmp_path / "cfg"), cwd=workspace)

        chunks = await _run(client, [ChatTurn(MESSAGE_ROLE_USER, "привет")], None)

        usage = [one for one in chunks if one.kind == CHUNK_USAGE]
        argv = runner.runs[0]
        opened = argv[argv.index("--session-id") + 1]
        assert usage[0].session_id == opened

    async def test_ten_turns_never_resend_the_whole_dialogue(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        Приёмка «resume не откатывается на реплей молча».

        Десять ходов подряд при живой сессии: промпт каждого — одна реплика, а не
        сумма всех прошлых. Ровно это и есть разница между продолжением и
        пересборкой, и она видна размером того, что ушло в процесс.
        """
        runner = RecordingExec([_result_line(SESSION_ID, 21_685)])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", runner)
        config_dir = tmp_path / "cfg"
        workspace = str(tmp_path / "workspace")
        _make_session_file(config_dir, workspace, SESSION_ID)
        client = CliChatClient(config_dir=str(config_dir), cwd=workspace)

        turns: list[ChatTurn] = []
        for index in range(10):
            turns.append(ChatTurn(MESSAGE_ROLE_USER, f"вопрос {index}"))
            await _run(client, turns, _hint(cwd=workspace))
            turns.append(ChatTurn(MESSAGE_ROLE_ASSISTANT, f"ответ {index}"))
        runner.flush_prompts()

        assert len(runner.prompts) == 10
        assert runner.prompts == [f"вопрос {index}" for index in range(10)]
        # Ни один ход не унёс в промпт сумму всех предыдущих.
        assert all(
            len(prompt) < len(render_transcript(turns)) for prompt in runner.prompts
        )


# --- ход через ручку --------------------------------------------------------


class ResumeSpyClient(ChatLLMClient):
    """Транспорт, который только записывает, с какой подсказкой его позвали."""

    model: str = "fake-chat-model"
    backend: str = "fake"

    def __init__(self, *, cwd: str | None, session_id: str | None) -> None:
        self._cwd = cwd
        self._session_id = session_id
        self.hints: list[ResumeHint | None] = []
        self.prompts: list[str] = []

    @property
    def cwd(self) -> str | None:
        return self._cwd

    def resumes(self, hint: ResumeHint | None) -> bool:
        return hint is not None and bool(hint.session_id)

    async def stream_turn(
        self,
        *,
        system_prompt: str,
        turns: Sequence[ChatTurn],
        resume: ResumeHint | None = None,
    ) -> AsyncIterator[ChatChunk]:
        self.hints.append(resume)
        self.prompts.append(render_transcript(turns))
        yield ChatChunk.delta("ответ")
        yield ChatChunk.usage(
            session_id=self._session_id,
            input_tokens=40,
            output_tokens=9,
            cache_read_tokens=21_685 if resume and resume.session_id else 0,
        )


@pytest.fixture(scope="function")
def install_chat(db_session: AsyncSession) -> Any:
    """Та же подмена фабрики и транспорта, что и в тестах потока."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    def install(client: ChatLLMClient | None) -> ChatLLMClient | None:
        app.dependency_overrides[get_session_factory] = lambda: factory
        app.dependency_overrides[get_chat_llm_client] = lambda: client
        return client

    return install


async def _turn(client: AsyncClient, conversation_id: int, content: str) -> None:
    """Прогнать один ход и дочитать поток до конца."""
    url = f"/api/v1/chat/conversations/{conversation_id}/messages"
    async with client.stream("POST", url, json={"content": content}) as response:
        assert response.status_code == 200
        async for _ in response.aiter_lines():
            pass


async def _new_conversation(client: AsyncClient) -> int:
    response = await client.post("/api/v1/chat/conversations", json={})
    assert response.status_code == 201
    conversation_id = response.json()["id"]
    assert isinstance(conversation_id, int)
    return conversation_id


@pytest.mark.asyncio
class TestTurnRecordsTheSession:
    """Подсказка о сессии пишется ходом и читается следующим."""

    async def test_the_first_turn_stores_session_cwd_and_version(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """После хода в таблице есть чем продолжить разговор."""
        transport = install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        assert isinstance(transport, ResumeSpyClient)
        conversation_id = await _new_conversation(client)

        await _turn(client, conversation_id, f"запомни: {ANCHOR}")

        row = await db_session.get(ChatConversation, conversation_id)
        assert row is not None
        await db_session.refresh(row)
        assert row.cli_session_id == SESSION_ID
        assert row.cli_cwd == WORKSPACE
        assert row.context_version == CHAT_CONTEXT_VERSION
        assert transport.hints[0] is not None
        assert transport.hints[0].session_id is None

    async def test_the_second_turn_gets_the_hint_of_the_first(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Второй ход приходит в транспорт уже с id сессии — вот и вся оптимизация."""
        transport = install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        assert isinstance(transport, ResumeSpyClient)
        conversation_id = await _new_conversation(client)

        await _turn(client, conversation_id, f"запомни: {ANCHOR}")
        await _turn(client, conversation_id, "какое число?")

        second = transport.hints[1]
        assert second is not None
        assert second.session_id == SESSION_ID
        assert second.cwd == WORKSPACE

    async def test_the_second_turn_reads_cache_and_is_not_slower(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """Обе цифры приёмки лежат в `chat_messages`, а не в логе."""
        install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        conversation_id = await _new_conversation(client)

        await _turn(client, conversation_id, f"запомни: {ANCHOR}")
        await _turn(client, conversation_id, "какое число?")

        rows = (
            (
                await db_session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .where(ChatMessage.role == MESSAGE_ROLE_ASSISTANT)
                    .order_by(ChatMessage.seq)
                )
            )
            .scalars()
            .all()
        )

        assert [row.cache_read_tokens for row in rows] == [0, 21_685]
        assert rows[1].latency_ms is not None

    async def test_an_api_backend_leaves_the_session_null(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """Пять ходов на API-бэкенде работают, и `cli_session_id` остаётся пустым."""
        transport = install_chat(ResumeSpyClient(cwd=None, session_id=None))
        assert isinstance(transport, ResumeSpyClient)
        transport.backend = BACKEND_API
        conversation_id = await _new_conversation(client)

        for index in range(5):
            await _turn(client, conversation_id, f"вопрос {index}")

        row = await db_session.get(ChatConversation, conversation_id)
        assert row is not None
        await db_session.refresh(row)
        assert row.cli_session_id is None
        assert row.cli_cwd is None
        assert row.llm_backend == BACKEND_API
        assert len(transport.prompts) == 5

    async def test_a_bumped_context_version_clears_the_stored_session(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """
        Приёмка «версия сменилась — id обнулён, следующий ход отвечает верно».

        Версия разговора отодвигается назад руками — это и есть то, что делает
        правка `CHAT_SYSTEM_PROMPT` со всеми уже лежащими разговорами.
        """
        transport = install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        assert isinstance(transport, ResumeSpyClient)
        conversation_id = await _new_conversation(client)
        await _turn(client, conversation_id, f"запомни: {ANCHOR}")

        row = await db_session.get(ChatConversation, conversation_id)
        assert row is not None
        row.context_version = CHAT_CONTEXT_VERSION - 1
        await db_session.commit()

        await _turn(client, conversation_id, "какое число?")

        # Подсказка второго хода пуста — сессию под прежним промптом не продолжают.
        second = transport.hints[1]
        assert second is not None
        assert second.session_id is None
        # А разговор от этого не пострадал: реплей несёт то самое число.
        assert ANCHOR in transport.prompts[1]

    async def test_a_moved_cwd_keeps_the_dialogue_working(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Разговор вчерашнего каталога отвечает верно и без ошибки."""
        transport = install_chat(
            ResumeSpyClient(cwd="/data/claude-chat/new", session_id=SESSION_ID)
        )
        assert isinstance(transport, ResumeSpyClient)
        conversation_id = await _new_conversation(client)
        await _turn(client, conversation_id, f"запомни: {ANCHOR}")
        await _turn(client, conversation_id, "какое число?")

        detail = await client.get(f"/api/v1/chat/conversations/{conversation_id}")

        assert detail.status_code == 200
        assert ANCHOR in transport.prompts[1]


@pytest.mark.asyncio
class TestReplayOrder:
    """Порядок реплея несёт `seq`, а не время записи."""

    async def test_two_messages_of_one_second_replay_by_seq(
        self, client: AsyncClient, db_session: AsyncSession, install_chat: Any
    ) -> None:
        """Одинаковый `created_at` не имеет права перевернуть разговор."""
        transport = install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        assert isinstance(transport, ResumeSpyClient)
        conversation_id = await _new_conversation(client)

        stamp = now_utc()
        for seq, (role, text) in enumerate(
            [
                (MESSAGE_ROLE_USER, f"запомни: {ANCHOR}"),
                (MESSAGE_ROLE_ASSISTANT, "запомнил"),
            ],
            start=1,
        ):
            db_session.add(
                ChatMessage(
                    conversation_id=conversation_id,
                    seq=seq,
                    role=role,
                    content=text,
                    # Вторая строка записана раньше первой: порядок по времени
                    # дал бы «Ты: запомнил» перед вопросом.
                    created_at=stamp - timedelta(seconds=seq),
                )
            )
        await db_session.commit()

        await _turn(client, conversation_id, "какое число?")

        assert transport.prompts[0] == (
            f"Человек: запомни: {ANCHOR}\n\nТы: запомнил\n\nЧеловек: какое число?"
        )


@pytest.mark.asyncio
class TestResumeFlagInTheHeader:
    """Признак «продолжение сессии» против «полного пересбора» отдаётся наружу."""

    async def test_a_fresh_conversation_is_not_resumable(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Разговора ещё не было — следующий ход соберёт его целиком."""
        install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        conversation_id = await _new_conversation(client)

        response = await client.get(f"/api/v1/chat/conversations/{conversation_id}")

        assert response.status_code == 200
        assert response.json()["resume_ready"] is False

    async def test_after_a_turn_the_next_one_continues_the_session(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Ход прошёл, сессия записана — шапка обязана это показать."""
        install_chat(ResumeSpyClient(cwd=WORKSPACE, session_id=SESSION_ID))
        conversation_id = await _new_conversation(client)
        await _turn(client, conversation_id, f"запомни: {ANCHOR}")

        response = await client.get(f"/api/v1/chat/conversations/{conversation_id}")

        assert response.json()["resume_ready"] is True

    async def test_a_disabled_chat_answers_false_rather_than_500(
        self, client: AsyncClient, install_chat: Any
    ) -> None:
        """Бэкенда нет — читать разговор всё ещё можно, продолжать нечего."""
        install_chat(None)
        conversation_id = await _new_conversation(client)

        response = await client.get(f"/api/v1/chat/conversations/{conversation_id}")

        assert response.status_code == 200
        assert response.json()["resume_ready"] is False
