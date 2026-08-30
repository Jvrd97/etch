"""
Tests for API-key authentication (X-API-Key header).
"""

# [review:need-review] PHASE-01/01-backend-api-key-auth
# summary: API-level tests for require_api_key dependency (401/200, dev-mode off, no key in logs)
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.main import app

PROTECTED_URL = "/api/v1/categories"


@pytest.fixture(scope="function")
async def bare_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test client WITHOUT the default X-API-Key header."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        app=app, base_url="http://test", follow_redirects=True
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def test_missing_api_key_returns_401(bare_client: AsyncClient) -> None:
    response = await bare_client.get(PROTECTED_URL)
    assert response.status_code == 401


async def test_wrong_api_key_returns_401(bare_client: AsyncClient) -> None:
    response = await bare_client.get(
        PROTECTED_URL, headers={"X-API-Key": "definitely-wrong-key"}
    )
    assert response.status_code == 401


async def test_valid_api_key_returns_200(
    bare_client: AsyncClient, api_key: str
) -> None:
    response = await bare_client.get(PROTECTED_URL, headers={"X-API-Key": api_key})
    assert response.status_code == 200


async def test_empty_api_key_env_disables_auth(
    bare_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Dev mode keeps working without a key — and stays quiet while doing it.

    The warning about disabled auth moved to startup in PHASE-03/106, so the
    per-request line this test used to assert is gone on purpose. Its
    once-only replacement is checked in `tests/test_perimeter.py`.
    """
    settings.API_KEY = ""  # autouse api_key fixture restores the value on teardown
    with caplog.at_level("WARNING", logger="app.core.auth"):
        response = await bare_client.get(PROTECTED_URL)
    assert response.status_code == 200
    assert caplog.records == []


async def test_api_key_value_is_never_logged(
    bare_client: AsyncClient, api_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        await bare_client.get(PROTECTED_URL, headers={"X-API-Key": api_key})
        await bare_client.get(PROTECTED_URL, headers={"X-API-Key": "wrong-key-value"})
        await bare_client.get(PROTECTED_URL)
    assert api_key not in caplog.text
    assert "wrong-key-value" not in caplog.text
