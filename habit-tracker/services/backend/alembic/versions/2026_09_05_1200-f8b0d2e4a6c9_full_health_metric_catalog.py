# [review:need-review] PHASE-02/65
# summary: insert the 22 new Health metrics from an immutable 24-row snapshot and delete only those rows on downgrade
"""full Health metric catalog

Revision ID: f8b0d2e4a6c9
Revises: e7a9c1b3d5f8
Create Date: 2026-09-05 12:00:00.000000+00:00

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.selectable import TableClause


revision: str = "f8b0d2e4a6c9"
down_revision: str | None = "e7a9c1b3d5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Intentional copy: a production migration is an immutable snapshot and must not
# import runtime catalog code whose later edits would rewrite migration history.
# `tests/test_health_catalog_migration.py` keeps all five fields aligned today.
METRICS = [
    ("HKQuantityTypeIdentifierStepCount", "cumulative", "count", "Шаги", "movement"),
    (
        "HKQuantityTypeIdentifierDistanceWalkingRunning",
        "cumulative",
        "m",
        "Дистанция ходьбы и бега",
        "movement",
    ),
    (
        "HKQuantityTypeIdentifierFlightsClimbed",
        "cumulative",
        "count",
        "Этажи",
        "movement",
    ),
    (
        "HKQuantityTypeIdentifierActiveEnergyBurned",
        "cumulative",
        "kcal",
        "Активная энергия",
        "movement",
    ),
    (
        "HKQuantityTypeIdentifierBasalEnergyBurned",
        "cumulative",
        "kcal",
        "Базальная энергия",
        "movement",
    ),
    (
        "HKQuantityTypeIdentifierAppleExerciseTime",
        "cumulative",
        "min",
        "Минуты тренировки",
        "movement",
    ),
    (
        "HKQuantityTypeIdentifierAppleStandTime",
        "cumulative",
        "min",
        "Время стоя",
        "movement",
    ),
    ("HKQuantityTypeIdentifierHeartRate", "discrete", "count/min", "Пульс", "heart"),
    (
        "HKQuantityTypeIdentifierRestingHeartRate",
        "discrete",
        "count/min",
        "Пульс покоя",
        "heart",
    ),
    (
        "HKQuantityTypeIdentifierWalkingHeartRateAverage",
        "discrete",
        "count/min",
        "Средний пульс при ходьбе",
        "heart",
    ),
    (
        "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
        "discrete",
        "ms",
        "Вариабельность пульса (SDNN)",
        "heart",
    ),
    (
        "HKQuantityTypeIdentifierRespiratoryRate",
        "discrete",
        "count/min",
        "Частота дыхания",
        "heart",
    ),
    ("HKQuantityTypeIdentifierOxygenSaturation", "discrete", "%", "Сатурация", "heart"),
    ("HKQuantityTypeIdentifierVO2Max", "discrete", "mL/(kg*min)", "VO2max", "heart"),
    ("HKQuantityTypeIdentifierBodyMass", "discrete", "kg", "Вес", "body"),
    (
        "HKQuantityTypeIdentifierBodyFatPercentage",
        "discrete",
        "%",
        "Процент жира",
        "body",
    ),
    (
        "HKQuantityTypeIdentifierLeanBodyMass",
        "discrete",
        "kg",
        "Мышечная масса",
        "body",
    ),
    (
        "HKQuantityTypeIdentifierBodyMassIndex",
        "discrete",
        "count",
        "Индекс массы тела",
        "body",
    ),
    ("HKQuantityTypeIdentifierHeight", "discrete", "cm", "Рост", "body"),
    (
        "HKQuantityTypeIdentifierDietaryEnergyConsumed",
        "cumulative",
        "kcal",
        "Съеденные калории",
        "nutrition",
    ),
    ("HKQuantityTypeIdentifierDietaryProtein", "cumulative", "g", "Белки", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryFatTotal", "cumulative", "g", "Жиры", "nutrition"),
    (
        "HKQuantityTypeIdentifierDietaryCarbohydrates",
        "cumulative",
        "g",
        "Углеводы",
        "nutrition",
    ),
    ("HKQuantityTypeIdentifierDietaryWater", "cumulative", "mL", "Вода", "nutrition"),
]

ORIGINAL_IDENTIFIERS = {
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierRestingHeartRate",
}


def _table() -> TableClause:
    return sa.table(
        "health_metrics",
        sa.column("identifier", sa.String),
        sa.column("kind", sa.String),
        sa.column("canonical_unit", sa.String),
        sa.column("display_name", sa.String),
        sa.column("group", sa.String),
    )


def upgrade() -> None:
    metrics = _table()
    rows = [
        dict(
            zip(
                ("identifier", "kind", "canonical_unit", "display_name", "group"),
                metric,
            )
        )
        for metric in METRICS
        if metric[0] not in ORIGINAL_IDENTIFIERS
    ]
    # Plain INSERT is deliberate: an unexpected identifier collision means the
    # database no longer matches the assumed predecessor and must stop migration.
    op.execute(metrics.insert().values(rows))


def downgrade() -> None:
    metrics = _table()
    new_identifiers = [
        metric[0] for metric in METRICS if metric[0] not in ORIGINAL_IDENTIFIERS
    ]
    op.execute(metrics.delete().where(metrics.c.identifier.in_(new_identifiers)))
