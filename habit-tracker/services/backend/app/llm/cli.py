# [review:need-review] PHASE-01/52-text-to-category-plan, PHASE-03/120
# summary: IsolatedCli — the one place `claude -p` is assembled (isolation flags, CLAUDE_CONFIG_DIR, fixed cwd); CliInsightsClient.generate now runs through it, so insights, onboarding and the day summary stop inheriting the host's personal configuration
"""
Одноходовой бэкенд на бинарнике `claude` и общая сборка его запуска.

**Изоляция живёт здесь, а не у каждого клиента.** `claude -p`, запущенный как
есть, тащит в запрос личную конфигурацию хоста: глобальный `CLAUDE.md`,
`SessionStart`-хуки, MCP-серверы, скиллы. Замер на CLI 2.1.250 — 52 555 токенов
префикса первого хода против 282 с полным набором флагов (ADR-0017). Набор
`ISOLATION_FLAGS` — единственный в репозитории: два его экземпляра означали бы,
что один из четырёх юзкейсов LLM тихо ходит без изоляции, а заметно это только
по счёту за подписку.

**Свой системный промпт вместо чужого.** `--system-prompt` заменяет агентный
промпт Claude Code целиком. Без него `--setting-sources ""` убирает источники
настроек, но оставляет многокилотокенную преамбулу самого CLI.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

from app.core.config import settings
from app.llm.client import LLM_TIMEOUT_SECONDS, LLMClient, LLMError
from app.llm.prompts import ONESHOT_SYSTEM_PROMPT

CLI_BINARY = "claude"
# Recorded as AIReport.model: the CLI decides the actual model itself.
CLI_MODEL_LABEL = "claude-cli"

# Полный набор флагов изоляции. ЕДИНСТВЕННОЕ место в репозитории, где он
# перечислен: и одноходовой `generate`, и поток чата собирают запуск отсюда.
# Проверяется тестом целиком — набор, из которого выпал один флаг, стоит
# десятки тысяч токенов на каждом ходу и утекает личной конфигурацией.
#
# Пары «флаг — значение»; None во втором поле — флаг без аргумента.
ISOLATION_FLAGS: tuple[tuple[str, str | None], ...] = (
    # Модель ничего не исполняет: ни у отчёта, ни у чата нет инструментов.
    ("--tools", ""),
    # Ни хуков, ни глобального CLAUDE.md, ни чужих настроек.
    ("--setting-sources", ""),
    # MCP-серверы источниками настроек не считаются: они приезжают из
    # `~/.claude.json` каталога конфигурации, и `--setting-sources ""` их не
    # трогает — `--help` самого CLI отсылает за ними сюда. Замер 2026-08-31 на
    # CLI 2.1.250: без этого флага первый ход стоил 21 620 токенов (описания
    # инструментов чужих MCP-серверов), с ним — 290.
    ("--strict-mcp-config", None),
)

ISOLATION_ARGS: tuple[str, ...] = tuple(
    part
    for flag, value in ISOLATION_FLAGS
    for part in ((flag,) if value is None else (flag, value))
)

# Переменная окружения, которой CLI указывают его собственный каталог конфигурации.
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

# Формат ответа одноходового вызова: голый текст, без обёртки.
TEXT_OUTPUT_ARGS: tuple[str, ...] = ("--output-format", "text")


class IsolatedCli:
    """
    Запуск `claude -p`, отрезанный от личной конфигурации хоста.

    Три вещи, которые нельзя забыть ни в одном юзкейсе, и потому собранные в
    одном объекте: набор флагов изоляции, свой каталог конфигурации
    (`CLAUDE_CONFIG_DIR`) и фиксированный рабочий каталог. Последний не деталь
    запуска — файл сессии CLI лежит в каталоге, названном по cwd, и `--resume`
    (`#112`) сверяет его перед тем, как продолжить разговор.

    Аргументы и окружение собираются отдельными методами, чтобы изоляцию можно
    было проверить тестом без запуска процесса.
    """

    def __init__(
        self,
        binary: str = CLI_BINARY,
        config_dir: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self._binary = binary
        self._config_dir = config_dir or settings.CHAT_CLAUDE_CONFIG_DIR
        self._cwd = cwd or settings.CHAT_CLI_CWD

    @property
    def cwd(self) -> str:
        """Рабочий каталог процесса — он же ключ файла сессии CLI."""
        return self._cwd

    @property
    def config_dir(self) -> str:
        """Каталог конфигурации — вторая половина ключа файла сессии."""
        return self._config_dir

    def build_argv(
        self,
        *,
        system_prompt: str,
        output_args: Sequence[str],
        extra_args: Sequence[str] = (),
    ) -> list[str]:
        """
        Полная командная строка одного вызова.

        `extra_args` — флаги, которые знает только вызывающий: чат добавляет
        сюда `--session-id`/`--resume` (`#112`). Изоляция от них не зависит и
        потому остаётся здесь, а не переезжает к каждому юзкейсу по копии.
        """
        return [
            self._binary,
            "-p",
            *output_args,
            *ISOLATION_ARGS,
            "--system-prompt",
            system_prompt,
            *extra_args,
        ]

    def build_env(self) -> dict[str, str]:
        """Окружение процесса: свой каталог конфигурации поверх текущего."""
        env = dict(os.environ)
        env[CLAUDE_CONFIG_DIR_ENV] = self._config_dir
        return env

    async def spawn(
        self,
        *,
        system_prompt: str,
        output_args: Sequence[str],
        stderr: int,
        extra_args: Sequence[str] = (),
    ) -> asyncio.subprocess.Process:
        """
        Поднять процесс с изолированными аргументами, окружением и каталогом.

        Промпт всегда уходит в stdin, а не аргументом: у argv есть предел длины,
        а контекст месяца в него не помещается. Ошибка запуска отдаётся как
        есть — каждый вызывающий переводит её в свой код отказа.
        """
        os.makedirs(self._cwd, exist_ok=True)
        return await asyncio.create_subprocess_exec(
            *self.build_argv(
                system_prompt=system_prompt,
                output_args=output_args,
                extra_args=extra_args,
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr,
            cwd=self._cwd,
            env=self.build_env(),
        )


class CliInsightsClient(LLMClient):
    """
    Text generation backed by a logged-in `claude` CLI binary.

    Runs `claude -p --output-format text` under the full isolation flag set
    (`IsolatedCli`) with the prompt piped to stdin, without blocking the event
    loop. The caller's prompt still carries its own domain instructions; the
    `--system-prompt` here only replaces the CLI's own agent preamble, so the
    three existing one-shot use cases keep their meaning.

    Any failure (non-zero exit, timeout, missing binary, empty output) is
    mapped to LLMError; error messages never include prompt or response content.
    """

    model: str = CLI_MODEL_LABEL

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
    def cli(self) -> IsolatedCli:
        """Сборка запуска — она же то, что проверяет смоук изоляции."""
        return self._cli

    def build_argv(self) -> list[str]:
        """Командная строка одноходового вызова."""
        return self._cli.build_argv(
            system_prompt=ONESHOT_SYSTEM_PROMPT, output_args=TEXT_OUTPUT_ARGS
        )

    def build_env(self) -> dict[str, str]:
        """Окружение одноходового вызова."""
        return self._cli.build_env()

    async def generate(self, prompt: str) -> str:
        try:
            process = await self._cli.spawn(
                system_prompt=ONESHOT_SYSTEM_PROMPT,
                output_args=TEXT_OUTPUT_ARGS,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LLMError("claude CLI binary not found") from exc
        except OSError as exc:
            # Каталог не создался, бинарник не исполняется — наружу уходит
            # только класс ошибки, без пути и без содержимого запроса.
            raise LLMError(f"claude CLI failed to start: {type(exc).__name__}") from exc

        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(prompt.encode()), timeout=self._timeout
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise LLMError("claude CLI timed out") from exc

        if process.returncode != 0:
            # Only the exit code is propagated: stderr/stdout may echo
            # prompt or report content and must never reach logs.
            raise LLMError(f"claude CLI exited with code {process.returncode}")

        text = stdout.decode().strip()
        if not text:
            raise LLMError("empty response from claude CLI")
        return text
