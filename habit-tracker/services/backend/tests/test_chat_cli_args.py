"""
Изоляция хода CLI от личной конфигурации хоста и разбор его потока.
"""

# [review:need-review] PHASE-03/111, PHASE-03/120
# summary: the isolation flag set (now shared with the one-shot `generate` client) is asserted whole (a turn that loses one of them costs tens of thousands of prefix tokens and leaks the host's personal config), CLAUDE_CONFIG_DIR and the fixed cwd reach the process, and the stream-json parser is checked on deltas, on the final result and on lines it must ignore rather than crash on
# summary: the parser is now checked against a whole recorded turn of CLI 2.1.251 (tests/fixtures/cli_stream/one_turn.jsonl) — thinking, block boundaries, tool names and stop_reason must all survive the trip, and --verbose is asserted in STREAM_ARGS because without it the CLI prints nothing at all
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.chat.client import (
    CHUNK_ACTING,
    CHUNK_DELTA,
    CHUNK_STEP_END,
    CHUNK_STOP,
    CHUNK_THINKING,
    CHUNK_USAGE,
    CHUNK_WRITING,
    STREAM_ARGS,
    ChatChunk,
    CliChatClient,
    parse_stream_line,
)
from app.llm.chat.prompt import ChatTurn, render_transcript
from app.llm.chat.session import MODE_REPLAY, TurnStrategy
from app.llm.cli import (
    CLAUDE_CONFIG_DIR_ENV,
    ISOLATION_ARGS,
    ISOLATION_FLAGS,
    CliInsightsClient,
)
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

# Запись настоящего хода CLI 2.1.251 под полным набором флагов изоляции,
# снятая 2026-08-31. Не пересказ протокола, а строки как есть: разборщик,
# проверенный на выдуманных строках, проверен на выдумке.
RECORDED_TURN = Path(__file__).parent / "fixtures" / "cli_stream" / "one_turn.jsonl"


def _recorded_lines() -> list[bytes]:
    """Строки записанного хода — по одной, как их читает `readline`."""
    return [
        line.encode() + b"\n"
        for line in RECORDED_TURN.read_text().splitlines()
        if line.strip()
    ]


def _event_line(event: dict[str, Any]) -> bytes:
    """Событие Messages API в обёртке CLI — одной строкой stdout."""
    payload = {"type": "stream_event", "event": event, "session_id": "s-1"}
    return json.dumps(payload, ensure_ascii=False).encode() + b"\n"


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

    def test_isolation_set_is_the_one_the_measurement_was_made_with(self) -> None:
        """
        Состав набора зафиксирован замером, а не вкусом.

        282 токена против 52 555 (ADR-0017, CLI 2.1.250) и 290 против 21 620
        для `--strict-mcp-config` (замер 2026-08-31, тот же CLI): источники
        настроек и MCP-серверы отключаются РАЗНЫМИ флагами, и второй забыли в
        `#111`. Тест держит набор целиком, чтобы следующая правка была
        осознанной и приезжала вместе со своим замером.
        """
        assert ISOLATION_FLAGS == (
            ("--tools", ""),
            ("--setting-sources", ""),
            ("--strict-mcp-config", None),
        )
        assert ISOLATION_ARGS == (
            "--tools",
            "",
            "--setting-sources",
            "",
            "--strict-mcp-config",
        )

    @pytest.mark.parametrize("flag,value", ISOLATION_FLAGS)
    def test_both_clients_carry_every_flag(
        self, flag: str, value: str | None, tmp_path: Path
    ) -> None:
        """
        Один набор на четыре юзкейса: чат и одноходовой `generate` — оба.

        Параметризация по парам «флаг — значение» здесь не украшение: тест
        обязан падать при пропаже ЛЮБОГО флага, а не только первого, и обязан
        падать за оба клиента сразу — иначе разбор дня уедет без изоляции,
        пока чат остаётся дешёвым.
        """
        chat_argv = CliChatClient(cwd=str(tmp_path)).build_argv(SYSTEM_PROMPT, FRESH)
        oneshot_argv = CliInsightsClient(cwd=str(tmp_path)).build_argv()

        for argv in (chat_argv, oneshot_argv):
            assert argv[0] == "claude"
            assert "-p" in argv
            assert flag in argv
            if value is not None:
                assert argv[argv.index(flag) + 1] == value

    def test_stream_flags_are_present(self, tmp_path: Path) -> None:
        """Поток кусками требует stream-json вместе с частичными сообщениями."""
        argv = CliChatClient(cwd=str(tmp_path)).build_argv(SYSTEM_PROMPT, FRESH)

        for flag in STREAM_ARGS:
            assert flag in argv

    def test_verbose_is_present(self, tmp_path: Path) -> None:
        """
        Без `--verbose` CLI 2.1.251 на `-p` вовсе не запускает stream-json.

        Отдельным тестом, а не строкой в наборе: отказ выглядит как пустой
        stdout и код 1, stderr уходит в `/dev/null`, и наружу это доезжает как
        `cli_exit: 1` без причины. Флаг, потерянный при рефакторинге, ломает
        чат целиком и молча.
        """
        argv = CliChatClient(cwd=str(tmp_path)).build_argv(SYSTEM_PROMPT, FRESH)

        assert "--verbose" in argv

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
            b'{"type":"stream_event","event":{"type":"message_stop"}}\n',
            # Подпись, которой CLI заменил рассуждение: читателю в ней нечего
            # смотреть, а разбирать её как мысль значило бы показывать base64.
            b'{"type":"stream_event","event":{"type":"content_block_delta",'
            b'"index":0,"delta":{"type":"signature_delta",'
            b'"signature":"CAISvwIKpgEIERgC"}}}\n',
            # Аргументы инструмента по кускам: имя уже приехало в начале блока.
            b'{"type":"stream_event","event":{"type":"content_block_delta",'
            b'"index":1,"delta":{"type":"input_json_delta",'
            b'"partial_json":"{\\"skill\\": \\"set"}}}\n',
            b'{"type":"system","subtype":"post_turn_summary",'
            b'"status_detail":"17 x 23 = 391"}\n',
            b'{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n',
            b'["list", "not", "object"]\n',
        ],
    )
    def test_lines_the_feed_has_nothing_to_show_for_are_ignored(
        self, line: bytes
    ) -> None:
        """Незнакомая строка пропускается: поток CLI пополняется от версии к версии."""
        assert parse_stream_line(line) is None

    def test_result_without_usage_still_parses(self) -> None:
        """Итог без счётчиков — не повод уронить ход."""
        chunk = parse_stream_line(b'{"type":"result","session_id":"s-1"}\n')

        assert chunk is not None
        assert chunk.kind == CHUNK_USAGE
        assert chunk.session_id == "s-1"
        assert chunk.input_tokens is None


class TestTurnSteps:
    """Шаги хода: чем модель занята между вопросом и первым словом ответа."""

    def test_thinking_block_start_says_the_model_is_thinking(self) -> None:
        """Начало блока мысли — единственный ранний признак живого хода."""
        chunk = parse_stream_line(
            _event_line(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "thinking",
                        "thinking": "",
                        "signature": "",
                    },
                }
            )
        )

        assert chunk == ChatChunk.thinking_step(index=0)

    def test_thinking_delta_carries_volume_and_no_words(self) -> None:
        """
        На подписке слов мысли нет — есть оценка объёма, и она доезжает.

        Пустое `thinking` здесь не упрощение теста: CLI 2.1.251 подменяет
        рассуждение подписью, и лента может показать «думает, ~50 токенов», но
        не текст. Тест закрепляет и то, и другое.
        """
        chunk = parse_stream_line(
            _event_line(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "thinking_delta",
                        "thinking": "",
                        "estimated_tokens": 50,
                    },
                }
            )
        )

        assert chunk is not None
        assert chunk.kind == CHUNK_THINKING
        assert chunk.thinking_tokens == 50
        assert chunk.thinking == ""
        # Мысль не притворяется ответом: собиратель строки читает только `text`.
        assert chunk.text == ""

    def test_system_thinking_tokens_is_the_same_step(self) -> None:
        """Свою оценку объёма CLI шлёт и отдельным служебным событием."""
        chunk = parse_stream_line(
            b'{"type":"system","subtype":"thinking_tokens","estimated_tokens":50,'
            b'"estimated_tokens_delta":50,"session_id":"s-1"}\n'
        )

        assert chunk == ChatChunk.thinking_step(thinking_tokens=50)

    def test_text_block_start_says_the_answer_began(self) -> None:
        """Граница «кончил думать, пошли слова» видна только отсюда."""
        chunk = parse_stream_line(
            _event_line(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                }
            )
        )

        assert chunk == ChatChunk.writing(index=1)

    def test_tool_block_start_names_the_tool(self) -> None:
        """
        Имя инструмента приезжает целиком, до аргументов.

        В этом чате шага не будет, пока стоит `--tools ""`, — разбирается поток
        CLI, а не одна его конфигурация. Строка снята с прогона без изоляции.
        """
        chunk = parse_stream_line(
            _event_line(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_01DFv7RfDokSd9sknH7BcsAW",
                        "name": "Skill",
                        "input": {},
                        "caller": {"type": "direct"},
                    },
                }
            )
        )

        assert chunk == ChatChunk.acting(tool_name="Skill", index=1)
        assert chunk is not None and chunk.kind == CHUNK_ACTING

    def test_block_stop_closes_the_step_by_its_index(self) -> None:
        """Конец шага сводится с началом по номеру: типа CLI тут не повторяет."""
        chunk = parse_stream_line(
            _event_line({"type": "content_block_stop", "index": 0})
        )

        assert chunk == ChatChunk.step_end(index=0)

    def test_message_delta_carries_the_reason_and_the_thinking_total(self) -> None:
        """`max_tokens` без этого шага неотличим от договорённого до конца."""
        chunk = parse_stream_line(
            _event_line(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "max_tokens"},
                    "usage": {
                        "input_tokens": 292,
                        "output_tokens": 585,
                        "output_tokens_details": {"thinking_tokens": 27},
                    },
                }
            )
        )

        assert chunk == ChatChunk.stop(stop_reason="max_tokens", thinking_tokens=27)


class TestRecordedTurn:
    """Записанный ход целиком: что видно в потоке, то и доезжает."""

    def test_every_step_of_a_real_turn_survives_the_parser(self) -> None:
        """
        Семнадцать строк живого CLI — в шаги ленты, по порядку.

        Тест держит границу разбора целиком, а не по одному событию: мысль,
        начало и конец обоих блоков, причина остановки и итог хода стоят на
        своих местах. Разборщик, разучившийся показывать мысль, падает здесь.
        """
        chunks = [
            chunk
            for chunk in (parse_stream_line(line) for line in _recorded_lines())
            if chunk is not None
        ]

        assert [chunk.kind for chunk in chunks] == [
            CHUNK_THINKING,  # content_block_start, блок 0
            CHUNK_THINKING,  # thinking_delta
            CHUNK_STEP_END,  # мысль кончилась
            CHUNK_WRITING,  # content_block_start, блок 1
            CHUNK_DELTA,  # text_delta
            CHUNK_STEP_END,  # ответ кончился
            CHUNK_STOP,  # message_delta
            CHUNK_USAGE,  # result
        ]

    def test_the_answer_is_assembled_from_deltas_alone(self) -> None:
        """
        Строка ответа собирается из `text` — и мысль в неё не попадает.

        Проверка той самой границы приватности: в базу уходит склейка `text`
        кусков `delta`, и ни один другой шаг хода в неё не вписывается.
        """
        chunks = [
            chunk
            for chunk in (parse_stream_line(line) for line in _recorded_lines())
            if chunk is not None
        ]

        answer = "".join(one.text for one in chunks if one.kind == CHUNK_DELTA)
        assert answer == "391"
        assert "".join(one.text for one in chunks if one.kind != CHUNK_DELTA) == ""

    def test_the_thinking_of_a_real_turn_carries_no_words(self) -> None:
        """Подписка отдаёт подпись вместо рассуждения — показывать нечего."""
        thoughts = [
            chunk
            for chunk in (parse_stream_line(line) for line in _recorded_lines())
            if chunk is not None and chunk.kind == CHUNK_THINKING
        ]

        assert thoughts
        assert all(one.thinking == "" for one in thoughts)

    def test_a_broken_line_in_the_middle_does_not_stop_the_turn(self) -> None:
        """Мусор посреди потока пропускается, остальные шаги доезжают."""
        lines = _recorded_lines()
        spoiled = lines[:3] + [b'{"type":"stream_event","event":\n', b"\x00\xff\n"]
        spoiled += lines[3:]

        chunks = [
            chunk
            for chunk in (parse_stream_line(line) for line in spoiled)
            if chunk is not None
        ]

        assert [chunk.kind for chunk in chunks] == [
            CHUNK_THINKING,
            CHUNK_THINKING,
            CHUNK_STEP_END,
            CHUNK_WRITING,
            CHUNK_DELTA,
            CHUNK_STEP_END,
            CHUNK_STOP,
            CHUNK_USAGE,
        ]


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
