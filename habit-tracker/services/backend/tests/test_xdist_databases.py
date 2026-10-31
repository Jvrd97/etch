"""
Each pytest-xdist worker runs in its own database (#285).
"""

# [review:need-review] PHASE-03/285
# summary: worker_database_url derives `<name>_<worker>` from TEST_DATABASE_URL and leaves a single-process run untouched; the live engine matches the worker it runs in

import os

import pytest

from tests.conftest import (
    TEST_DATABASE_URL,
    XDIST_WORKER_ENV,
    test_engine,
    worker_database_url,
)

BASE = "postgresql+asyncpg://habit_user:habit_pass@localhost:55432/habit_test_285"


def test_worker_database_gets_its_own_name() -> None:
    assert worker_database_url(BASE, "gw3") == (
        "postgresql+asyncpg://habit_user:habit_pass@localhost:55432/habit_test_285_gw3"
    )


@pytest.mark.parametrize("worker", [None, ""])
def test_single_process_run_keeps_the_url_as_is(worker: str | None) -> None:
    assert worker_database_url(BASE, worker) == BASE


def test_worker_database_keeps_a_password_with_reserved_characters() -> None:
    base = (
        "postgresql+asyncpg://habit_user:p%40ss%2Fword@localhost:55432/habit_test_285"
    )
    assert worker_database_url(base, "gw0").startswith(
        "postgresql+asyncpg://habit_user:p%40ss%2Fword@localhost:55432/"
    )


def test_engine_of_this_process_matches_its_worker() -> None:
    worker = os.environ.get(XDIST_WORKER_ENV)
    name = test_engine.url.database
    assert name is not None
    assert TEST_DATABASE_URL.endswith(f"/{name}")
    if worker:
        assert name.endswith(f"_{worker}")
    else:
        assert not name.endswith("_gw0")
