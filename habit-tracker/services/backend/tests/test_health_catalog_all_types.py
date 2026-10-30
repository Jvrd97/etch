# [review:need-review] PHASE-03/272
# summary: the catalogue holds every HealthKit type except cycle tracking — the exclusion list pinned, every category row one the server can fold into hours, and the three catalogue migrations together equal the runtime seed, the last one inserting only its own rows and deleting only them on downgrade
"""
The whole Apple Health catalogue, minus cycle tracking (#272).

The owner's rule: every metric HealthKit gives on iPhone and Watch, except the
"Cycle Tracking" section. The list below is that section; neither the server
nor the phone (`HealthMetricCatalogTests`) may carry any of it.
"""

from importlib import util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Delete, Insert

from app.health.aggregate import MetricKind
from app.health.catalog import SEED_METRICS

CYCLE_TRACKING = {
    "HKCategoryTypeIdentifierMenstrualFlow",
    "HKCategoryTypeIdentifierIntermenstrualBleeding",
    "HKCategoryTypeIdentifierInfrequentMenstrualCycles",
    "HKCategoryTypeIdentifierIrregularMenstrualCycles",
    "HKCategoryTypeIdentifierPersistentIntermenstrualBleeding",
    "HKCategoryTypeIdentifierProlongedMenstrualPeriods",
    "HKCategoryTypeIdentifierOvulationTestResult",
    "HKCategoryTypeIdentifierCervicalMucusQuality",
    "HKCategoryTypeIdentifierProgesteroneTestResult",
    "HKCategoryTypeIdentifierPregnancyTestResult",
    "HKCategoryTypeIdentifierPregnancy",
    "HKCategoryTypeIdentifierLactation",
    "HKCategoryTypeIdentifierContraceptive",
    "HKCategoryTypeIdentifierSexualActivity",
    "HKCategoryTypeIdentifierBleedingDuringPregnancy",
    "HKCategoryTypeIdentifierBleedingAfterPregnancy",
    # HealthKit files basal body temperature under reproductive health, and the
    # Health app shows it in Cycle Tracking.
    "HKQuantityTypeIdentifierBasalBodyTemperature",
}

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
QUANTITY_MIGRATION = "2026_09_05_1200-f8b0d2e4a6c9_full_health_metric_catalog.py"
SLEEP_MIGRATION = "2026_10_30_1000-4359c5a3d24e_health_sleep_nights.py"
ALL_TYPES_MIGRATION = "2026_10_30_1200-b55c9394752b_health_all_metrics_except_cycle.py"

Row = tuple[str, str, str, str, str]


def load(name: str) -> ModuleType:
    spec = util.spec_from_file_location(name.removesuffix(".py"), VERSIONS / name)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_rows() -> list[Row]:
    return [
        (m.identifier, m.kind.value, m.canonical_unit, m.display_name, m.group)
        for m in SEED_METRICS
    ]


def test_no_cycle_tracking_type_is_in_the_catalogue() -> None:
    assert {m.identifier for m in SEED_METRICS} & CYCLE_TRACKING == set()


def test_every_identifier_is_listed_once() -> None:
    identifiers = [m.identifier for m in SEED_METRICS]

    assert len(identifiers) == len(set(identifiers))


def test_every_category_type_but_sleep_folds_into_minutes_or_counts() -> None:
    categories = [
        m for m in SEED_METRICS if m.identifier.startswith("HKCategoryTypeIdentifier")
    ]

    assert len(categories) > 1
    for metric in categories:
        if metric.kind is MetricKind.SLEEP:
            continue
        assert metric.kind is MetricKind.CUMULATIVE, metric.identifier
        assert metric.canonical_unit in {"min", "count"}, metric.identifier


def test_the_catalogue_migrations_together_equal_the_runtime_seed() -> None:
    sleep = load(SLEEP_MIGRATION).SLEEP_ROW
    migrated: list[Row] = [
        *load(QUANTITY_MIGRATION).METRICS,
        (
            sleep["identifier"],
            sleep["kind"],
            sleep["canonical_unit"],
            sleep["display_name"],
            sleep["group"],
        ),
        *load(ALL_TYPES_MIGRATION).METRICS,
    ]

    assert sorted(migrated) == sorted(seed_rows())


def test_upgrade_inserts_only_its_rows_and_downgrade_deletes_only_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load(ALL_TYPES_MIGRATION)
    executed: list[Insert | Delete] = []
    monkeypatch.setattr(migration.op, "execute", executed.append)
    own = {row[0] for row in migration.METRICS}
    earlier = {row[0] for row in load(QUANTITY_MIGRATION).METRICS} | {
        load(SLEEP_MIGRATION).SLEEP_ROW["identifier"]
    }

    migration.upgrade()
    migration.downgrade()

    insert, delete = executed
    inserted = {
        value
        for value in insert.compile(dialect=postgresql.dialect()).params.values()
        if isinstance(value, str) and value.startswith("HK")
    }
    deleted = {
        value
        for values in delete.compile(dialect=postgresql.dialect()).params.values()
        for value in (values if isinstance(values, list) else [values])
    }
    assert inserted == own
    assert deleted == own
    assert own & earlier == set()
    assert migration.down_revision == "4359c5a3d24e"
