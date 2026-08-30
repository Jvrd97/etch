"""
Tests for the CLI LLM backend (claude -p) and backend selection.
"""

# [review:need-review] PHASE-01/26-llm-cli-backend, PHASE-03/120
# summary: unit tests for CliInsightsClient (mocked subprocess: success, exit!=0, timeout, no binary) + backend selection + the isolation of the one-shot call (flag set whole, own CLAUDE_CONFIG_DIR, fixed cwd, own system prompt)
import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.llm.cli import (
    CLAUDE_CONFIG_DIR_ENV,
    ISOLATION_FLAGS,
    TEXT_OUTPUT_ARGS,
    CliInsightsClient,
)
from app.llm.client import (
    AnthropicInsightsClient,
    LLMError,
    resolve_insights_client,
)
from app.llm.prompts import ONESHOT_SYSTEM_PROMPT


class FakeProcess:
    """Fake asyncio subprocess: canned stdout/returncode, optional hang."""

    def __init__(
        self, returncode: int = 0, stdout: bytes = b"", hang: bool = False
    ) -> None:
        self.returncode: int | None = returncode
        self._stdout = stdout
        self._hang = hang
        self.killed = False
        self.stdin_data: bytes | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin_data = input
        if self._hang:
            await asyncio.sleep(3600)
        return self._stdout, b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return -9 if self.killed else (self.returncode or 0)


class FakeExecFactory:
    """Replacement for asyncio.create_subprocess_exec recording the argv."""

    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.argv: tuple[str, ...] | None = None
        self.kwargs: dict[str, Any] = {}

    async def __call__(self, *args: str, **kwargs: Any) -> FakeProcess:
        self.argv = args
        self.kwargs = kwargs
        return self.process

    def argv_or_fail(self) -> tuple[str, ...]:
        """The recorded argv, or a failed assertion instead of an Optional dance."""
        assert self.argv is not None
        return self.argv


@pytest.mark.asyncio
class TestCliInsightsClient:
    """CliInsightsClient.generate with asyncio subprocess mocked."""

    async def test_success_returns_stdout_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exit 0 -> stdout is returned; prompt goes to stdin of `claude -p`."""
        fake = FakeExecFactory(FakeProcess(returncode=0, stdout=b"## Report\n\nok\n"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)

        result = await CliInsightsClient().generate("period context here")

        assert result == "## Report\n\nok"
        assert fake.argv is not None
        assert fake.argv[0] == "claude"
        assert "-p" in fake.argv
        assert "--output-format" in fake.argv
        assert fake.process.stdin_data is not None
        assert b"period context here" in fake.process.stdin_data

    async def test_nonzero_exit_raises_llm_error_without_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exit != 0 -> LLMError; message leaks neither prompt nor output."""
        fake = FakeExecFactory(FakeProcess(returncode=1, stdout=b"partial output"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)

        with pytest.raises(LLMError) as exc_info:
            await CliInsightsClient().generate("secret context")

        message = str(exc_info.value)
        assert "secret context" not in message
        assert "partial output" not in message

    async def test_timeout_kills_process_and_raises_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hanging CLI -> killed after timeout -> LLMError."""
        fake = FakeExecFactory(FakeProcess(hang=True))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)

        with pytest.raises(LLMError):
            await CliInsightsClient(timeout=0.01).generate("ctx")

        assert fake.process.killed

    async def test_missing_binary_raises_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FileNotFoundError from exec -> LLMError (defense in depth)."""

        async def raise_not_found(*args: str, **kwargs: Any) -> FakeProcess:
            raise FileNotFoundError(args[0])

        monkeypatch.setattr(asyncio, "create_subprocess_exec", raise_not_found)

        with pytest.raises(LLMError):
            await CliInsightsClient().generate("ctx")

    async def test_empty_stdout_raises_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exit 0 with blank stdout -> LLMError, not an empty report."""
        fake = FakeExecFactory(FakeProcess(returncode=0, stdout=b"  \n"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)

        with pytest.raises(LLMError):
            await CliInsightsClient().generate("ctx")


class TestOneShotIsolation:
    """
    Одноходовой вызов отрезан от личной конфигурации хоста ровно так же, как чат.

    Инсайты, онбординг категорий и разбор дня ходят через `generate`. Без этих
    флагов каждый из них тащит в запрос глобальный CLAUDE.md, хуки, MCP-серверы
    и скиллы владельца машины — замер ADR-0017: 52 555 токенов префикса против
    282, плюс прогон, в котором модель отработала личный скилл `/set`.
    """

    @pytest.mark.parametrize("flag,value", ISOLATION_FLAGS)
    def test_every_isolation_flag_is_present(
        self, flag: str, value: str | None, tmp_path: Path
    ) -> None:
        """Набор проверяется целиком: пропажа любого флага валит тест."""
        argv = CliInsightsClient(cwd=str(tmp_path)).build_argv()

        assert argv[0] == "claude"
        assert "-p" in argv
        assert flag in argv
        if value is not None:
            assert argv[argv.index(flag) + 1] == value

    def test_own_system_prompt_replaces_the_cli_preamble(self, tmp_path: Path) -> None:
        """Свой промпт передаётся `--system-prompt`, а не дописывается к чужому."""
        argv = CliInsightsClient(cwd=str(tmp_path)).build_argv()

        assert argv[argv.index("--system-prompt") + 1] == ONESHOT_SYSTEM_PROMPT
        assert "--append-system-prompt" not in argv

    def test_text_output_is_kept(self, tmp_path: Path) -> None:
        """Формат ответа прежний: три юзкейса разбирают голый текст."""
        argv = CliInsightsClient(cwd=str(tmp_path)).build_argv()

        for flag in TEXT_OUTPUT_ARGS:
            assert flag in argv

    def test_config_dir_points_at_its_own_directory(self, tmp_path: Path) -> None:
        """CLAUDE_CONFIG_DIR ведёт в свой каталог, а не в личный `~/.claude`."""
        env = CliInsightsClient(
            config_dir=str(tmp_path / "cfg"), cwd=str(tmp_path)
        ).build_env()

        assert env[CLAUDE_CONFIG_DIR_ENV] == str(tmp_path / "cfg")

    @pytest.mark.asyncio
    async def test_process_gets_the_config_dir_and_the_fixed_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Каталог конфигурации и рабочий каталог доезжают до самого процесса."""
        workspace = tmp_path / "workspace"
        fake = FakeExecFactory(FakeProcess(returncode=0, stdout=b"ok"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
        client = CliInsightsClient(config_dir=str(tmp_path / "cfg"), cwd=str(workspace))

        await client.generate("ctx")

        assert fake.kwargs["cwd"] == str(workspace)
        assert fake.kwargs["env"][CLAUDE_CONFIG_DIR_ENV] == str(tmp_path / "cfg")
        # Каталог создаётся: пустой рабочий каталог — предусловие, а не надежда.
        assert workspace.is_dir()
        assert "--setting-sources" in fake.argv_or_fail()


class TestBackendSelection:
    """resolve_insights_client: LLM_BACKEND env + auto-detection."""

    def _set_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        backend: str,
        api_key: str,
        binary_found: bool,
    ) -> None:
        monkeypatch.setattr(settings, "LLM_BACKEND", backend)
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", api_key)
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/local/bin/claude" if binary_found else None,
        )

    def test_explicit_cli_with_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM_BACKEND=cli and binary present -> CLI client."""
        self._set_env(monkeypatch, backend="cli", api_key="", binary_found=True)
        assert isinstance(resolve_insights_client(), CliInsightsClient)

    def test_explicit_cli_without_binary_disables_feature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM_BACKEND=cli but no binary -> None (503 branch)."""
        self._set_env(monkeypatch, backend="cli", api_key="", binary_found=False)
        assert resolve_insights_client() is None

    def test_explicit_api_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM_BACKEND=api and key set -> API client."""
        self._set_env(monkeypatch, backend="api", api_key="sk-test", binary_found=True)
        assert isinstance(resolve_insights_client(), AnthropicInsightsClient)

    def test_explicit_api_without_key_disables_feature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM_BACKEND=api but empty key -> None (503 branch)."""
        self._set_env(monkeypatch, backend="api", api_key="", binary_found=True)
        assert resolve_insights_client() is None

    def test_auto_prefers_cli_when_no_key_and_binary_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset backend, no key, binary present -> CLI client."""
        self._set_env(monkeypatch, backend="", api_key="", binary_found=True)
        assert isinstance(resolve_insights_client(), CliInsightsClient)

    def test_auto_prefers_api_when_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset backend with a key -> API client even if binary exists."""
        self._set_env(monkeypatch, backend="", api_key="sk-test", binary_found=True)
        assert isinstance(resolve_insights_client(), AnthropicInsightsClient)

    def test_auto_with_nothing_available_disables_feature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset backend, no key, no binary -> None (503 branch)."""
        self._set_env(monkeypatch, backend="", api_key="", binary_found=False)
        assert resolve_insights_client() is None
