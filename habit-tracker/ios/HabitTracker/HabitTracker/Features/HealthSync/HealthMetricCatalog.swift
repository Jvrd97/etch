// [review:need-review] PHASE-02/65
// summary: the exact 24 HealthKit quantity types, their canonical units, names, and four screen groups

import HealthKit

enum HealthMetricGroup: String, CaseIterable, Hashable {
    case movement
    case heart
    case body
    case nutrition

    var title: String {
        switch self {
        case .movement: "Движение и энергия"
        case .heart: "Сердце и дыхание"
        case .body: "Тело"
        case .nutrition: "Питание"
        }
    }
}

struct HealthMetricDefinition: Identifiable, Equatable {
    let typeIdentifier: HKQuantityTypeIdentifier
    let displayName: String
    let group: HealthMetricGroup
    let unit: String

    var identifier: String { typeIdentifier.rawValue }
    var id: String { identifier }
}

enum HealthMetricCatalog {
    static let metrics: [HealthMetricDefinition] = [
        metric(.stepCount, "Шаги", .movement, "count"),
        metric(.distanceWalkingRunning, "Дистанция ходьбы и бега", .movement, "m"),
        metric(.flightsClimbed, "Этажи", .movement, "count"),
        metric(.activeEnergyBurned, "Активная энергия", .movement, "kcal"),
        metric(.basalEnergyBurned, "Базальная энергия", .movement, "kcal"),
        metric(.appleExerciseTime, "Минуты тренировки", .movement, "min"),
        metric(.appleStandTime, "Время стоя", .movement, "min"),
        metric(.heartRate, "Пульс", .heart, "count/min"),
        metric(.restingHeartRate, "Пульс покоя", .heart, "count/min"),
        metric(.walkingHeartRateAverage, "Средний пульс при ходьбе", .heart, "count/min"),
        metric(.heartRateVariabilitySDNN, "Вариабельность пульса (SDNN)", .heart, "ms"),
        metric(.respiratoryRate, "Частота дыхания", .heart, "count/min"),
        metric(.oxygenSaturation, "Сатурация", .heart, "%"),
        metric(.vo2Max, "VO2max", .heart, "mL/(kg*min)"),
        metric(.bodyMass, "Вес", .body, "kg"),
        metric(.bodyFatPercentage, "Процент жира", .body, "%"),
        metric(.leanBodyMass, "Мышечная масса", .body, "kg"),
        metric(.bodyMassIndex, "Индекс массы тела", .body, "count"),
        metric(.height, "Рост", .body, "cm"),
        metric(.dietaryEnergyConsumed, "Съеденные калории", .nutrition, "kcal"),
        metric(.dietaryProtein, "Белки", .nutrition, "g"),
        metric(.dietaryFatTotal, "Жиры", .nutrition, "g"),
        metric(.dietaryCarbohydrates, "Углеводы", .nutrition, "g"),
        metric(.dietaryWater, "Вода", .nutrition, "mL"),
    ]

    private static func metric(
        _ identifier: HKQuantityTypeIdentifier,
        _ displayName: String,
        _ group: HealthMetricGroup,
        _ unit: String
    ) -> HealthMetricDefinition {
        HealthMetricDefinition(
            typeIdentifier: identifier,
            displayName: displayName,
            group: group,
            unit: unit
        )
    }
}
