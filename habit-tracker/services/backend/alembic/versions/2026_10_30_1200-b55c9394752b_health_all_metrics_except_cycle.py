"""health catalogue: every HealthKit type except cycle tracking

Revision ID: b55c9394752b
Revises: 4359c5a3d24e
Create Date: 2026-10-30 12:00:00.000000+00:00
"""

# [review:need-review] PHASE-03/272
# summary: reversible — inserts the 147 catalogue rows #272 adds (95 quantity types, 52 category types in minutes or counts per hour, nothing from cycle tracking) and deletes exactly those rows on downgrade; their hourly buckets go with them by the foreign key's cascade

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b55c9394752b"
down_revision: str | None = "4359c5a3d24e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot, not an import of `app.health.catalog`: a migration must not change
# when the runtime catalogue does. `tests/test_health_catalog_all_types.py`
# checks that the catalogue migrations together equal the runtime seed today.
# (identifier, kind, canonical_unit, display_name, group)
METRICS: list[tuple[str, str, str, str, str]] = [
    ("HKQuantityTypeIdentifierAppleMoveTime", "cumulative", "min", "Минуты движения", "movement"),
    ("HKQuantityTypeIdentifierTimeInDaylight", "cumulative", "min", "Время на дневном свете", "movement"),
    ("HKQuantityTypeIdentifierDistanceCycling", "cumulative", "m", "Дистанция на велосипеде", "movement"),
    ("HKQuantityTypeIdentifierDistanceWheelchair", "cumulative", "m", "Дистанция на кресле-коляске", "movement"),
    ("HKQuantityTypeIdentifierPushCount", "cumulative", "count", "Толчки кресла-коляски", "movement"),
    ("HKQuantityTypeIdentifierDistanceSwimming", "cumulative", "m", "Дистанция в плавании", "movement"),
    ("HKQuantityTypeIdentifierSwimmingStrokeCount", "cumulative", "count", "Гребки в плавании", "movement"),
    ("HKQuantityTypeIdentifierDistanceDownhillSnowSports", "cumulative", "m", "Дистанция на горных лыжах и сноуборде", "movement"),
    ("HKQuantityTypeIdentifierDistanceCrossCountrySkiing", "cumulative", "m", "Дистанция на беговых лыжах", "movement"),
    ("HKQuantityTypeIdentifierDistancePaddleSports", "cumulative", "m", "Дистанция на каяке и SUP", "movement"),
    ("HKQuantityTypeIdentifierDistanceRowing", "cumulative", "m", "Дистанция гребли", "movement"),
    ("HKQuantityTypeIdentifierDistanceSkatingSports", "cumulative", "m", "Дистанция на коньках", "movement"),
    ("HKQuantityTypeIdentifierNikeFuel", "cumulative", "count", "NikeFuel", "movement"),
    ("HKQuantityTypeIdentifierPhysicalEffort", "discrete", "kcal/(kg*hr)", "Физическая нагрузка", "movement"),
    ("HKQuantityTypeIdentifierWorkoutEffortScore", "discrete", "appleEffortScore", "Оценка нагрузки тренировки", "movement"),
    ("HKQuantityTypeIdentifierEstimatedWorkoutEffortScore", "discrete", "appleEffortScore", "Расчётная нагрузка тренировки", "movement"),
    ("HKQuantityTypeIdentifierRunningSpeed", "discrete", "m/s", "Скорость бега", "movement"),
    ("HKQuantityTypeIdentifierRunningPower", "discrete", "W", "Мощность бега", "movement"),
    ("HKQuantityTypeIdentifierRunningStrideLength", "discrete", "m", "Длина шага при беге", "movement"),
    ("HKQuantityTypeIdentifierRunningVerticalOscillation", "discrete", "cm", "Вертикальные колебания при беге", "movement"),
    ("HKQuantityTypeIdentifierRunningGroundContactTime", "discrete", "ms", "Время контакта с землёй при беге", "movement"),
    ("HKQuantityTypeIdentifierCyclingSpeed", "discrete", "m/s", "Скорость на велосипеде", "movement"),
    ("HKQuantityTypeIdentifierCyclingPower", "discrete", "W", "Мощность на велосипеде", "movement"),
    ("HKQuantityTypeIdentifierCyclingFunctionalThresholdPower", "discrete", "W", "Функциональная пороговая мощность", "movement"),
    ("HKQuantityTypeIdentifierCyclingCadence", "discrete", "count/min", "Каденс на велосипеде", "movement"),
    ("HKQuantityTypeIdentifierCrossCountrySkiingSpeed", "discrete", "m/s", "Скорость на беговых лыжах", "movement"),
    ("HKQuantityTypeIdentifierPaddleSportsSpeed", "discrete", "m/s", "Скорость на каяке и SUP", "movement"),
    ("HKQuantityTypeIdentifierRowingSpeed", "discrete", "m/s", "Скорость гребли", "movement"),
    ("HKQuantityTypeIdentifierUnderwaterDepth", "discrete", "m", "Глубина под водой", "movement"),
    ("HKQuantityTypeIdentifierWaterTemperature", "discrete", "degC", "Температура воды", "movement"),
    ("HKQuantityTypeIdentifierWalkingSpeed", "discrete", "m/s", "Скорость ходьбы", "mobility"),
    ("HKQuantityTypeIdentifierWalkingStepLength", "discrete", "cm", "Длина шага", "mobility"),
    ("HKQuantityTypeIdentifierWalkingAsymmetryPercentage", "discrete", "%", "Асимметрия ходьбы", "mobility"),
    ("HKQuantityTypeIdentifierWalkingDoubleSupportPercentage", "discrete", "%", "Время двойной опоры", "mobility"),
    ("HKQuantityTypeIdentifierAppleWalkingSteadiness", "discrete", "%", "Устойчивость при ходьбе", "mobility"),
    ("HKQuantityTypeIdentifierSixMinuteWalkTestDistance", "discrete", "m", "Дистанция шестиминутной ходьбы", "mobility"),
    ("HKQuantityTypeIdentifierStairAscentSpeed", "discrete", "m/s", "Скорость подъёма по лестнице", "mobility"),
    ("HKQuantityTypeIdentifierStairDescentSpeed", "discrete", "m/s", "Скорость спуска по лестнице", "mobility"),
    ("HKQuantityTypeIdentifierHeartRateRecoveryOneMinute", "discrete", "count/min", "Восстановление пульса за минуту", "heart"),
    ("HKQuantityTypeIdentifierAtrialFibrillationBurden", "discrete", "%", "Доля фибрилляции предсердий", "heart"),
    ("HKQuantityTypeIdentifierPeripheralPerfusionIndex", "discrete", "%", "Индекс периферической перфузии", "heart"),
    ("HKQuantityTypeIdentifierBloodPressureSystolic", "discrete", "mmHg", "Систолическое давление", "heart"),
    ("HKQuantityTypeIdentifierBloodPressureDiastolic", "discrete", "mmHg", "Диастолическое давление", "heart"),
    ("HKQuantityTypeIdentifierForcedVitalCapacity", "discrete", "L", "Форсированная жизненная ёмкость лёгких", "heart"),
    ("HKQuantityTypeIdentifierForcedExpiratoryVolume1", "discrete", "L", "Объём форсированного выдоха за секунду", "heart"),
    ("HKQuantityTypeIdentifierPeakExpiratoryFlowRate", "discrete", "L/min", "Пиковая скорость выдоха", "heart"),
    ("HKQuantityTypeIdentifierInhalerUsage", "cumulative", "count", "Использование ингалятора", "heart"),
    ("HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances", "discrete", "count", "Нарушения дыхания во сне", "heart"),
    ("HKQuantityTypeIdentifierWaistCircumference", "discrete", "cm", "Обхват талии", "body"),
    ("HKQuantityTypeIdentifierBodyTemperature", "discrete", "degC", "Температура тела", "body"),
    ("HKQuantityTypeIdentifierAppleSleepingWristTemperature", "discrete", "degC", "Температура запястья во сне", "body"),
    ("HKQuantityTypeIdentifierElectrodermalActivity", "discrete", "mcS", "Электродермальная активность", "body"),
    ("HKQuantityTypeIdentifierEnvironmentalAudioExposure", "discrete", "dBASPL", "Шум окружения", "hearing"),
    ("HKQuantityTypeIdentifierHeadphoneAudioExposure", "discrete", "dBASPL", "Громкость в наушниках", "hearing"),
    ("HKQuantityTypeIdentifierEnvironmentalSoundReduction", "discrete", "dBASPL", "Шумоподавление", "hearing"),
    ("HKQuantityTypeIdentifierDietaryFiber", "cumulative", "g", "Клетчатка", "nutrition"),
    ("HKQuantityTypeIdentifierDietarySugar", "cumulative", "g", "Сахар", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryFatSaturated", "cumulative", "g", "Насыщенные жиры", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryFatMonounsaturated", "cumulative", "g", "Мононенасыщенные жиры", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryFatPolyunsaturated", "cumulative", "g", "Полиненасыщенные жиры", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryCholesterol", "cumulative", "mg", "Холестерин", "nutrition"),
    ("HKQuantityTypeIdentifierDietarySodium", "cumulative", "mg", "Натрий", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryPotassium", "cumulative", "mg", "Калий", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryCalcium", "cumulative", "mg", "Кальций", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryIron", "cumulative", "mg", "Железо", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryMagnesium", "cumulative", "mg", "Магний", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryPhosphorus", "cumulative", "mg", "Фосфор", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryZinc", "cumulative", "mg", "Цинк", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryCopper", "cumulative", "mg", "Медь", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryManganese", "cumulative", "mg", "Марганец", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryChloride", "cumulative", "mg", "Хлорид", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryCaffeine", "cumulative", "mg", "Кофеин", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminC", "cumulative", "mg", "Витамин C", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminE", "cumulative", "mg", "Витамин E", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminB6", "cumulative", "mg", "Витамин B6", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryThiamin", "cumulative", "mg", "Тиамин (B1)", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryRiboflavin", "cumulative", "mg", "Рибофлавин (B2)", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryNiacin", "cumulative", "mg", "Ниацин (B3)", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryPantothenicAcid", "cumulative", "mg", "Пантотеновая кислота (B5)", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminA", "cumulative", "mcg", "Витамин A", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminB12", "cumulative", "mcg", "Витамин B12", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminD", "cumulative", "mcg", "Витамин D", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryVitaminK", "cumulative", "mcg", "Витамин K", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryFolate", "cumulative", "mcg", "Фолат", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryBiotin", "cumulative", "mcg", "Биотин", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryIodine", "cumulative", "mcg", "Йод", "nutrition"),
    ("HKQuantityTypeIdentifierDietarySelenium", "cumulative", "mcg", "Селен", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryChromium", "cumulative", "mcg", "Хром", "nutrition"),
    ("HKQuantityTypeIdentifierDietaryMolybdenum", "cumulative", "mcg", "Молибден", "nutrition"),
    ("HKQuantityTypeIdentifierNumberOfAlcoholicBeverages", "cumulative", "count", "Алкогольные напитки", "nutrition"),
    ("HKQuantityTypeIdentifierBloodGlucose", "discrete", "mg/dL", "Глюкоза крови", "other"),
    ("HKQuantityTypeIdentifierInsulinDelivery", "cumulative", "IU", "Инсулин", "other"),
    ("HKQuantityTypeIdentifierBloodAlcoholContent", "discrete", "%", "Алкоголь в крови", "other"),
    ("HKQuantityTypeIdentifierNumberOfTimesFallen", "cumulative", "count", "Падения", "other"),
    ("HKQuantityTypeIdentifierUVExposure", "discrete", "count", "УФ-индекс", "other"),
    ("HKCategoryTypeIdentifierAppleStandHour", "cumulative", "count", "Часы с разминкой", "movement"),
    ("HKCategoryTypeIdentifierMindfulSession", "cumulative", "min", "Осознанность", "mind"),
    ("HKCategoryTypeIdentifierHighHeartRateEvent", "cumulative", "count", "Уведомления о высоком пульсе", "heart"),
    ("HKCategoryTypeIdentifierLowHeartRateEvent", "cumulative", "count", "Уведомления о низком пульсе", "heart"),
    ("HKCategoryTypeIdentifierIrregularHeartRhythmEvent", "cumulative", "count", "Уведомления о нерегулярном ритме", "heart"),
    ("HKCategoryTypeIdentifierLowCardioFitnessEvent", "cumulative", "count", "Уведомления о низкой кардиоподготовке", "heart"),
    ("HKCategoryTypeIdentifierHypertensionEvent", "cumulative", "count", "Уведомления о гипертонии", "heart"),
    ("HKCategoryTypeIdentifierSleepApneaEvent", "cumulative", "count", "Уведомления о нарушениях дыхания во сне", "heart"),
    ("HKCategoryTypeIdentifierAppleWalkingSteadinessEvent", "cumulative", "count", "Уведомления об устойчивости при ходьбе", "mobility"),
    ("HKCategoryTypeIdentifierAudioExposureEvent", "cumulative", "count", "Уведомления о громком окружении", "hearing"),
    ("HKCategoryTypeIdentifierHeadphoneAudioExposureEvent", "cumulative", "count", "Уведомления о громкости наушников", "hearing"),
    ("HKCategoryTypeIdentifierToothbrushingEvent", "cumulative", "count", "Чистка зубов", "other"),
    ("HKCategoryTypeIdentifierHandwashingEvent", "cumulative", "count", "Мытьё рук", "other"),
    ("HKCategoryTypeIdentifierAbdominalCramps", "cumulative", "count", "Спазмы в животе", "symptoms"),
    ("HKCategoryTypeIdentifierAcne", "cumulative", "count", "Акне", "symptoms"),
    ("HKCategoryTypeIdentifierAppetiteChanges", "cumulative", "count", "Изменения аппетита", "symptoms"),
    ("HKCategoryTypeIdentifierBladderIncontinence", "cumulative", "count", "Недержание мочи", "symptoms"),
    ("HKCategoryTypeIdentifierBloating", "cumulative", "count", "Вздутие", "symptoms"),
    ("HKCategoryTypeIdentifierBreastPain", "cumulative", "count", "Боль в молочных железах", "symptoms"),
    ("HKCategoryTypeIdentifierChestTightnessOrPain", "cumulative", "count", "Стеснение или боль в груди", "symptoms"),
    ("HKCategoryTypeIdentifierChills", "cumulative", "count", "Озноб", "symptoms"),
    ("HKCategoryTypeIdentifierConstipation", "cumulative", "count", "Запор", "symptoms"),
    ("HKCategoryTypeIdentifierCoughing", "cumulative", "count", "Кашель", "symptoms"),
    ("HKCategoryTypeIdentifierDiarrhea", "cumulative", "count", "Диарея", "symptoms"),
    ("HKCategoryTypeIdentifierDizziness", "cumulative", "count", "Головокружение", "symptoms"),
    ("HKCategoryTypeIdentifierDrySkin", "cumulative", "count", "Сухость кожи", "symptoms"),
    ("HKCategoryTypeIdentifierFainting", "cumulative", "count", "Обморок", "symptoms"),
    ("HKCategoryTypeIdentifierFatigue", "cumulative", "count", "Усталость", "symptoms"),
    ("HKCategoryTypeIdentifierFever", "cumulative", "count", "Жар", "symptoms"),
    ("HKCategoryTypeIdentifierGeneralizedBodyAche", "cumulative", "count", "Ломота в теле", "symptoms"),
    ("HKCategoryTypeIdentifierHairLoss", "cumulative", "count", "Выпадение волос", "symptoms"),
    ("HKCategoryTypeIdentifierHeadache", "cumulative", "count", "Головная боль", "symptoms"),
    ("HKCategoryTypeIdentifierHeartburn", "cumulative", "count", "Изжога", "symptoms"),
    ("HKCategoryTypeIdentifierHotFlashes", "cumulative", "count", "Приливы", "symptoms"),
    ("HKCategoryTypeIdentifierLossOfSmell", "cumulative", "count", "Потеря обоняния", "symptoms"),
    ("HKCategoryTypeIdentifierLossOfTaste", "cumulative", "count", "Потеря вкуса", "symptoms"),
    ("HKCategoryTypeIdentifierLowerBackPain", "cumulative", "count", "Боль в пояснице", "symptoms"),
    ("HKCategoryTypeIdentifierMemoryLapse", "cumulative", "count", "Провалы в памяти", "symptoms"),
    ("HKCategoryTypeIdentifierMoodChanges", "cumulative", "count", "Перепады настроения", "symptoms"),
    ("HKCategoryTypeIdentifierNausea", "cumulative", "count", "Тошнота", "symptoms"),
    ("HKCategoryTypeIdentifierNightSweats", "cumulative", "count", "Ночная потливость", "symptoms"),
    ("HKCategoryTypeIdentifierPelvicPain", "cumulative", "count", "Тазовая боль", "symptoms"),
    ("HKCategoryTypeIdentifierRapidPoundingOrFlutteringHeartbeat", "cumulative", "count", "Учащённое сердцебиение", "symptoms"),
    ("HKCategoryTypeIdentifierRunnyNose", "cumulative", "count", "Насморк", "symptoms"),
    ("HKCategoryTypeIdentifierShortnessOfBreath", "cumulative", "count", "Одышка", "symptoms"),
    ("HKCategoryTypeIdentifierSinusCongestion", "cumulative", "count", "Заложенность носа", "symptoms"),
    ("HKCategoryTypeIdentifierSkippedHeartbeat", "cumulative", "count", "Перебои сердцебиения", "symptoms"),
    ("HKCategoryTypeIdentifierSleepChanges", "cumulative", "count", "Изменения сна", "symptoms"),
    ("HKCategoryTypeIdentifierSoreThroat", "cumulative", "count", "Боль в горле", "symptoms"),
    ("HKCategoryTypeIdentifierVaginalDryness", "cumulative", "count", "Сухость влагалища", "symptoms"),
    ("HKCategoryTypeIdentifierVomiting", "cumulative", "count", "Рвота", "symptoms"),
    ("HKCategoryTypeIdentifierWheezing", "cumulative", "count", "Хрипы", "symptoms"),
]

COLUMNS = ("identifier", "kind", "canonical_unit", "display_name", "group")


def _metrics() -> sa.TableClause:
    return sa.table(
        "health_metrics",
        sa.column("identifier", sa.String),
        sa.column("kind", sa.String),
        sa.column("canonical_unit", sa.String),
        sa.column("display_name", sa.String),
        sa.column("group", sa.String),
    )


def upgrade() -> None:
    # Plain INSERT: an identifier already present means the database is not the
    # one this revision follows, and the migration should stop there.
    op.execute(_metrics().insert().values([dict(zip(COLUMNS, row)) for row in METRICS]))


def downgrade() -> None:
    metrics = _metrics()
    op.execute(
        metrics.delete().where(metrics.c.identifier.in_([row[0] for row in METRICS]))
    )
