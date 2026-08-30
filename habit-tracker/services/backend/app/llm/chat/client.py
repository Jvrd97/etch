# [review:need-review] PHASE-03/111, PHASE-03/120
# summary: ChatLLMClient.stream_turn — the second transport method beside LLMClient.generate; the CLI implementation runs `claude -p` through the shared IsolatedCli of app/llm/cli.py (isolation flags, CLAUDE_CONFIG_DIR, fixed empty cwd), the API one streams messages.stream, and both hand back the same ChatChunk stream
"""
Транспорт многоходового разговора.

**Второй метод, а не переписанный первый.** `LLMClient.generate(prompt) -> str`
остаётся дословно: на нём стоят три работающих юзкейса и граница моков в
четырёх файлах тестов. Рядом появляется `ChatLLMClient.stream_turn(...)`,
отдающий поток `ChatChunk`. Оба бэкенда обязаны работать, поэтому у CLI и у API
одна форма ответа и один набор событий.

**Несущее здесь — изоляция, а не поток.** `claude -p`, запущенный как есть,
тащит в каждый запрос личную конфигурацию хоста: глобальный `CLAUDE.md`,
`SessionStart`-хуки, MCP-серверы, скиллы. Замер на CLI 2.1.250 — 52 555 токенов
префикса первого хода против 282 с полным набором флагов. На проде хостовый
`~/.claude` смонтирован в контейнер, то есть без флагов это происходит уже
сейчас. Поэтому `ISOLATION_ARGS` — не оптимизация, а условие приёмки, и на него
стоит отдельный тест: набор проверяется целиком, а не «хотя бы `--tools`».
Живёт он одним экземпляром в `app/llm/cli.py` — там же, где его берёт
одноходовой `generate`, потому что второй список флагов означал бы юзкейс,
тихо ходящий без изоляции.

**Личный конфиг заменяется своим, а не отключается наполовину.**
`--setting-sources ""` убирает источники настроек, `CLAUDE_CONFIG_DIR`
показывает на отдельный том, cwd фиксирован пустым каталогом. Последнее важно
дважды: CLI кладёт файл сессии в каталог, названный по cwd, и `--resume`
(`#112`) ключуется тем же cwd.

**Содержимое разговора не попадает ни в лог, ни в текст исключения.** stderr
процесса уходит в `/dev/null`: там эхо промпта, а прочитанный и залогированный
stderr — ровно тот путь, которым тексты дневника оказываются в логах.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app.core.config import settings
from app.llm.chat.prompt import ChatTurn, render_transcript
from app.llm.cli import CLI_BINARY, CLI_MODEL_LABEL, IsolatedCli
from app.llm.client import (
    INSIGHTS_MODEL,
    LLM_TIMEOUT_SECONDS,
    MAX_REPORT_TOKENS,
    AnthropicAPIError,
    AnthropicInsightsClient,
    LLMError,
)
from app.models.chat import MESSAGE_ROLE_ASSISTANT, MESSAGE_ROLE_USER

BACKEND_CLI = "cli"
BACKEND_API = "api"

CHUNK_DELTA = "delta"
CHUNK_USAGE = "usage"

# Флаги потока. `--include-partial-messages` работает только вместе с
# `--output-format stream-json`, поэтому они и стоят рядом.
STREAM_ARGS: tuple[str, ...] = (
    "--output-format",
    "stream-json",
    "--include-partial-messages",
)

# Коды отказа. Машинные: в `chat_messages.error_code` пишется одно из них, а не
# текст, в котором мог бы оказаться кусок разговора.
ERROR_CLI_START = "cli_start_failed"
ERROR_CLI_TIMEOUT = "cli_timeout"
ERROR_CLI_EXIT = "cli_exit"
ERROR_API = "api_error"


@dataclass(frozen=True)
class ChatChunk:
    """
    Один кусок ответа: либо текст, либо итог хода.

    Одна структура на два вида событий, различаемых `kind`. Два класса
    выглядели бы честнее ровно до первого `isinstance` в цикле стрима; здесь
    поле-дискриминатор читается и в тесте, и в обработчике SSE.

    `input_tokens` — это вход **вместе с созданием кеша**: у чата нет отдельной
    колонки под `cache_creation_input_tokens`, а проверка «первый ход дешевле
    тысячи токенов» без неё считала бы не то. Сумма честнее одного слагаемого.
    """

    kind: str
    text: str = ""
    session_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None

    @classmethod
    def delta(cls, text: str) -> "ChatChunk":
        """Кусок видимого текста ответа."""
        return cls(kind=CHUNK_DELTA, text=text)

    @classmethod
    def usage(
        cls,
        *,
        session_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
    ) -> "ChatChunk":
        """Итог хода: чем он обошёлся и какой сессией CLI его можно продолжить."""
        return cls(
            kind=CHUNK_USAGE,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        )


class ChatLLMClient:
    """
    Многоходовой транспорт: история сообщений на входе, поток кусков на выходе.

    Граница моков в тестах проходит ровно здесь. Реализации —
    `CliChatClient` (подписка Claude Code) и `AnthropicChatClient` (API);
    снаружи они неотличимы, и это то самое требование паритета бэкендов,
    ради которого чат не пользуется native tool use.
    """

    model: str = INSIGHTS_MODEL
    backend: str = BACKEND_API

    @property
    def cwd(self) -> str | None:
        """
        Рабочий каталог процесса, если у бэкенда он вообще есть.

        Не деталь запуска: файл сессии CLI лежит в каталоге, названном по cwd, и
        `--resume` (`#112`) сверяет его перед тем, как продолжить разговор.
        У API-бэкенда каталога нет, и None здесь — это «сверять нечего».
        """
        return None

    def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        """Отправить разговор целиком и отдавать ответ кусками по мере прихода."""
        raise NotImplementedError


def parse_stream_line(line: bytes) -> ChatChunk | None:
    """
    Одна строка `--output-format stream-json` в кусок ответа, либо None.

    Что разбирается: `stream_event` с `content_block_delta` / `text_delta` —
    видимый текст, и финальный `result` — `session_id` и `usage`. Всё
    остальное (`system`, `assistant`, `user`, служебные события) молча
    пропускается: поток CLI пополняется типами событий от версии к версии, и
    падать на незнакомом — значит ронять чат при каждом обновлении.

    Нераспознанная строка не логируется: в ней текст ответа.
    """
    text = line.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        event: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None

    kind = event.get("type")
    if kind == "stream_event":
        return _parse_stream_event(event.get("event"))
    if kind == "result":
        return _parse_result(event)
    return None


def _parse_stream_event(inner: Any) -> ChatChunk | None:
    """`content_block_delta` с `text_delta` — единственное, что несёт текст."""
    if not isinstance(inner, dict) or inner.get("type") != "content_block_delta":
        return None
    delta = inner.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return None
    piece = delta.get("text")
    if not isinstance(piece, str) or not piece:
        return None
    return ChatChunk.delta(piece)


def _int_or_none(source: dict[str, Any], key: str) -> int | None:
    """Целое поле usage, либо None. `bool` — не число: True не есть один токен."""
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _parse_result(event: dict[str, Any]) -> ChatChunk:
    """Финальное событие хода: id сессии и счётчики токенов."""
    raw_usage = event.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    plain_input = _int_or_none(usage, "input_tokens")
    cache_creation = _int_or_none(usage, "cache_creation_input_tokens")
    total_input = (
        None
        if plain_input is None and cache_creation is None
        else (plain_input or 0) + (cache_creation or 0)
    )
    session_id = event.get("session_id")
    return ChatChunk.usage(
        session_id=session_id if isinstance(session_id, str) else None,
        input_tokens=total_input,
        output_tokens=_int_or_none(usage, "output_tokens"),
        cache_read_tokens=_int_or_none(usage, "cache_read_input_tokens"),
    )


class CliChatClient(ChatLLMClient):
    """
    Разговор через залогиненный бинарник `claude`, изолированный от хоста.

    Аргументы собираются `build_argv`, окружение — `build_env`, и обе функции
    существуют отдельно от стрима затем, чтобы набор флагов изоляции
    проверялся тестом без запуска процесса.
    """

    model: str = CLI_MODEL_LABEL
    backend: str = BACKEND_CLI

    def __init__(
        self,
        binary: str = CLI_BINARY,
        timeout: float = LLM_TIMEOUT_SECONDS,
        config_dir: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._cli = IsolatedCli(binary=binary, config_dir=config_dir, cwd=cwd)

    @property
    def cwd(self) -> str:
        """Рабочий каталог процесса — он же ключ файла сессии CLI."""
        return self._cli.cwd

    def build_argv(self, system_prompt: str) -> list[str]:
        """Полная командная строка одного хода."""
        return self._cli.build_argv(
            system_prompt=system_prompt, output_args=STREAM_ARGS
        )

    def build_env(self) -> dict[str, str]:
        """Окружение процесса: свой каталог конфигурации поверх текущего."""
        return self._cli.build_env()

    async def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        """Запустить ход и отдавать куски по мере того, как их печатает CLI."""
        prompt = render_transcript(turns)
        try:
            process = await self._cli.spawn(
                system_prompt=system_prompt,
                output_args=STREAM_ARGS,
                # Не PIPE: stderr CLI повторяет промпт, а непрочитанный PIPE
                # ещё и подвешивает процесс на переполнении буфера.
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            # Имя каталога и класс ошибки — всё, что уходит наружу.
            raise LLMError(f"{ERROR_CLI_START}: {type(exc).__name__}") from exc

        stdin = process.stdin
        stdout = process.stdout
        if stdin is None or stdout is None:  # pragma: no cover - PIPE запрошен выше
            process.kill()
            await process.wait()
            raise LLMError(f"{ERROR_CLI_START}: pipes unavailable")

        deadline = time.monotonic() + self._timeout
        try:
            stdin.write(prompt.encode())
            await stdin.drain()
            stdin.close()

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMError(ERROR_CLI_TIMEOUT)
                try:
                    line = await asyncio.wait_for(stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise LLMError(ERROR_CLI_TIMEOUT) from exc
                if not line:
                    break
                chunk = parse_stream_line(line)
                if chunk is not None:
                    yield chunk

            code = await process.wait()
            if code != 0:
                raise LLMError(f"{ERROR_CLI_EXIT}: {code}")
        finally:
            # Обрыв соединения закрывает генератор — процесс не должен пережить
            # разговор, который его породил.
            if process.returncode is None:
                process.kill()
                await process.wait()


class AnthropicChatClient(ChatLLMClient):
    """
    Разговор через Messages API: тот же поток кусков, полный список сообщений.

    Сессий у API нет, поэтому каждый ход уходит целиком; `session_id` в итоге
    хода не заполняется, и `--resume` (`#112`) на этом бэкенде не включается.
    """

    model: str = INSIGHTS_MODEL
    backend: str = BACKEND_API

    def __init__(self, api_key: str) -> None:
        # Через существующий клиент, а не второй экземпляр SDK: ключ и таймаут
        # настраиваются в одном месте.
        self._api = AnthropicInsightsClient(api_key=api_key)

    async def stream_turn(
        self, *, system_prompt: str, turns: Sequence[ChatTurn]
    ) -> AsyncIterator[ChatChunk]:
        """Отправить весь диалог и отдавать текст по мере генерации."""
        messages = _api_messages(turns)
        try:
            async with self._api.sdk.messages.stream(
                model=self.model,
                max_tokens=MAX_REPORT_TOKENS,
                system=system_prompt,
                # MessageParam — TypedDict из SDK, а тянуть SDK сюда нельзя:
                # единственная точка его импорта — app/llm/client.py. Форма
                # словаря ровно та, которую требует тип.
                messages=cast(Any, messages),
            ) as stream:
                async for piece in stream.text_stream:
                    if piece:
                        yield ChatChunk.delta(piece)
                final = await stream.get_final_message()
        except AnthropicAPIError as exc:
            raise LLMError(f"{ERROR_API}: {type(exc).__name__}") from exc

        cache_creation = final.usage.cache_creation_input_tokens or 0
        yield ChatChunk.usage(
            input_tokens=final.usage.input_tokens + cache_creation,
            output_tokens=final.usage.output_tokens,
            cache_read_tokens=final.usage.cache_read_input_tokens,
        )


def _api_messages(turns: Sequence[ChatTurn]) -> list[dict[str, str]]:
    """
    Реплики в форме Messages API.

    `system_note` — реплика сервера, а не участника разговора, и роли под неё
    в API нет. Она приезжает как реплика человека с пометкой: выбросить её
    молча значило бы, что модель не видит, почему прошлый ход оборвался.
    """
    messages: list[dict[str, str]] = []
    for turn in turns:
        if turn.role == MESSAGE_ROLE_ASSISTANT:
            messages.append({"role": MESSAGE_ROLE_ASSISTANT, "content": turn.content})
        elif turn.role == MESSAGE_ROLE_USER:
            messages.append({"role": MESSAGE_ROLE_USER, "content": turn.content})
        else:
            messages.append(
                {"role": MESSAGE_ROLE_USER, "content": f"[система] {turn.content}"}
            )
    return messages


def resolve_chat_client() -> ChatLLMClient | None:
    """
    Выбрать бэкенд чата по настройкам; None — чат выключен (503).

    Та же развилка, что у одноходового транспорта, и намеренно та же настройка
    `LLM_BACKEND`: два переключателя бэкенда означали бы, что разбор дня и
    разговор о нём отвечают из разных мест.
    """
    backend: str = settings.LLM_BACKEND
    if not backend:
        no_key_but_cli = not settings.ANTHROPIC_API_KEY and shutil.which(CLI_BINARY)
        backend = BACKEND_CLI if no_key_but_cli else BACKEND_API

    if backend == BACKEND_CLI:
        if shutil.which(CLI_BINARY) is None:
            return None
        return CliChatClient()

    if not settings.ANTHROPIC_API_KEY:
        return None
    return AnthropicChatClient(api_key=settings.ANTHROPIC_API_KEY)
