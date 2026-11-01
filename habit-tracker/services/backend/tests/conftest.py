"""
Test configuration and fixtures.
"""

# [review:need-review] PHASE-01/13-backend-uv-mypy-ruff, PHASE-03/86, PHASE-03/93, PHASE-03/120, PHASE-03/218, PHASE-03/285
# summary: env-overridable TEST_DATABASE_URL + typed fixtures (builtin generics); the published day boundary is reset between tests; the isolated-CLI paths point at a tmp dir so no test writes to /data; `seeded_goal` puts goal 1 of today's quarter (computed, not frozen as `2026-Q3` — `#218`) in the table so the plans that name it satisfy the foreign key; the three categories a quick-mark button can stand on live here because two test modules press the same buttons; under pytest-xdist each worker gets its own database (`<name>_gw0`, ...) created at session start and dropped at its end (PHASE-03/285)
# [review:need-review] 309
# summary: the `sql_counter` fixture — statements and rows read by the database inside a `with` block, for the tests that hold the number of queries and of rows flat as data grows
import asyncio
import os
from collections.abc import AsyncGenerator, Callable, Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import daytime
from app.crud import goal as goal_crud
from app.crud import role as role_crud
from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.goal import QuarterGoal
from app.models.role import ROLE_CODE_ARCHITECT

# Test database URL: default targets the docker-compose network ("postgres"
# host); override via env for local runs (e.g. localhost:5432).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://habit_user:habit_pass@postgres:5432/habit_tracker_test",
)

# xdist sets this in every worker process before conftest is imported; it is
# absent in a single-process run, with `-p no:xdist` and in the xdist controller.
XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"
MAINTENANCE_DATABASE = "postgres"


def worker_database_url(base_url: str, worker: str | None) -> str:
    """Give each xdist worker its own database: `<name>_<worker>`; no worker, no change."""
    if not worker:
        return base_url
    url = make_url(base_url)
    return url.set(database=f"{url.database}_{worker}").render_as_string(
        hide_password=False
    )


WORKER = os.environ.get(XDIST_WORKER_ENV)
TEST_DATABASE_URL = worker_database_url(TEST_DATABASE_URL, WORKER)

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


async def _run_database_statement(url: str, statement: str) -> None:
    """Run one DDL statement on the server's maintenance database."""
    parsed = make_url(url)
    connection = await asyncpg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        database=MAINTENANCE_DATABASE,
    )
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


def _database_statement(statement: str) -> None:
    # A private loop: the session loop of pytest-asyncio does not exist yet here.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_database_statement(TEST_DATABASE_URL, statement))
    finally:
        loop.close()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Create this xdist worker's database; fail loudly instead of sharing one."""
    if not WORKER:
        return
    name = make_url(TEST_DATABASE_URL).database
    try:
        _database_statement(f'CREATE DATABASE "{name}"')
    except asyncpg.DuplicateDatabaseError:
        pass  # left by an interrupted run; the schema is rebuilt before every test
    except asyncpg.InsufficientPrivilegeError as error:
        pytest.exit(
            f"xdist worker {WORKER} needs CREATE DATABASE for its own database "
            f"{name!r}: grant it to the test role or run without -n ({error})",
            returncode=3,
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Drop this xdist worker's database."""
    if not WORKER:
        return
    name = make_url(TEST_DATABASE_URL).database
    _database_statement(f'DROP DATABASE IF EXISTS "{name}"')


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


@pytest.fixture(scope="function", autouse=True)
def isolated_cli_paths(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[None, None, None]:
    """
    Каталог конфигурации и рабочий каталог `claude` — временные на время теста.

    Их прод-значения лежат в `/data`, который на машине разработчика создать
    нельзя; а запуск CLI создаёт рабочий каталог перед стартом процесса. Без
    подмены любой тест, дошедший до сборки запуска, упирался бы в права на
    корень файловой системы вместо того, что он проверяет.
    """
    root = tmp_path_factory.mktemp("claude-cli")
    original_config_dir = settings.CHAT_CLAUDE_CONFIG_DIR
    original_cwd = settings.CHAT_CLI_CWD
    settings.CHAT_CLAUDE_CONFIG_DIR = str(root / "config")
    settings.CHAT_CLI_CWD = str(root / "workspace")
    yield
    settings.CHAT_CLAUDE_CONFIG_DIR = original_config_dir
    settings.CHAT_CLI_CWD = original_cwd


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


@dataclass
class SqlCount:
    """What the database was asked inside one `with sql_counter():` block."""

    statements: list[str] = field(default_factory=list)
    # `cursor.rowcount` of each statement, in the same order: rows returned by a
    # SELECT, touched by a write.
    row_counts: list[int] = field(default_factory=list)

    @property
    def queries(self) -> int:
        return len(self.statements)

    @property
    def rows(self) -> int:
        return sum(self.row_counts)

    def rows_of(self, table: str) -> list[int]:
        """Rows of each statement whose text names `table`."""
        return [
            rows
            for statement, rows in zip(self.statements, self.row_counts)
            if table in statement
        ]


SqlCounter = Callable[[], AbstractContextManager[SqlCount]]


@contextmanager
def _count_sql() -> Iterator[SqlCount]:
    seen = SqlCount()

    def before(*args: Any) -> None:
        seen.statements.append(str(args[2]))

    def after(*args: Any) -> None:
        seen.row_counts.append(max(args[1].rowcount, 0))

    engine = test_engine.sync_engine
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)


@pytest.fixture
def sql_counter() -> SqlCounter:
    """
    Count statements and rows: `with sql_counter() as seen: ...; seen.queries, seen.rows`.

    For the tests of the class «grows with data»: the same read on N and on
    10·N rows must ask as many statements, and a narrowed read must not pull
    the rows it then throws away. BEGIN and COMMIT are not statements here.
    """
    return _count_sql


@pytest.fixture(scope="function")
async def seeded_goal(db_session: AsyncSession) -> AsyncGenerator[int, None]:
    """
    The goal of the quarter every test plan points at, under the id it points at.

    The tests of the plan write `quarter_goal_id=1` because that is what a real
    plan carries, and `#93` gave the column its foreign key. The id is spelled
    out rather than taken from the sequence: the tests name the number, and a
    fixture returning 7 would make them all pass by accident of ordering.

    The quarter itself is today's, computed the same way `GET /goals` computes
    it (`#218`): a fixed `"2026-Q3"` went stale the moment the calendar crossed
    into Q4 and a plan written for "today" could no longer name a goal of
    "today's" quarter.
    """
    goal = QuarterGoal(
        id=1,
        quarter=goal_crud.quarter_code(daytime.today_local()),
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


async def record_role_act(
    db: AsyncSession,
    on: date,
    *,
    role_code: str = ROLE_CODE_ARCHITECT,
    act_kind: str = "adr_written",
    title: str = "ADR-0020: роли как измеряемая величина",
) -> None:
    """
    Закрыть клауз роли (`#137`) для одного дня.

    Помощник, а не фикстура: клауз нужен ровно тем тестам, которые ждут
    выигранный рабочий день, и включать его во все подряд значило бы прятать в
    автоиспользуемой фикстуре условие, которое эти тесты и проверяют.

    Пишет через crud, а не через ручку: тесту вердикта нужен факт в таблице, а
    не проверка контракта `POST /role-acts` — её делает `test_roles.py`.
    """
    await role_crud.seed_roles(db)
    role = await role_crud.get_role_by_code(db, role_code)
    assert role is not None, "справочник ролей не засеян"
    await role_crud.write_act(
        db,
        role_crud.ActDraft(
            work_day=on,
            role_id=role.id,
            act_kind=act_kind,
            title=title,
        ),
    )
    await db.flush()
