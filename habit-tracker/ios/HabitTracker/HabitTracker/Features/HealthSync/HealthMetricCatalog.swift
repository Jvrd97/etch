// [review:need-review] PHASE-02/65, PHASE-03/234, PHASE-03/233, PHASE-03/238
// summary: the exact 24 HealthKit quantity types, their kind (cumulative or discrete), the HealthKit unit they are read in and the unit the server is sent, names, and four screen groups; the category types the pump sends as raw intervals (sleep), with the server kind and how far before the window to read

import HealthKit

enum HealthMetricGroup: String, CaseIterable, Hashable, Sendable {
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

/// Mirrors `MetricKind` in the server catalogue and HealthKit's own aggregation style.
enum HealthMetricKind: Equatable, Sendable {
    /// An amount over an interval (steps): read as HealthKit's hourly sums.
    case cumulative
    /// A reading at a moment (resting heart rate): read as samples.
    case discrete
}

struct HealthMetricDefinition: Identifiable, Equatable, Sendable {
    let typeIdentifier: HKQuantityTypeIdentifier
    let displayName: String
    let group: HealthMetricGroup
    let kind: HealthMetricKind
    /// HealthKit unit string the value is read in.
    let unit: String
    /// Unit string the server is told the value is in. Differs from `unit` only for
    /// percentages: `HKUnit.percent()` yields 0.97, which the server calls `fraction`.
    let wireUnit: String

    var identifier: String { typeIdentifier.rawValue }
    var id: String { identifier }
}

enum HealthMetricCatalog {
    static let metrics: [HealthMetricDefinition] = [
        metric(.stepCount, "Шаги", .movement, .cumulative, "count"),
        metric(.distanceWalkingRunning, "Дистанция ходьбы и бега", .movement, .cumulative, "m"),
        metric(.flightsClimbed, "Этажи", .movement, .cumulative, "count"),
        metric(.activeEnergyBurned, "Активная энергия", .movement, .cumulative, "kcal"),
        metric(.basalEnergyBurned, "Базальная энергия", .movement, .cumulative, "kcal"),
        metric(.appleExerciseTime, "Минуты тренировки", .movement, .cumulative, "min"),
        metric(.appleStandTime, "Время стоя", .movement, .cumulative, "min"),
        metric(.heartRate, "Пульс", .heart, .discrete, "count/min"),
        metric(.restingHeartRate, "Пульс покоя", .heart, .discrete, "count/min"),
        metric(.walkingHeartRateAverage, "Средний пульс при ходьбе", .heart, .discrete, "count/min"),
        metric(.heartRateVariabilitySDNN, "Вариабельность пульса (SDNN)", .heart, .discrete, "ms"),
        metric(.respiratoryRate, "Частота дыхания", .heart, .discrete, "count/min"),
        metric(.oxygenSaturation, "Сатурация", .heart, .discrete, "%", wire: "fraction"),
        metric(.vo2Max, "VO2max", .heart, .discrete, "mL/(kg*min)"),
        metric(.bodyMass, "Вес", .body, .discrete, "kg"),
        metric(.bodyFatPercentage, "Процент жира", .body, .discrete, "%", wire: "fraction"),
        metric(.leanBodyMass, "Мышечная масса", .body, .discrete, "kg"),
        metric(.bodyMassIndex, "Индекс массы тела", .body, .discrete, "count"),
        metric(.height, "Рост", .body, .discrete, "cm"),
        metric(.dietaryEnergyConsumed, "Съеденные калории", .nutrition, .cumulative, "kcal"),
        metric(.dietaryProtein, "Белки", .nutrition, .cumulative, "g"),
        metric(.dietaryFatTotal, "Жиры", .nutrition, .cumulative, "g"),
        metric(.dietaryCarbohydrates, "Углеводы", .nutrition, .cumulative, "g"),
        metric(.dietaryWater, "Вода", .nutrition, .cumulative, "mL"),
    ]

    private static func metric(
        _ identifier: HKQuantityTypeIdentifier,
        _ displayName: String,
        _ group: HealthMetricGroup,
        _ kind: HealthMetricKind,
        _ unit: String,
        wire wireUnit: String? = nil
    ) -> HealthMetricDefinition {
        HealthMetricDefinition(
            typeIdentifier: identifier,
            displayName: displayName,
            group: group,
            kind: kind,
            unit: unit,
            wireUnit: wireUnit ?? unit
        )
    }
}

/// A HealthKit category type the pump sends as raw intervals (`category_samples`):
/// HealthKit's raw category value, a start and an end. The server decides what the
/// value means by its catalogue kind; the app does not fold anything.
struct HealthCategoryDefinition: Identifiable, Equatable, Sendable {
    let typeIdentifier: HKCategoryTypeIdentifier
    let displayName: String
    /// The server catalogue kind (`sleep` folds into nights by wake date).
    let serverKind: String
    /// How long before the window's first midnight to start reading. The server sends
    /// every interval of a night to one row and overwrites it, so the first night of
    /// the window has to arrive whole.
    let lead: TimeInterval

    var identifier: String { typeIdentifier.rawValue }
    var id: String { identifier }
}

enum HealthCategoryCatalog {
    /// Server `NIGHT_BOUNDARY_HOUR` (`app/health/sleep.py`): the night that ends on a date
    /// collects every interval ending after 18:00 the evening before, six hours before midnight.
    static let nightLead: TimeInterval = 6 * 60 * 60

    static let sleep = HealthCategoryDefinition(
        typeIdentifier: .sleepAnalysis, displayName: "Сон", serverKind: "sleep", lead: nightLead
    )

    static let categories: [HealthCategoryDefinition] = [sleep]
}
