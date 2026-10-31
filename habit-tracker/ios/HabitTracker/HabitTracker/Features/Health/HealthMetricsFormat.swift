// [review:need-review] PHASE-01/268
// summary: vocabulary of the Health metrics screens, the same words as the web (frontend/lib/health.ts, health-metrics.ts, HealthSyncStatus.tsx) — units in Russian (never `count`, `count/min`; cycling cadence is «об/мин»), values, deviation from the metric's own baseline, calendar-day arithmetic, the 24 hour slots, sparkline points with a gap kept as a gap, sleep and workout lines, groups, and the sync/lag verdict
import Foundation

enum HealthMetricsFormat {
    // MARK: Groups

    static let groups: [(id: String, title: String)] = [
        ("movement", "Движение и энергия"),
        ("heart", "Сердце и дыхание"),
        ("body", "Тело"),
        ("nutrition", "Питание"),
        ("mobility", "Подвижность"),
        ("hearing", "Слух"),
        ("mind", "Осознанность"),
        ("symptoms", "Симптомы"),
        ("other", "Другое"),
    ]

    private static let knownGroupIDs = Set(groups.map(\.id))

    /// The metrics of a group in server order. A group the app does not know yet is filed under «Другое», not dropped.
    static func metrics(of group: String, in all: [HealthMetricSeriesDTO]) -> [HealthMetricSeriesDTO] {
        all.filter { metric in
            metric.group == group || (group == "other" && !knownGroupIDs.contains(metric.group))
        }
    }

    // MARK: Periods

    static let periods: [(days: Int, label: String)] = [(7, "7 дней"), (30, "30 дней"), (90, "90 дней")]
    static let defaultPeriodDays = 30
    static let sparklineDays = 30
    static let hoursPerDay = 24
    static let sleepIdentifier = "HKCategoryTypeIdentifierSleepAnalysis"
    /// Days of nights and workouts the list shows.
    static let weekDays = 7

    // MARK: Units

    private static let unitLabels: [String: String] = [
        "count": "", "count/min": "уд/мин", "kg": "кг", "g": "г", "mg": "мг", "mcg": "мкг", "m": "м", "cm": "см",
        "m/s": "м/с", "min": "мин", "ms": "мс", "kcal": "ккал", "degC": "°C", "mL": "мл", "L": "л",
        "dBASPL": "дБ", "mmHg": "мм рт. ст.",
        // Units the web prints as they come; here they have a word.
        "W": "Вт", "L/min": "л/мин", "mg/dL": "мг/дл", "IU": "МЕ", "mcS": "мкСм",
        "appleEffortScore": "", "NikeFuel": "",
    ]

    private static let countLabels: [String: String] = [
        "HKQuantityTypeIdentifierStepCount": "шагов",
        "HKQuantityTypeIdentifierFlightsClimbed": "этажей",
        "HKQuantityTypeIdentifierRespiratoryRate": "дых/мин",
    ]

    private static let respiratoryRate = "HKQuantityTypeIdentifierRespiratoryRate"
    private static let cyclingCadence = "HKQuantityTypeIdentifierCyclingCadence"

    /// The unit as a reader would say it: no `count`, no `count/min`; empty when there is no word for it.
    static func unitLabel(identifier: String, unit: String) -> String {
        if identifier == respiratoryRate { return countLabels[identifier] ?? "" }
        if identifier == cyclingCadence && unit == "count/min" { return "об/мин" }
        if unit == "count" { return countLabels[identifier] ?? "" }
        return unitLabels[unit] ?? unit
    }

    /// One decimal at most, no trailing zero: `4321`, `67.3`.
    static func formatValue(_ value: Double) -> String {
        let rounded = (value * 10).rounded() / 10
        if rounded == rounded.rounded() { return String(Int(rounded)) }
        return String(rounded)
    }

    /// Counts (steps, flights, falls) and kilocalories print whole; the rest keeps one decimal.
    static func isWhole(unit: String) -> Bool { unit == "count" || unit == "kcal" }

    /// `4322 шагов`, `67.3 уд/мин`, or just `3` for a bare count.
    static func formatQuantity(identifier: String, value: Double, unit: String) -> String {
        let label = unitLabel(identifier: identifier, unit: unit)
        let number = isWhole(unit: unit) ? String(Int(value.rounded())) : formatValue(value)
        return label.isEmpty ? number : "\(number) \(label)"
    }

    /// `+0.4 кг к обычному`, or `как обычно` when the day sits exactly on the mean.
    static func deviationText(_ baseline: HealthBaselineDTO, identifier: String, unit: String) -> String {
        let rounded = (baseline.deviation * 10).rounded() / 10
        if rounded == 0 { return "как обычно" }
        let label = unitLabel(identifier: identifier, unit: unit)
        let sign = rounded > 0 ? "+" : "−"
        let magnitude = isWhole(unit: unit) ? String(Int(abs(baseline.deviation).rounded())) : formatValue(abs(rounded))
        return "\(sign)\(magnitude)\(label.isEmpty ? "" : " \(label)") к обычному"
    }

    static let outsideTypicalText = "вне обычного"

    // MARK: Dates

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        return calendar
    }()

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ru_RU")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "d MMM"
        return formatter
    }()

    /// `yyyy-MM-dd` for a moment in the reader's own calendar, as the server's `date_from`/`date_to` want it.
    static func localDate(_ moment: Date, calendar: Calendar = .current) -> String {
        let parts = calendar.dateComponents([.year, .month, .day], from: moment)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    private static func parse(_ iso: String) -> Date? {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return utc.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
    }

    /// `yyyy-MM-dd` shifted by whole days, on the calendar alone.
    static func shiftDate(_ iso: String, by days: Int) -> String {
        guard let date = parse(iso), let shifted = utc.date(byAdding: .day, value: days, to: date) else { return iso }
        let parts = utc.dateComponents([.year, .month, .day], from: shifted)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    /// `2026-10-20` → `20 окт.`
    static func dayLabel(_ iso: String) -> String {
        guard let date = parse(iso) else { return iso }
        return dayFormatter.string(from: date)
    }

    // MARK: Series

    /// The `count` calendar days ending at `endDate`, oldest first. A day the server sent nothing for is `nil` — a gap in the line, never a zero.
    static func sparklinePoints(_ days: [HealthDayValueDTO], endDate: String, count: Int = sparklineDays) -> [Double?] {
        if days.isEmpty { return [] }
        let byDate = Dictionary(days.map { ($0.date, $0.value) }, uniquingKeysWith: { _, last in last })
        return (0..<count).map { index in byDate[shiftDate(endDate, by: index - (count - 1))] }
    }

    /// The 24 hours of a day, index = local hour. A slot without data is `nil`, which is not a zero.
    static func hourSlots(_ hours: [HealthHourValueDTO]) -> [HealthHourValueDTO?] {
        var slots = [HealthHourValueDTO?](repeating: nil, count: hoursPerDay)
        for hour in hours where hour.hour >= 0 && hour.hour < hoursPerDay { slots[hour.hour] = hour }
        return slots
    }

    static func hourLabel(_ hour: Int) -> String { String(format: "%02d:00", hour) }

    /// `54–58` for an hour of a discrete metric whose readings differ; `nil` when there is no range to show.
    static func hourRange(_ hour: HealthHourValueDTO) -> String? {
        hour.min == hour.max ? nil : "\(formatValue(hour.min))–\(formatValue(hour.max))"
    }

    // MARK: Sleep and workouts

    /// `430` → `7 ч 10 мин`.
    static func sleepDuration(_ minutes: Double) -> String {
        let total = Int(minutes.rounded())
        let hours = total / 60
        let rest = total % 60
        if hours == 0 { return "\(rest) мин" }
        return rest == 0 ? "\(hours) ч" : "\(hours) ч \(rest) мин"
    }

    /// `HH:MM` as the phone's clock showed it, read from the string and not converted into the reader's zone.
    static func wallClock(_ instant: String) -> String {
        guard let marker = instant.firstIndex(of: "T") else { return "" }
        return String(instant[instant.index(after: marker)...].prefix(5))
    }

    /// Stages in the order the Health app lists them; zero rows are left out.
    static func sleepStages(_ night: HealthSleepNightDTO) -> [(label: String, minutes: Double)] {
        [
            ("Основной", night.coreMin), ("Глубокий", night.deepMin), ("REM", night.remMin),
            ("Сон без фазы", night.unspecifiedMin), ("Бодрствование", night.awakeMin), ("В кровати", night.inBedMin),
        ].filter { $0.1 > 0 }
    }

    static let sleepEmptyText = "Ночей за неделю нет: сон приходит с телефона вместе с остальными метриками."
    static let workoutsEmptyText = "Тренировок за 30 дней нет: они приходят с телефона вместе с остальными метриками."

    /// `7200` → `7,2 км`, `850` → `850 м`.
    static func workoutDistance(_ meters: Double) -> String {
        if meters < 1000 { return "\(Int(meters.rounded())) м" }
        let kilometers = (meters / 1000 * 10).rounded() / 10
        let text = kilometers == kilometers.rounded() ? String(Int(kilometers)) : String(kilometers).replacingOccurrences(of: ".", with: ",")
        return "\(text) км"
    }

    /// The numbers HealthKit held for the workout, in reading order; a missing one is left out.
    static func workoutDetails(_ workout: HealthWorkoutRecordDTO) -> [String] {
        var details: [String] = []
        if let meters = workout.distanceM { details.append(workoutDistance(meters)) }
        if let kcal = workout.energyKcal { details.append("\(Int(kcal.rounded())) ккал") }
        if let pulse = workout.avgHeartRate { details.append("пульс \(Int(pulse.rounded())) уд/мин") }
        if let peak = workout.maxHeartRate { details.append("макс. \(Int(peak.rounded()))") }
        return details
    }

    // MARK: States in words

    static let notConfiguredMessage = "Укажите адрес сервера в More → Settings"
    static let loadFailedMessage = "Не удалось загрузить данные здоровья"
    static let syncHint = "Данных ещё нет — откройте «Синк и журнал» и нажмите «Отправить за 7 дней»."

    static func message(for error: APIClientError) -> String {
        switch error {
        case .invalidBaseURL: return "Неверный адрес сервера"
        case .unauthorized: return "Неверный ключ API (401)"
        case .timeout: return "Сервер не ответил вовремя"
        case .transport: return "Нет связи с сервером"
        case .unexpectedStatus(let status): return "Сервер ответил ошибкой \(status)"
        case .invalidResponse: return "Сервер вернул непонятный ответ"
        }
    }

    /// «Нет связи · обновлено 27 окт., 09:41» — absolute, so it stays honest while the screen sits open.
    static func offlineCaption(_ date: Date, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ru_RU")
        formatter.timeZone = timeZone
        formatter.setLocalizedDateFormatFromTemplate("dMMMHHmm")
        return "Нет связи · обновлено \(formatter.string(from: date))"
    }

    // MARK: Sync block

    /// From this lag the block turns into a warning.
    static let lagWarningHours = 24.0

    /// «меньше часа назад» under one hour, otherwise whole hours: «отставание 24 ч».
    static func lagLabel(_ lagHours: Double) -> String {
        lagHours < 1 ? "меньше часа назад" : "отставание \(Int(lagHours.rounded(.down))) ч"
    }

    struct SyncVerdict: Equatable {
        let text: String
        let detail: String?
        let warn: Bool
    }

    private static let failureLabels: [String: String] = [
        "network": "нет связи с сервером",
        "unit": "неверная единица измерения",
        "unknown_metric": "неизвестная метрика",
        "auth": "не прошла авторизация",
        "unknown": "причина неизвестна",
    ]

    static func syncVerdict(_ status: HealthSyncStatusDTO) -> SyncVerdict {
        let failed = status.lastRuns.first.flatMap { $0.status == "failed" ? $0 : nil }
        let failureDetail = failed.map {
            "Последний прогон не удался: \(failureLabels[$0.failureKind ?? "unknown"] ?? failureLabels["unknown"] ?? "")"
        }
        guard let lagHours = status.lagHours else {
            return SyncVerdict(text: "Синк ещё не проходил", detail: failureDetail, warn: true)
        }
        let lag = lagLabel(lagHours)
        if status.interrupted {
            return SyncVerdict(
                text: "Последний синк оборван — \(lag)",
                detail: "Телефон ушёл из сети посреди прогона; данные догрузятся при следующем синке.",
                warn: true
            )
        }
        return SyncVerdict(
            text: "Последний синк: \(lag)", detail: failureDetail, warn: lagHours >= lagWarningHours || failed != nil
        )
    }
}

/// What a list row says about a metric: the latest value, the day it belongs to when that is not today,
/// and the deviation from the metric's own baseline with its date when it is not the shown day.
struct HealthMetricRowText: Equatable {
    static let noDataText = "Нет данных"

    let value: String
    let dateNote: String?
    let deviation: String?
    let outsideTypical: Bool

    /// `nil` for a metric without a day: the row says «Нет данных».
    init?(_ metric: HealthMetricSeriesDTO, today: String) {
        guard let latest = metric.days.last else { return nil }
        value = HealthMetricsFormat.formatQuantity(
            identifier: metric.identifier, value: latest.value, unit: metric.canonicalUnit
        )
        dateNote = latest.date == today ? nil : HealthMetricsFormat.dayLabel(latest.date)
        if let baseline = metric.baseline {
            let prefix = baseline.day == latest.date ? "" : "\(HealthMetricsFormat.dayLabel(baseline.day)): "
            let text = prefix + HealthMetricsFormat.deviationText(
                baseline, identifier: metric.identifier, unit: metric.canonicalUnit
            )
            deviation = baseline.outsideTypical ? "\(text), \(HealthMetricsFormat.outsideTypicalText)" : text
            outsideTypical = baseline.outsideTypical
        } else {
            deviation = nil
            outsideTypical = false
        }
    }
}
