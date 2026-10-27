# [review:need-review] PHASE-03/254
# summary: the metric kinds and canonical units in tests/fixtures/health/metric_catalog.json equal the seeded catalogue; the iOS catalogue test reads the same file
"""
Shared fixture of metric kinds and canonical units.

`HealthSampleMappingTests.testCatalogKindsAndUnitsMatchTheServerFixture` on the
iOS side reads this file. The server catalogue changes here first; the fixture
follows, and the iOS test then names every metric whose kind or unit drifted.
"""

import json
from pathlib import Path

from app.health.aggregate import _UNITS
from app.health.catalog import SEED_METRICS

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "health" / "metric_catalog.json"


def test_fixture_equals_the_seeded_catalogue() -> None:
    seeded = [
        {
            "identifier": metric.identifier,
            "kind": metric.kind.value,
            "canonical_unit": metric.canonical_unit,
        }
        for metric in SEED_METRICS
    ]

    assert json.loads(FIXTURE_PATH.read_text(encoding="utf-8")) == seeded


def test_every_canonical_unit_is_one_the_converter_knows() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert {row["canonical_unit"] for row in fixture} <= set(_UNITS)
