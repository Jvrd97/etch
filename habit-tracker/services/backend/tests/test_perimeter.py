"""
Tests for the API perimeter: prod-time configuration checks, the CORS
allowlist, and the key comparison that used to blow up on a non-ASCII header.

None of these tests touch the database on purpose: every one of them is about
what happens before a request reaches a handler, and a perimeter test that
needs postgres to run is a perimeter test that stops being run.
"""

# [review:need-review] PHASE-03/106, PHASE-03/109
# summary: startup refusal in prod (empty key, "*" origin), CORS allowlist, non-ASCII key header -> 401, once-only dev warning
# summary: prod settings now also carry SESSION_SECRET — the browser-session secret is part of the same perimeter (its own refusal lives in test_session_auth.py)
from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient

from app.core import auth
from app.core.auth import require_api_key, warn_if_auth_disabled
from app.core.config import PerimeterError, Settings
from app.main import create_app

PROTECTED_URL = "/api/v1/categories"
FRONTEND_ORIGIN = "http://habit.tailnet:3000"
FOREIGN_ORIGIN = "http://evil.example"
PROD_KEY = "prod-key-for-tests-only"
PROD_SESSION_SECRET = "prod-session-secret-for-tests-only"


def prod_settings(**overrides: object) -> Settings:
    """Settings for a production process, with the two perimeter values valid."""
    values: dict[str, object] = {
        "ENVIRONMENT": "prod",
        "API_KEY": PROD_KEY,
        "SESSION_SECRET": PROD_SESSION_SECRET,
        "CORS_ORIGINS": [FRONTEND_ORIGIN],
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]  # BaseSettings takes **kwargs


# --- startup refusal -------------------------------------------------------


def test_prod_with_empty_api_key_refuses_to_start() -> None:
    with pytest.raises(PerimeterError, match="API_KEY"):
        prod_settings(API_KEY="")


def test_prod_with_wildcard_cors_refuses_to_start() -> None:
    with pytest.raises(PerimeterError, match="CORS_ORIGINS"):
        prod_settings(CORS_ORIGINS=["*"])


def test_prod_with_wildcard_among_other_origins_refuses_to_start() -> None:
    with pytest.raises(PerimeterError, match="CORS_ORIGINS"):
        prod_settings(CORS_ORIGINS=[FRONTEND_ORIGIN, "*"])


def test_prod_with_explicit_origins_and_a_key_starts() -> None:
    config = prod_settings()
    assert config.CORS_ORIGINS == [FRONTEND_ORIGIN]
    assert config.API_KEY == PROD_KEY


def test_dev_keeps_the_permissive_defaults() -> None:
    config = Settings(
        ENVIRONMENT="dev", API_KEY="", SESSION_SECRET="", CORS_ORIGINS=["*"]
    )
    assert config.CORS_ORIGINS == ["*"]
    assert config.docs_enabled is True


def test_prod_hides_the_api_schema() -> None:
    assert prod_settings().docs_enabled is False
    app = create_app(prod_settings())
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_cors_origins_come_from_a_comma_separated_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CORS_ORIGINS=a,b` must work in compose without JSON quoting."""
    monkeypatch.setenv("CORS_ORIGINS", f"{FRONTEND_ORIGIN}, http://other:3000")
    assert Settings().CORS_ORIGINS == [FRONTEND_ORIGIN, "http://other:3000"]


# --- CORS allowlist --------------------------------------------------------


@pytest.fixture(scope="function")
async def prod_client() -> AsyncGenerator[AsyncClient, None]:
    """Client for an app assembled with a production-like perimeter."""
    async with AsyncClient(
        app=create_app(prod_settings()), base_url="http://test"
    ) as ac:
        yield ac


async def _preflight(client: AsyncClient, origin: str) -> str | None:
    response = await client.options(
        PROTECTED_URL,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    return response.headers.get("access-control-allow-origin")


async def test_allowed_origin_passes_preflight(prod_client: AsyncClient) -> None:
    assert await _preflight(prod_client, FRONTEND_ORIGIN) == FRONTEND_ORIGIN


async def test_foreign_origin_is_not_allowed(prod_client: AsyncClient) -> None:
    assert await _preflight(prod_client, FOREIGN_ORIGIN) is None


# --- key comparison --------------------------------------------------------


async def test_non_ascii_api_key_header_returns_401(prod_client: AsyncClient) -> None:
    """
    Cyrillic in the header used to raise TypeError inside compare_digest.

    The header goes out as raw bytes: httpx refuses to encode a non-ASCII
    header value from `str`, while a real client (or curl) sends the bytes as
    they are and Starlette decodes them as latin-1.
    """
    response = await prod_client.get(
        PROTECTED_URL, headers=[(b"X-API-Key", "ключ".encode())]
    )
    assert response.status_code == 401


async def test_empty_key_lets_the_request_through_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev without a key keeps working: the dependency returns, nothing raises."""
    monkeypatch.setattr(auth.settings, "API_KEY", "")
    assert await require_api_key(None) is None


# --- the dev-mode warning --------------------------------------------------


def test_auth_disabled_warning_is_printed_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(auth.settings, "API_KEY", "")
    monkeypatch.setattr(auth, "_warned_auth_disabled", False)
    with caplog.at_level("WARNING", logger="app.core.auth"):
        warn_if_auth_disabled()
        warn_if_auth_disabled()
    assert len(caplog.records) == 1
    assert "DISABLED" in caplog.records[0].message


def test_no_warning_when_a_key_is_set(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(auth.settings, "API_KEY", PROD_KEY)
    monkeypatch.setattr(auth, "_warned_auth_disabled", False)
    with caplog.at_level("WARNING", logger="app.core.auth"):
        warn_if_auth_disabled()
    assert caplog.records == []


async def test_requests_do_not_warn_at_all(
    prod_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The warning belongs to startup; requests must stay silent."""
    with caplog.at_level("WARNING", logger="app.core.auth"):
        await prod_client.get(PROTECTED_URL)
    assert caplog.records == []
