# LLM через `claude` CLI на сервере: как устроено и как перенести

Рецепт, по которому в habit-tracker бэкенд ходит в LLM **не через Anthropic API**, а
шеллится в бинарь `claude`, запечённый в Docker-образ. Логин при этом в образ не
попадает — он приходит с хоста в рантайме.

Документ самодостаточный: сниппеты можно копировать в другой проект как есть.

## Когда это уместно

| Подходит | Не подходит |
| --- | --- |
| Редкие тяжёлые запросы (отчёт раз в день, онбординг-план) | Hot path, десятки RPS |
| Один пользователь / внутренний инструмент | Продакшен с реальным трафиком |
| Хочется не платить отдельно за API-токены | Нужны предсказуемые лимиты и SLA |

Главное ограничение: CLI ходит по подписке Claude Code, а не по API-биллингу. При
заметном трафике это упирается в rate limits и выходит за рамки обычного
использования подписки — там честнее `LLM_BACKEND=api`. Плюс каждый вызов
поднимает отдельный процесс Node: сотни миллисекунд на старт и заметная память.

## Архитектура

Четыре части, каждая переносится независимо:

1. **Абстракция бэкенда** — нейтральный `LLMClient.generate(prompt) -> str` и выбор
   реализации по настройке.
2. **CLI-адаптер** — subprocess к `claude -p` с промптом через stdin.
3. **Образ** — Node + `@anthropic-ai/claude-code` в Dockerfile, без кредов.
4. **Аутентификация и таймауты** — compose-переменные, тома логина, timeout
   веб-сервера.

## 1. Абстракция бэкенда

`app/llm/client.py`. Базовый класс намеренно нейтральный: `generate` принимает
полностью собранный промпт, доменное обрамление (системные инструкции, парсинг
ответа) остаётся на вызывающей стороне. Тесты мокают именно эту границу.

```python
INSIGHTS_MODEL = "claude-sonnet-5"
# Generous timeout: a month-of-data report or an onboarding plan is a long request.
LLM_TIMEOUT_SECONDS = 120.0
MAX_REPORT_TOKENS = 8192


class LLMError(Exception):
    """LLM call failed: upstream API error, timeout, or empty response."""


class LLMClient:
    model: str = INSIGHTS_MODEL

    async def generate(self, prompt: str) -> str:
        """Send the prompt to the backend and return the response text."""
        raise NotImplementedError
```

Выбор реализации — одна функция. Возврат `None` вместо исключения важен: это
означает «фича выключена», и API отдаёт 503, а не падает пятисоткой.

```python
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
```

Настройки (`app/core/config.py`, pydantic-settings):

```python
ANTHROPIC_API_KEY: str = ""
# LLM backend: "cli" (claude CLI binary) or "api" (Anthropic API).
LLM_BACKEND: Literal["", "cli", "api"] = ""
```

В роутере клиент подключается как зависимость, чтобы тесты могли её подменить:

```python
def get_llm_client() -> InsightsClient | None:
    """LLM client dependency; None when no backend is available."""
    return resolve_insights_client()
```

## 2. CLI-адаптер

`app/llm/cli.py` целиком:

```python
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
```

Четыре решения, которые легко потерять при копировании:

- **Промпт идёт в stdin, не в argv.** Отчёт за месяц — десятки килобайт, argv имеет
  системный лимит, и падение будет неочевидным.
- **`asyncio.create_subprocess_exec`, а не `subprocess.run`.** Блокирующий вызов на
  120 секунд заморозил бы весь event loop воркера.
- **В `LLMError` попадает только код возврата.** stderr и stdout эхом содержат
  промпт и данные пользователя — в логи им нельзя (в этом проекте это ещё и
  жёсткое правило про PII).
- **После таймаута `kill()` и `await wait()`.** Без второго вызова остаётся зомби-процесс.

Режим намеренно чистый: `-p --output-format text`, никаких инструментов и никакого
`--dangerously-skip-permissions`. Модель ничего не выполняет, только генерирует
текст. Если переносите с включёнными тулами — это уже совсем другой профиль риска,
и обёртку надо пересматривать целиком.

## 3. Dockerfile

Бинарь ставится глобально через npm; креды в образ **не** запекаются.

```dockerfile
# System dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node + claude CLI: LLM_BACKEND=cli shells out to `claude -p`, and
# resolve_insights_client() disables insights (503) when the binary is
# absent. Credentials are not baked in — the host's ~/.claude is mounted
# by docker-compose at runtime.
ENV NODE_MAJOR=22
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*
```

`curl` и `ca-certificates` обязательны — без них не отработает скрипт nodesource.

## 4. Аутентификация

Два способа, взаимозаменяемых.

### Вариант A: долгоживущий токен (рекомендуется для сервера)

```bash
claude setup-token          # на хосте, один раз
# → дописать в .env:
# CLAUDE_CODE_OAUTH_TOKEN=<токен>
```

```yaml
environment:
  # cli | api | empty (auto). cli shells out to the `claude` binary
  # baked into the image and uses the mounted host login below.
  LLM_BACKEND: ${LLM_BACKEND:-cli}
  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
  # Preferred auth on a headless server: `claude setup-token` on the
  # host, then export the long-lived token. Falls back to the mounted
  # ~/.claude login below when unset.
  CLAUDE_CODE_OAUTH_TOKEN: ${CLAUDE_CODE_OAUTH_TOKEN:-}
```

Не зависит от того, где именно CLI держит файлы логина, — на headless-сервере это
надёжнее варианта B.

### Вариант B: монтирование логина с хоста

На хосте один раз запустить `claude` и пройти вход, дальше:

```yaml
volumes:
  # claude CLI login from the host (run `claude` once there to log in).
  # Writable: the CLI refreshes tokens and updates its config in place.
  - ${CLAUDE_CONFIG_DIR:-${HOME}/.claude}:/root/.claude
  - ${HOME}/.claude.json:/root/.claude.json
```

Грабли: **`~/.claude.json` должен существовать на хосте до `up`**, иначе Docker
создаст на его месте директорию, и CLI не поднимется. Тома монтируются на запись —
CLI обновляет токены на месте.

Вторые грабли, prod-специфичные: compose мержит списки томов по target, поэтому
`volumes: []` в оверрайде **не** убирает bind-mount из базового файла. Если в prod
нужно «запускаться из образа без live-reload», убирать монтирование исходников надо
иначе.

## 5. Таймауты

```
gunicorn ... --timeout 180     # prod
LLM_TIMEOUT_SECONDS = 120.0    # app/llm/client.py
```

Правило: **таймаут воркера строго больше таймаута LLM.** Генерация отчёта за 30
дней — один длинный синхронный запрос; более короткий воркер-таймаут убьёт его
раньше, чем CLI успеет ответить, и наружу это выглядит как случайная 502.

В prod-компоуз стоит вписать это прямо комментарием рядом с командой — связь между
двумя числами в разных файлах иначе теряется при первом же рефакторинге.

## Чеклист переноса

1. Скопировать `app/llm/client.py` и `app/llm/cli.py`. Если API-бэкенд не нужен —
   достаточно `LLMClient`, `LLMError`, `LLM_TIMEOUT_SECONDS` и `CliInsightsClient`.
2. Добавить в настройки `LLM_BACKEND` и `ANTHROPIC_API_KEY`.
3. Добавить в Dockerfile блок Node 22 + `@anthropic-ai/claude-code` (+ `curl`,
   `ca-certificates`).
4. В compose прописать `LLM_BACKEND=cli`, `CLAUDE_CODE_OAUTH_TOKEN` и/или два тома
   логина.
5. Поднять таймаут веб-сервера выше `LLM_TIMEOUT_SECONDS`.
6. Убедиться, что роутер корректно обрабатывает `None` от резолвера (503, не 500).

## Проверка после `up`

```bash
docker compose exec backend claude --version
echo "Reply with exactly: OK" | docker compose exec -T backend claude -p --output-format text
```

Если вторая команда возвращает `Not logged in`, аутентификация не проброшена:
эндпоинт будет отдавать 503 (`no LLM backend available`) или 502. Флаг `-T` во
второй команде обязателен — без него docker выделяет TTY и stdin не прокидывается.
