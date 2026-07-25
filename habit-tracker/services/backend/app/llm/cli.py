# [review:need-review] PHASE-01/52-text-to-category-plan
# summary: CLI backend now pipes the caller's prompt verbatim (no baked insights system prompt)
from __future__ import annotations

import asyncio

from app.llm.client import LLM_TIMEOUT_SECONDS, LLMClient, LLMError

CLI_BINARY = "claude"
# Recorded as AIReport.model: the CLI decides the actual model itself.
CLI_MODEL_LABEL = "claude-cli"


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
