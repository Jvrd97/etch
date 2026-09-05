# [review:need-review] PHASE-02/65
# summary: the immutable migration snapshot matches runtime and inserts only its 22 genuinely new metrics

from importlib import util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

from app.health.catalog import SEED_METRICS

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/2026_09_05_1200-f8b0d2e4a6c9_full_health_metric_catalog.py"
)
ORIGINAL_IDENTIFIERS = {
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierRestingHeartRate",
}


@pytest.fixture
def migration() -> ModuleType:
    spec = util.spec_from_file_location("health_catalog_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_snapshot_matches_runtime_catalog(migration: ModuleType) -> None:
    runtime_snapshot = [
        (
            metric.identifier,
            metric.kind.value,
            metric.canonical_unit,
            metric.display_name,
            metric.group,
        )
        for metric in SEED_METRICS
    ]

    assert migration.METRICS == runtime_snapshot
    assert len(migration.METRICS) == 24


def test_upgrade_is_plain_insert_of_only_new_metrics(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    executed: list[Insert] = []
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    assert len(executed) == 1
    statement = executed[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    inserted_identifiers = {
        value
        for value in statement.compile(dialect=postgresql.dialect()).params.values()
        if isinstance(value, str) and value.startswith("HKQuantityTypeIdentifier")
    }
    assert "ON CONFLICT" not in sql
    assert inserted_identifiers == {
        metric.identifier
        for metric in SEED_METRICS
        if metric.identifier not in ORIGINAL_IDENTIFIERS
    }
    assert len(inserted_identifiers) == 22
