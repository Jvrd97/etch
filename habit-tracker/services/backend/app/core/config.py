# [review:need-review] PHASE-03/106
# summary: ENVIRONMENT + CORS_ORIGINS allowlist; in prod an empty API_KEY or a "*" origin kills the start
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

from pydantic import model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource

LIST_ENV_SEPARATOR = ","
WILDCARD_ORIGIN = "*"


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

    # AI insights: empty string disables the api backend (endpoint returns 503)
    ANTHROPIC_API_KEY: str = ""

    # LLM backend: "cli" (claude CLI binary) or "api" (Anthropic API).
    # Empty = auto: cli when no API key and the binary is found, else api.
    LLM_BACKEND: Literal["", "cli", "api"] = ""

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
    def docs_enabled(self) -> bool:
        """
        Открыты ли `/docs`, `/redoc` и `openapi.json`.

        Swagger UI грузится браузером и не может послать `X-API-Key`, поэтому
        «закрыть ключом» для него не работает. В проде схема API выключается
        целиком (решение зафиксировано в `deploy/README.md`), в разработке
        остаётся.
        """
        return self.ENVIRONMENT != "prod"

    @model_validator(mode="after")
    def _enforce_prod_perimeter(self) -> "Settings":
        """В проде запрещает пустой ключ и звёздочку в CORS-allowlist."""
        if self.ENVIRONMENT != "prod":
            return self
        if not self.API_KEY:
            raise PerimeterError(
                "API_KEY is empty while ENVIRONMENT=prod: that would disable "
                "authentication for every endpoint. Set API_KEY "
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
