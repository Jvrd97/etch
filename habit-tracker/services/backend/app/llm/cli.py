# [review:need-review] PHASE-01/52-text-to-category-plan, PHASE-03/116
# summary: CLI backend now pipes the caller's prompt verbatim (no baked insights system prompt); terminate_process is the one kill+wait every exit path of a CLI turn goes through
from __future__ import annotations

import asyncio

from app.llm.client import LLM_TIMEOUT_SECONDS, LLMClient, LLMError

CLI_BINARY = "claude"
# Recorded as AIReport.model: the CLI decides the actual model itself.
CLI_MODEL_LABEL = "claude-cli"


# Сколько ждать завершения убитого процесса, прежде чем перестать его ждать.
# Отмена хода не должна зависать на процессе, который уже получил SIGKILL.
KILL_WAIT_SECONDS = 5.0


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    """
    Убить процесс и дождаться его — но не дольше `KILL_WAIT_SECONDS`.

    Одной функцией, потому что порознь `kill` и `wait` и забывают: `kill` без
    `wait` оставляет зомби, `wait` без предела подвешивает отмену хода.

    `shield` здесь несущий. Функция вызывается в том числе из `finally`,
    раскручиваемого отменой, а обычный `await` внутри отменяемого кода получает
    `CancelledError` немедленно и оставляет процесс жить дальше — ровно тот
    случай, ради которого `#116` и требует гарантированного убийства.
    """
    if process.returncode is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        # Успел завершиться сам между проверкой и сигналом — ждать нечего.
        return
    try:
        await asyncio.wait_for(
            asyncio.shield(process.wait()), timeout=KILL_WAIT_SECONDS
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        # Процесс уже получил SIGKILL; ядро доберёт его без нас, а держать ход
        # ради этого ожидания смысла нет.
        return


class CliInsightsClient(LLMClient):
    """
    Text generation backed by a logged-in `claude` CLI binary.

    Runs `claude -p --output-format text` with the prompt piped to stdin
    (avoids argv size limits) without blocking the event loop. Any failure
    (non-zero exit, timeout, missing binary, empty output) is mapped to
    LLMError; error messages never include prompt or response content.
    """

    model: str = CLI_MODEL_LABEL

    def __init__(
        self, binary: str = CLI_BINARY, timeout: float = LLM_TIMEOUT_SECONDS
    ) -> None:
        self._binary = binary
        self._timeout = timeout

    async def generate(self, prompt: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self._binary,
                "-p",
                "--output-format",
                "text",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LLMError("claude CLI binary not found") from exc

        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(prompt.encode()), timeout=self._timeout
            )
        except asyncio.TimeoutError as exc:
            await terminate_process(process)
            raise LLMError("claude CLI timed out") from exc

        if process.returncode != 0:
            # Only the exit code is propagated: stderr/stdout may echo
            # prompt or report content and must never reach logs.
            raise LLMError(f"claude CLI exited with code {process.returncode}")

        text = stdout.decode().strip()
        if not text:
            raise LLMError("empty response from claude CLI")
        return text
