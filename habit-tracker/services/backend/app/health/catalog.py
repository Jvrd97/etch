# [review:need-review] PHASE-02/64-health-vertical-two-metrics, PHASE-02/65, PHASE-03/238
# summary: the canonical Health catalog — 24 quantity metrics and sleep (a category type, in minutes asleep per night) — shared by runtime and test database seeding
"""
Seed rows of the metric catalogue.

The database remains the runtime source of truth. This tuple gives a fresh
database and tests the same baseline; adding a row directly to the database is
enough for the API to accept it immediately.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.health.aggregate import MetricKind


@dataclass(frozen=True)
class MetricSeed:
    identifier: str
    kind: MetricKind
    canonical_unit: str
    display_name: str
    group: str


# Group ids are stable slugs; the screen decides how to title them.
GROUP_MOVEMENT = "movement"
GROUP_HEART = "heart"
GROUP_BODY = "body"
GROUP_NUTRITION = "nutrition"
GROUP_SLEEP = "sleep"

SLEEP_IDENTIFIER = "HKCategoryTypeIdentifierSleepAnalysis"

SEED_METRICS: tuple[MetricSeed, ...] = (
    MetricSeed(
        identifier="HKQuantityTypeIdentifierStepCount",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="count",
        display_name="Шаги",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierDistanceWalkingRunning",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="m",
        display_name="Дистанция ходьбы и бега",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierFlightsClimbed",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="count",
        display_name="Этажи",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierActiveEnergyBurned",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="kcal",
        display_name="Активная энергия",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierBasalEnergyBurned",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="kcal",
        display_name="Базальная энергия",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierAppleExerciseTime",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="min",
        display_name="Минуты тренировки",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierAppleStandTime",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="min",
        display_name="Время стоя",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierHeartRate",
        kind=MetricKind.DISCRETE,
        canonical_unit="count/min",
        display_name="Пульс",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierRestingHeartRate",
        kind=MetricKind.DISCRETE,
        canonical_unit="count/min",
        display_name="Пульс покоя",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierWalkingHeartRateAverage",
        kind=MetricKind.DISCRETE,
        canonical_unit="count/min",
        display_name="Средний пульс при ходьбе",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
        kind=MetricKind.DISCRETE,
        canonical_unit="ms",
        display_name="Вариабельность пульса (SDNN)",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierRespiratoryRate",
        kind=MetricKind.DISCRETE,
        canonical_unit="count/min",
        display_name="Частота дыхания",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierOxygenSaturation",
        kind=MetricKind.DISCRETE,
        canonical_unit="%",
        display_name="Сатурация",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierVO2Max",
        kind=MetricKind.DISCRETE,
        canonical_unit="mL/(kg*min)",
        display_name="VO2max",
        group=GROUP_HEART,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierBodyMass",
        kind=MetricKind.DISCRETE,
        canonical_unit="kg",
        display_name="Вес",
        group=GROUP_BODY,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierBodyFatPercentage",
        kind=MetricKind.DISCRETE,
        canonical_unit="%",
        display_name="Процент жира",
        group=GROUP_BODY,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierLeanBodyMass",
        kind=MetricKind.DISCRETE,
        canonical_unit="kg",
        display_name="Мышечная масса",
        group=GROUP_BODY,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierBodyMassIndex",
        kind=MetricKind.DISCRETE,
        canonical_unit="count",
        display_name="Индекс массы тела",
        group=GROUP_BODY,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierHeight",
        kind=MetricKind.DISCRETE,
        canonical_unit="cm",
        display_name="Рост",
        group=GROUP_BODY,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierDietaryEnergyConsumed",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="kcal",
        display_name="Съеденные калории",
        group=GROUP_NUTRITION,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierDietaryProtein",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="g",
        display_name="Белки",
        group=GROUP_NUTRITION,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierDietaryFatTotal",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="g",
        display_name="Жиры",
        group=GROUP_NUTRITION,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierDietaryCarbohydrates",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="g",
        display_name="Углеводы",
        group=GROUP_NUTRITION,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierDietaryWater",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="mL",
        display_name="Вода",
        group=GROUP_NUTRITION,
    ),
    # A category type: its day value is minutes asleep of the night that ended
    # that day; stages, bedtime and wake time live in `health_sleep_nights`.
    MetricSeed(
        identifier=SLEEP_IDENTIFIER,
        kind=MetricKind.SLEEP,
        canonical_unit="min",
        display_name="Сон",
        group=GROUP_SLEEP,
    ),
)
