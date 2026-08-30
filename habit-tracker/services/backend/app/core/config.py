# [review:need-review] PHASE-03/106, PHASE-03/107, PHASE-03/109, PHASE-03/111
# summary: ENVIRONMENT + CORS_ORIGINS allowlist; in prod an empty API_KEY or a "*" origin kills the start
# summary: APP_TIMEZONE + DAY_START_HOUR — the temporary source of the one day boundary, validated at build
# summary: SESSION_SECRET / SESSION_MAX_AGE_S / SESSION_COOKIE_SECURE — the browser session; an empty secret in prod kills the start the same way an empty API_KEY does
# summary: CHAT_CLAUDE_CONFIG_DIR + CHAT_CLI_CWD + CHAT_CONTEXT_MAX_CHARS — the isolation of a chat turn from the host configuration is configuration, not a constant
"""
Настройки приложения.

Два параметра рисуют периметр и потому проверяются здесь, а не доверяются
дисциплине: пустой `API_KEY` полностью выключает аутентификацию, а
`CORS_ORIGINS = ["*"]` разрешает вызывать API с любой страницы. В разработке
оба значения удобны, в проде недопустимы, поэтому `ENVIRONMENT=prod`
превращает удобное значение в отказ стартовать — вместо warning'а, который
никто не читает.

Списочные переменные окружения читаются как `a,b,c`, а не как JSON: строка
`CORS_ORIGINS=http://host:3000,http://other:3000` в compose-файле работает
без кавычек и скобок.
"""

from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource

LIST_ENV_SEPARATOR = ","
WILDCARD_ORIGIN = "*"

# Срок жизни сессионной куки по умолчанию — 30 суток.
DEFAULT_SESSION_MAX_AGE_S = 30 * 24 * 60 * 60

# Ключ подписи сессий в разработке, когда `SESSION_SECRET` пуст. Значение
# заведомо публичное: подделать куку с ним может кто угодно, и именно поэтому
# пустой `SESSION_SECRET` в проде роняет старт (`_enforce_prod_perimeter`).
DEV_SESSION_SECRET = "dev-insecure-session-secret"


class PerimeterError(RuntimeError):
    """
    Продовая конфигурация, которая оставила бы API открытым.

    Поднимается при сборке настроек, то есть до первого запроса: приложение
    не стартует, а не работает дырявым.
    """


class _EnvSource(EnvSettingsSource):
    """Источник переменных окружения, читающий списки как `a,b,c`, а не как JSON."""

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if isinstance(value, str) and field.annotation == list[str]:
            return [
                item.strip() for item in value.split(LIST_ENV_SEPARATOR) if item.strip()
            ]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class _DotEnvSource(_EnvSource, DotEnvSettingsSource):
    """То же правило для значений из `.env`."""


class Settings(BaseSettings):
    """
    Настройки приложения.
    Все параметры можно переопределить через переменные окружения.
    """

    # Where this process runs. "prod" turns dev conveniences into a hard failure.
    ENVIRONMENT: Literal["dev", "prod"] = "dev"

    # Database
    POSTGRES_USER: str = "habit_user"
    POSTGRES_PASSWORD: str = "habit_pass"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "habit_tracker"

    # Auth: empty string disables auth (dev only; refused when ENVIRONMENT=prod)
    API_KEY: str = ""

    # Browser origins allowed to call the API. "*" is a dev-only default and is
    # refused when ENVIRONMENT=prod; an empty list allows no browser origin at
    # all, which is the right answer for clients that are not browsers.
    CORS_ORIGINS: list[str] = [WILDCARD_ORIGIN]

    # Browser session (PHASE-03/109). The web client trades the key for a signed
    # HttpOnly cookie once and never holds the key again; every other client
    # keeps sending X-API-Key. An empty secret is a development convenience and
    # is refused when ENVIRONMENT=prod, exactly like an empty API_KEY.
    SESSION_SECRET: str = ""
    SESSION_MAX_AGE_S: int = Field(default=DEFAULT_SESSION_MAX_AGE_S, gt=0)
    # Attach `Secure` to the session cookie. True by default: a cookie without
    # it travels over plain HTTP. Set it to false only where the frontend is
    # served over http:// — inside a tailnet, which encrypts the transport
    # itself (ADR-0003), a Secure cookie would simply never be stored.
    SESSION_COOKIE_SECURE: bool = True

    # AI insights: empty string disables the api backend (endpoint returns 503)
    ANTHROPIC_API_KEY: str = ""

    # LLM backend: "cli" (claude CLI binary) or "api" (Anthropic API).
    # Empty = auto: cli when no API key and the binary is found, else api.
    LLM_BACKEND: Literal["", "cli", "api"] = ""

    # Chat (ADR-0017). A chat turn on the CLI backend runs under its own
    # configuration directory and inside a fixed empty working directory, never
    # under the host's `~/.claude`: otherwise the process loads the personal
    # CLAUDE.md, hooks, MCP servers and skills of whoever owns the machine —
    # measured at 52 555 prefix tokens per turn against 282 with them off. The
    # working directory doubles as the key of the CLI session file, which is
    # what `--resume` (#112) is looked up by, so it is a setting and not a
    # temporary directory picked per call.
    CHAT_CLAUDE_CONFIG_DIR: str = "/data/claude-chat"
    CHAT_CLI_CWD: str = "/data/claude-chat/workspace"
    # Ceiling on the day card #113 will put into the prompt. Declared here
    # already so that slice is code and not another pass over compose files.
    CHAT_CONTEXT_MAX_CHARS: int = Field(default=20_000, ge=1_000)

    # The one day boundary — see `app/core/daytime.py`. A day runs from
    # DAY_START_HOUR local wall clock to that hour of the next date, so a
    # moment at 00:30 belongs to the previous day. Temporary home: `#86` moves
    # the source into the versioned `day_rule_set` without changing the
    # signature of local_date().
    APP_TIMEZONE: str = "Europe/Berlin"
    DAY_START_HOUR: int = Field(default=4, ge=0, le=23)

    # API
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Habit Tracker API"
    VERSION: str = "1.0.0"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Подменяет env- и dotenv-источники на те, что понимают `a,b,c`."""
        return (
            init_settings,
            _EnvSource(settings_cls),
            _DotEnvSource(settings_cls),
            file_secret_settings,
        )

    @property
    def DATABASE_URL(self) -> str:
        """Синхронный URL для Alembic"""
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Асинхронный URL для SQLAlchemy"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def session_signing_secret(self) -> str:
        """
        Ключ, которым подписывается сессионная кука.

        В разработке `SESSION_SECRET` обычно пуст, и подписывать всё равно надо
        — иначе страница входа не работает из коробки. Подставляется заведомо
        публичный `DEV_SESSION_SECRET`; в проде пустое значение до этой строки
        не доживает, его отбивает `_enforce_prod_perimeter`.
        """
        return self.SESSION_SECRET or DEV_SESSION_SECRET

    @property
    def docs_enabled(self) -> bool:
        """
        Открыты ли `/docs`, `/redoc` и `openapi.json`.

        Swagger UI грузится браузером и не может послать `X-API-Key`, поэтому
        «закрыть ключом» для него не работает. В проде схема API выключается
        целиком (решение зафиксировано в `deploy/README.md`), в разработке
        остаётся.
        """
        return self.ENVIRONMENT != "prod"

    @field_validator("APP_TIMEZONE")
    @classmethod
    def _timezone_must_resolve(cls, value: str) -> str:
        """
        Проверяет пояс при сборке настроек, а не при первом вызове.

        Иначе опечатка в `APP_TIMEZONE` доживает до первого запроса и падает
        внутри `local_date()`. Та же проверка ловит контейнер без базы поясов:
        `zoneinfo` своей базы не имеет, поэтому `tzdata` стоит в основных
        зависимостях.
        """
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"APP_TIMEZONE={value!r} is not a known IANA zone "
                '(expected something like "Europe/Berlin")'
            ) from exc
        return value

    @model_validator(mode="after")
    def _enforce_prod_perimeter(self) -> "Settings":
        """В проде запрещает пустой ключ, пустой секрет сессий и звёздочку в CORS."""
        if self.ENVIRONMENT != "prod":
            return self
        if not self.API_KEY:
            raise PerimeterError(
                "API_KEY is empty while ENVIRONMENT=prod: that would disable "
                "authentication for every endpoint. Set API_KEY "
                "(generate one with: openssl rand -hex 32)."
            )
        if not self.SESSION_SECRET:
            raise PerimeterError(
                "SESSION_SECRET is empty while ENVIRONMENT=prod: browser "
                "sessions would be signed with a publicly known development "
                "key, so anyone could forge a session cookie and walk in "
                "without the API key. Set SESSION_SECRET "
                "(generate one with: openssl rand -hex 32)."
            )
        if WILDCARD_ORIGIN in self.CORS_ORIGINS:
            raise PerimeterError(
                f'CORS_ORIGINS contains "{WILDCARD_ORIGIN}" while ENVIRONMENT=prod: '
                "that would let a page on any site call the API from a browser. "
                "List the frontend origins explicitly, or leave CORS_ORIGINS empty."
            )
        return self


settings = Settings()
