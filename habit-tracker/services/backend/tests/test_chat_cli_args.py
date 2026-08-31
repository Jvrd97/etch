"""
Изоляция хода CLI от личной конфигурации хоста и разбор его потока.
"""

# [review:need-review] PHASE-03/111
# summary: the isolation flag set is asserted whole (a turn that loses one of them costs tens of thousands of prefix tokens and leaks the host's personal config), CLAUDE_CONFIG_DIR and the fixed cwd reach the process, and the stream-json parser is checked on deltas, on the final result and on lines it must ignore rather than crash on
import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.llm.chat.client import (
    CHUNK_DELTA,
    CHUNK_USAGE,
    CLAUDE_CONFIG_DIR_ENV,
    ISOLATION_ARGS,
    STREAM_ARGS,
    ChatChunk,
    CliChatClient,
    parse_stream_line,
)
from app.llm.chat.prompt import ChatTurn, render_transcript
from app.llm.chat.session import MODE_REPLAY, TurnStrategy
from app.llm.client import LLMError

SYSTEM_PROMPT = "системный промпт чата"
# Стратегия первого хода: разговора в сессии ещё нет, значит реплей.
FRESH = TurnStrategy(mode=MODE_REPLAY, session_id="fresh-uuid")
SECRET = "якорь-77 личная фраза из дневника"


def _delta_line(text: str) -> bytes:
    return (
        b'{"type":"stream_event","event":{"type":"content_block_delta",'
        b'"delta":{"type":"text_delta","text":"' + text.encode() + b'"}}}\n'
    )


RESULT_LINE = (
    b'{"type":"result","session_id":"abc-123","usage":'
    b'{"input_tokens":200,"cache_creation_input_tokens":82,'
    b'"cache_read_input_tokens":0,"output_tokens":17}}\n'
)


class FakeStdin:
    """Приёмник промпта: запоминает записанное, ничего никуда не шлёт."""

    def __init__(self) -> None:
        self.written = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeStdout:
    """Выдаёт заготовленные строки, затем пустую — как закрытый поток."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class FakeProcess:
    """Подставной процесс CLI с заготовленным stdout и кодом выхода."""

    def __init__(self, lines: list[bytes], returncode: int = 0) -> None:
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(lines)
        self._returncode = returncode
        self.returncode: int | None = None
        self.killed = False

    async def wait(self) -> int:
        self.returncode = self._returncode
        return self._returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeExec:
    """Замена asyncio.create_subprocess_exec, запоминающая argv, cwd и env."""

    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.argv: tuple[str, ...] = ()
        self.kwargs: dict[str, Any] = {}

    async def __call__(self, *args: str, **kwargs: Any) -> FakeProcess:
        self.argv = args
        self.kwargs = kwargs
        return self.process


class TestIsolationArgs:
    """Набор флагов проверяется целиком: выпавший флаг — это принятый срез, который не работает."""

    def test_every_isolation_flag_is_present(self, tmp_path: Path) -> None:
        """`--tools ""` и `--setting-sources ""` — оба, вместе со своими значениями."""
        argv = CliChatClient(cwd=str(tmp_path)).build_argv(SYSTEM_PROMPT, FRESH)

        assert argv[0] == "claude"
        assert "-p" in argv
        for index in range(0, len(ISOLATION_ARGS), 2):
            flag, value = ISOLATION_ARGS[index], ISOLATION_ARGS[index + 1]
            assert flag in argv
            assert argv[argv.index(flag) + 1] == value

    def test_isolation_set_is_the_one_the_measurement_was_made_with(self) -> None:
        """Состав набора зафиксирован: замер 282 против 52 555 токенов сделан на нём."""
        assert ISOLATION_ARGS == ("--tools", "", "--setting-sources", "")

    def test_stream_flags_are_present(self, tmp_path: Path) -> None:
        """Поток кусками требует stream-json вместе с частичными сообщениями."""
        argv = CliChatClient(cwd=str(tmp_path)).build_argv(SYSTEM_PROMPT, FRESH)

        for flag in STREAM_ARGS:
            assert flag in argv

    def test_system_prompt_replaces_the_default_one(self, tmp_path: Path) -> None:
        """Промпт передаётся `--system-prompt`, а не дописывается к чужому."""
        argv = CliChatClient(cwd=str(tmp_path)).build_argv(SYSTEM_PROMPT, FRESH)

        assert "--system-prompt" in argv
        assert argv[argv.index("--system-prompt") + 1] == SYSTEM_PROMPT
        assert "--append-system-prompt" not in argv

    def test_config_dir_points_at_its_own_directory(self, tmp_path: Path) -> None:
        """CLAUDE_CONFIG_DIR ведёт в свой каталог, а не в личный `~/.claude` хоста."""
        env = CliChatClient(
            config_dir="/data/claude-chat", cwd=str(tmp_path)
        ).build_env()

        assert env[CLAUDE_CONFIG_DIR_ENV] == "/data/claude-chat"


@pytest.mark.asyncio
class TestCliStream:
    """Запуск хода: что уходит в процесс и что приходит обратно."""

    async def test_process_gets_the_config_dir_and_the_fixed_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Каталог конфигурации и рабочий каталог доезжают до самого процесса."""
        workspace = tmp_path / "workspace"
        fake = FakeExec(FakeProcess([_delta_line("ok"), RESULT_LINE]))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
        client = CliChatClient(config_dir=str(tmp_path / "cfg"), cwd=str(workspace))

        chunks = [
            chunk
            async for chunk in client.stream_turn(
                system_prompt=SYSTEM_PROMPT, turns=[ChatTurn("user", "привет")]
            )
        ]

        assert fake.kwargs["cwd"] == str(workspace)
        assert fake.kwargs["env"][CLAUDE_CONFIG_DIR_ENV] == str(tmp_path / "cfg")
        # Каталог создаётся: пустой рабочий каталог — предусловие, а не надежда.
        assert workspace.is_dir()
        assert [chunk.kind for chunk in chunks] == [CHUNK_DELTA, CHUNK_USAGE]

    async def test_the_dialogue_goes_in_through_stdin(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Разговор передаётся stdin, а не аргументом: у argv есть предел длины."""
        process = FakeProcess([RESULT_LINE])
        fake = FakeExec(process)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
        client = CliChatClient(cwd=str(tmp_path))

        turns = [ChatTurn("user", "первый"), ChatTurn("assistant", "ответ")]
        async for _ in client.stream_turn(system_prompt=SYSTEM_PROMPT, turns=turns):
            pass

        assert process.stdin.written.decode() == render_transcript(turns)
        assert process.stdin.closed

    async def test_nonzero_exit_raises_without_leaking_content(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Ненулевой код — LLMError, в тексте которой нет ни куска разговора."""
        fake = FakeExec(FakeProcess([_delta_line("частичный ответ")], returncode=2))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
        client = CliChatClient(cwd=str(tmp_path))

        with pytest.raises(LLMError) as info:
            async for _ in client.stream_turn(
                system_prompt=SYSTEM_PROMPT, turns=[ChatTurn("user", SECRET)]
            ):
                pass

        message = str(info.value)
        assert SECRET not in message
        assert "частичный ответ" not in message

    async def test_missing_binary_raises_llm_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Нет бинарника — LLMError, а не голый FileNotFoundError наружу."""

        async def raise_not_found(*args: str, **kwargs: Any) -> FakeProcess:
            raise FileNotFoundError(args[0])

        monkeypatch.setattr(asyncio, "create_subprocess_exec", raise_not_found)
        client = CliChatClient(cwd=str(tmp_path))

        with pytest.raises(LLMError):
            async for _ in client.stream_turn(
                system_prompt=SYSTEM_PROMPT, turns=[ChatTurn("user", "привет")]
            ):
                pass


class TestStreamParser:
    """Разбор строк `--output-format stream-json`."""

    def test_text_delta_becomes_a_visible_chunk(self) -> None:
        chunk = parse_stream_line(_delta_line("кусок"))

        assert chunk == ChatChunk.delta("кусок")

    def test_result_carries_session_id_and_usage(self) -> None:
        """Вход считается вместе с созданием кеша — иначе проверка цены хода врёт."""
        chunk = parse_stream_line(RESULT_LINE)

        assert chunk is not None
        assert chunk.kind == CHUNK_USAGE
        assert chunk.session_id == "abc-123"
        assert chunk.input_tokens == 282
        assert chunk.output_tokens == 17
        assert chunk.cache_read_tokens == 0

    @pytest.mark.parametrize(
        "line",
        [
            b"\n",
            b"not json at all\n",
            b'{"type":"system","subtype":"init"}\n',
            b'{"type":"stream_event","event":{"type":"message_start"}}\n',
            b'{"type":"stream_event","event":{"type":"content_block_delta",'
            b'"delta":{"type":"thinking_delta","thinking":"..."}}}\n',
            b'["list", "not", "object"]\n',
        ],
    )
    def test_lines_without_visible_text_are_ignored(self, line: bytes) -> None:
        """Незнакомая строка пропускается: поток CLI пополняется от версии к версии."""
        assert parse_stream_line(line) is None

    def test_result_without_usage_still_parses(self) -> None:
        """Итог без счётчиков — не повод уронить ход."""
        chunk = parse_stream_line(b'{"type":"result","session_id":"s-1"}\n')

        assert chunk is not None
        assert chunk.kind == CHUNK_USAGE
        assert chunk.session_id == "s-1"
        assert chunk.input_tokens is None


class TestTranscript:
    """Реплей разговора одним промптом."""

    def test_roles_are_labelled_in_order(self) -> None:
        """Без подписей модель не отличает свою прошлую реплику от чужой."""
        text = render_transcript(
            [
                ChatTurn("user", "первый вопрос"),
                ChatTurn("assistant", "ответ"),
                ChatTurn("user", "второй вопрос"),
            ]
        )

        assert text == "Человек: первый вопрос\n\nТы: ответ\n\nЧеловек: второй вопрос"

    def test_unknown_role_does_not_break_the_replay(self) -> None:
        """Роль вне словаря получает нейтральную подпись, а не исключение."""
        text = render_transcript([ChatTurn("whatever", "текст")])

        assert text == "Реплика: текст"
