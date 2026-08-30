# [review:need-review] PHASE-01/52-text-to-category-plan, PHASE-03/111
# summary: neutral LLMClient.generate(prompt) — no baked system prompt; InsightsClient kept as alias, both backends preserved; the SDK handle and its error class are exposed so app/llm/chat can stream without a second `import anthropic`
from __future__ import annotations

import shutil

import anthropic

from app.core.config import settings

# Upstream error class, re-exported. `app/llm/chat/` needs to tell an API
# failure apart from a bug in its own parser, and this file stays the only one
# in `app/` that imports the SDK — an invariant checked by grep, not by memory.
AnthropicAPIError = anthropic.APIError

INSIGHTS_MODEL = "claude-sonnet-5"
# Generous timeout: a month-of-data report or an onboarding plan is a long request.
LLM_TIMEOUT_SECONDS = 120.0
# Total output budget (Sonnet 5 runs adaptive thinking by default,
# which shares this budget with the visible output text).
MAX_REPORT_TOKENS = 8192


class LLMError(Exception):
    """LLM call failed: upstream API error, timeout, or empty response."""


class LLMClient:
    """
    Neutral text-in/text-out LLM interface.

    `generate` takes a fully-formed prompt (the caller bakes in any system
    instructions it needs) and returns the raw response text. Callers that
    need domain framing — insight reports, onboarding plans — assemble their
    own prompt and parse the result themselves.

    Tests mock at this boundary; the real implementations are
    AnthropicInsightsClient (API) and CliInsightsClient (claude CLI).
    """

    model: str = INSIGHTS_MODEL

    async def generate(self, prompt: str) -> str:
        """Send the prompt to the backend and return the response text."""
        raise NotImplementedError


# Backward-compatible alias: the class was insight-specific before it was
# generalised. Existing insight code and tests keep the old name.
InsightsClient = LLMClient


class AnthropicInsightsClient(LLMClient):
    """Text generation backed by the Anthropic Messages API."""

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=LLM_TIMEOUT_SECONDS
        )

    @property
    def sdk(self) -> anthropic.AsyncAnthropic:
        """
        The configured SDK handle, for callers that need a call `generate` is
        not — streaming a chat turn, say. Exposed rather than duplicated: a
        second `anthropic.AsyncAnthropic(...)` elsewhere would be a second
        place the timeout and the key are configured.
        """
        return self._client

    async def generate(self, prompt: str) -> str:
        try:
            response = await self._client.messages.create(
                model=INSIGHTS_MODEL,
                max_tokens=MAX_REPORT_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            # Only the exception class name is propagated: no prompt/response
            # content and no API key ever reach logs or error messages.
            raise LLMError(f"anthropic API error: {type(exc).__name__}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise LLMError("empty response from LLM")
        return text


def resolve_insights_client() -> LLMClient | None:
    """
    Pick the LLM backend from settings; None = feature disabled (503).

    LLM_BACKEND=cli -> claude CLI (None when the binary is missing);
    LLM_BACKEND=api -> Anthropic API (None when the key is empty);
    empty -> auto: cli when no key and the binary is found, else api.
    """
    # Local import: app.llm.cli imports this module for the base class.
    from app.llm.cli import CLI_BINARY, CliInsightsClient

    backend = settings.LLM_BACKEND
    if not backend:
        no_key_but_cli = not settings.ANTHROPIC_API_KEY and shutil.which(CLI_BINARY)
        backend = "cli" if no_key_but_cli else "api"

    if backend == "cli":
        if shutil.which(CLI_BINARY) is None:
            return None
        return CliInsightsClient()

    if not settings.ANTHROPIC_API_KEY:
        return None
    return AnthropicInsightsClient(api_key=settings.ANTHROPIC_API_KEY)


# Neutral name for the same backend selection, used by non-insight callers.
resolve_llm_client = resolve_insights_client
