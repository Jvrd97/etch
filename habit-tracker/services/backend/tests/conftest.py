"""
Test configuration and fixtures.
"""

# [review:need-review] PHASE-01/13-backend-uv-mypy-ruff, PHASE-03/86, PHASE-03/93
# summary: env-overridable TEST_DATABASE_URL + typed fixtures (builtin generics); the published day boundary is reset between tests; `seeded_goal` puts goal 1 of the quarter in the table so the plans that name it satisfy the foreign key; the three categories a quick-mark button can stand on live here because two test modules press the same buttons
import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import daytime
from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.goal import QuarterGoal

# Test database URL: default targets the docker-compose network ("postgres"
# host); override via env for local runs (e.g. localhost:5432).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://habit_user:habit_pass@postgres:5432/habit_tracker_test",
)

# API key used by all tests; injected into settings and client headers
TEST_API_KEY = "test-api-key-for-tests-only"


# Create test engine
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, echo=False)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=True)
def api_key() -> Generator[str, None, None]:
    """Enable API-key auth for every test; restore original value afterwards."""
    original = settings.API_KEY
    settings.API_KEY = TEST_API_KEY
    yield TEST_API_KEY
    settings.API_KEY = original


@pytest.fixture(scope="function", autouse=True)
def day_boundary() -> Generator[None, None, None]:
    """
    Forget the day boundary published from `day_rule_set` after every test.

    It lives in a module-level variable of `app.core.daytime` — process-wide by
    design, so that nine consumers cannot disagree about which day it is — and a
    rule row inserted by one test would otherwise decide what "today" means for
    every test that runs after it.
    """
    daytime.reset_boundary()
    yield
    daytime.reset_boundary()


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a clean database session for each test."""
    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="function")
async def seeded_goal(db_session: AsyncSession) -> AsyncGenerator[int, None]:
    """
    The goal of the quarter every test plan points at, under the id it points at.

    The tests of the plan write `quarter_goal_id=1` because that is what a real
    plan carries, and `#93` gave the column its foreign key. The id is spelled
    out rather than taken from the sequence: the tests name the number, and a
    fixture returning 7 would make them all pass by accident of ordering.
    """
    goal = QuarterGoal(
        id=1,
        quarter="2026-Q3",
        ord=1,
        text_md="Денежный контур Talvior работает end-to-end.",
    )
    db_session.add(goal)
    await db_session.flush()
    yield goal.id


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with database session override."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        app=app,
        base_url="http://test",
        follow_redirects=True,
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def water(client: AsyncClient) -> dict[str, Any]:
    """A form category with one number field — the «+250 мл» case."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Вода",
            "display_mode": "form",
            "fields": [{"name": "Объём", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
async def vitamins(client: AsyncClient) -> dict[str, Any]:
    """A checklist category with one boolean field."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Витамины",
            "display_mode": "checklist",
            "fields": [{"name": "D3", "field_type": "boolean", "order": 1}],
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
async def smoking(client: AsyncClient) -> dict[str, Any]:
    """An avoid category — the one a relapse button is allowed on."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Курение",
            "display_mode": "form",
            "streak_mode": "avoid",
            "fields": [{"name": "Штук", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201
    return response.json()
