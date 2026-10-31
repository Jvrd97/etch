// [review:need-review] PHASE-03/305
// summary: what the Health screen draws out of data it already holds — the words of the server's index, tone of a deviation by the direction of «better», the share of key metrics not worse than the metric's own norm, deviation bars around zero, seven-night sleep bars (a missing night stays a gap) with the best night, tiles with a gap-keeping line, workouts grouped by type with only the numbers HealthKit held; no formula of the index lives here
import Foundation

/// Whether a value against the norm is good news; drives the colour and never stands alone: a word always goes beside it.
enum HealthTone: Equatable {
    case better
    case worse
    case same
}

enum HealthOverview {
    // MARK: Key metrics

    private static let restingHeartRate = "HKQuantityTypeIdentifierRestingHeartRate"
    private static let variability = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
    private static let respiratoryRate = "HKQuantityTypeIdentifierRespiratoryRate"
    static let stepCount = "HKQuantityTypeIdentifierStepCount"
    static let activeEnergy = "HKQuantityTypeIdentifierActiveEnergyBurned"

    /// Key metrics and the direction of «better»: a lower resting pulse and calmer breathing are good news, the rest the other way.
    private static let higherIsBetter: [String: Bool] = [
        restingHeartRate: false, variability: true, respiratoryRate: false, stepCount: true, activeEnergy: true,
    ]

    static func isHigherBetter(_ identifier: String) -> Bool? { higherIsBetter[identifier] }

    /// A deviation that prints as «как обычно» is neither good nor bad.
    static func tone(deviation: Double, higherIsBetter: Bool) -> HealthTone {
        let rounded = (deviation * 10).rounded() / 10
        if rounded == 0 { return .same }
        return (rounded > 0) == higherIsBetter ? .better : .worse
    }

    // MARK: State card

    static func stateWord(_ label: String?) -> String? {
        switch label {
        case "good": return "Хорошее"
        case "fair": return "Среднее"
        case "poor": return "Низкое"
        default: return nil
        }
    }

    static let indexScale = 100

    static func indexText(_ value: Int) -> String { "\(value) из \(indexScale)" }

    static let stateTitle = "Состояние сегодня"
    /// The server holds the index back under three days of data.
    static let stateTooLittleText = "Данных мало: индекс считается, когда набралось хотя бы три дня."

    /// «по 7 дням» — the days the server counted the index on.
    static func basisText(_ days: Int) -> String {
        let one = days % 10 == 1 && days % 100 != 11
        return "по \(days) \(one ? "дню" : "дням")"
    }

    struct NormShare: Equatable {
        let inNorm: Int
        let judged: Int
        var fraction: Double? { judged == 0 ? nil : Double(inNorm) / Double(judged) }
    }

    /// Of the key metrics that have a norm of their own: how many are not worse than it today.
    static func normShare(_ metrics: [HealthMetricSeriesDTO]) -> NormShare {
        var inNorm = 0
        var judged = 0
        for metric in metrics {
            guard let better = higherIsBetter[metric.identifier], let baseline = metric.baseline else { continue }
            judged += 1
            if tone(deviation: baseline.deviation, higherIsBetter: better) != .worse { inNorm += 1 }
        }
        return NormShare(inNorm: inNorm, judged: judged)
    }

    // MARK: Deviation bars

    /// Half of the bar axis, as a share of the metric's own norm: a bar that long is a fifth above or below it.
    static let deviationAxis = 0.2

    struct DeviationBar: Equatable, Identifiable {
        let id: String
        let title: String
        let text: String
        /// -1...1 around zero; the sign is the side, the tone is whether that side is good.
        let share: Double
        let tone: HealthTone
    }

    private static let barMetrics = [restingHeartRate, variability, respiratoryRate]

    static func deviationBars(_ metrics: [HealthMetricSeriesDTO]) -> [DeviationBar] {
        barMetrics.compactMap { identifier in
            guard let metric = metrics.first(where: { $0.identifier == identifier }),
                  let baseline = metric.baseline, baseline.mean != 0, let better = higherIsBetter[identifier]
            else { return nil }
            let share = max(-1, min(1, baseline.deviation / abs(baseline.mean) / deviationAxis))
            return DeviationBar(
                id: identifier, title: metric.displayName,
                text: HealthMetricsFormat.deviationText(baseline, identifier: identifier, unit: metric.canonicalUnit),
                share: share, tone: tone(deviation: baseline.deviation, higherIsBetter: better)
            )
        }
    }

    // MARK: Tiles

    struct Tile: Equatable {
        let title: String
        let value: String
        /// The day of the value when it is not today.
        let dateNote: String?
        let note: String?
        let tone: HealthTone
        let points: [Double?]
    }

    /// `nil` for a metric the phone never filled.
    static func tile(_ metric: HealthMetricSeriesDTO, today: String, higherIsBetter: Bool) -> Tile? {
        guard let latest = metric.days.last else { return nil }
        let baseline = metric.baseline
        return Tile(
            title: metric.displayName,
            value: HealthMetricsFormat.formatQuantity(identifier: metric.identifier, value: latest.value, unit: metric.canonicalUnit),
            dateNote: latest.date == today ? nil : HealthMetricsFormat.dayLabel(latest.date),
            note: baseline.map { HealthMetricsFormat.deviationText($0, identifier: metric.identifier, unit: metric.canonicalUnit) },
            tone: baseline.map { tone(deviation: $0.deviation, higherIsBetter: higherIsBetter) } ?? .same,
            points: HealthMetricsFormat.sparklinePoints(metric.days, endDate: latest.date)
        )
    }

    // MARK: Sleep bars

    static let sleepTitle = "Сон по ночам"

    struct SleepBar: Equatable, Identifiable {
        let date: String
        let weekday: String
        let hasData: Bool
        let deepRemMin: Double
        let lightMin: Double
        let isBest: Bool
        var id: String { date }
        var totalMin: Double { deepRemMin + lightMin }
    }

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        return calendar
    }()

    private static let weekdayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ru_RU")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "EE"
        return formatter
    }()

    private static func weekday(_ iso: String) -> String {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, let date = utc.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])) else { return "" }
        return weekdayFormatter.string(from: date).lowercased()
    }

    /// The seven nights ending `today`, oldest first. A night nothing arrived for has no data and no height: it is not a short night.
    static func sleepBars(_ nights: [HealthSleepNightDTO], today: String, count: Int = HealthMetricsFormat.weekDays) -> [SleepBar] {
        let byDate = Dictionary(nights.map { ($0.date, $0) }, uniquingKeysWith: { _, last in last })
        let dates = (0..<count).map { HealthMetricsFormat.shiftDate(today, by: $0 - (count - 1)) }
        let longest = dates.compactMap { byDate[$0]?.asleepMin }.max()
        let bestDate = dates.last { byDate[$0]?.asleepMin == longest && longest != nil }
        return dates.map { date in
            guard let night = byDate[date] else {
                return SleepBar(date: date, weekday: weekday(date), hasData: false, deepRemMin: 0, lightMin: 0, isBest: false)
            }
            let deepRem = night.deepMin + night.remMin
            return SleepBar(
                date: date, weekday: weekday(date), hasData: true, deepRemMin: deepRem,
                lightMin: max(night.asleepMin - deepRem, 0), isBest: date == bestDate
            )
        }
    }

    // MARK: Workouts

    static let workoutsTitle = "Тренировки · 30 дней"

    private static func plural(_ count: Int, _ one: String, _ few: String, _ many: String) -> String {
        let tail = count % 100
        if (11...14).contains(tail) { return many }
        switch count % 10 {
        case 1: return one
        case 2...4: return few
        default: return many
        }
    }

    struct WorkoutGroup: Equatable, Identifiable {
        let type: String
        let label: String
        let count: Int
        let minutes: Double
        /// `nil` when none of the workouts held the number: not zero.
        let kcal: Double?
        let meters: Double?
        var id: String { type }

        var details: [String] {
            var parts = ["\(count) \(HealthOverview.plural(count, "раз", "раза", "раз"))", HealthMetricsFormat.sleepDuration(minutes)]
            if let kcal { parts.append("\(Int(kcal.rounded())) ккал") }
            if let meters { parts.append(HealthMetricsFormat.workoutDistance(meters)) }
            return parts
        }
    }

    /// By type, the one that took most time first.
    static func workoutGroups(_ workouts: [HealthWorkoutRecordDTO]) -> [WorkoutGroup] {
        var order: [String] = []
        var byType: [String: [HealthWorkoutRecordDTO]] = [:]
        for workout in workouts {
            if byType[workout.activityType] == nil { order.append(workout.activityType) }
            byType[workout.activityType, default: []].append(workout)
        }
        func sum(_ values: [Double?]) -> Double? {
            let held = values.compactMap { $0 }
            return held.isEmpty ? nil : held.reduce(0, +)
        }
        return order.compactMap { type -> WorkoutGroup? in
            guard let rows = byType[type], let first = rows.first else { return nil }
            return WorkoutGroup(
                type: type, label: first.activityLabel, count: rows.count, minutes: rows.reduce(0) { $0 + $1.durationMin },
                kcal: sum(rows.map(\.energyKcal)), meters: sum(rows.map(\.distanceM))
            )
        }
        .sorted { $0.minutes != $1.minutes ? $0.minutes > $1.minutes : $0.label < $1.label }
    }

    /// «2 тренировки · 1 ч 15 мин»; `nil` when there were none.
    static func workoutsHeadline(_ workouts: [HealthWorkoutRecordDTO]) -> String? {
        guard !workouts.isEmpty else { return nil }
        let word = plural(workouts.count, "тренировка", "тренировки", "тренировок")
        let minutes = HealthMetricsFormat.sleepDuration(workouts.reduce(0) { $0 + $1.durationMin })
        return "\(workouts.count) \(word) · \(minutes)"
    }
}
