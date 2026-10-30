// [review:need-review] PHASE-01/268
// summary: a scriptable HealthMetricsAPI and the answers the Health tests share — one handler per read, the calls it saw
import Foundation
@testable import HabitTracker

final class MockHealthMetricsAPI: HealthMetricsAPI {
    var metricsHandler: (String, String) async throws -> HealthMetricsResponseDTO = { _, _ in HealthMetricsResponseDTO(metrics: []) }
    var daysHandler: (String, String, String) async throws -> HealthMetricDaysResponseDTO = { id, _, _ in
        HealthMetricDaysResponseDTO(identifier: id, displayName: id, kind: "cumulative", canonicalUnit: "count", days: [])
    }
    var hoursHandler: (String, String) async throws -> HealthMetricHoursResponseDTO = { id, day in
        HealthMetricHoursResponseDTO(identifier: id, displayName: id, kind: "cumulative", canonicalUnit: "count", date: day, hours: [])
    }
    var sleepHandler: (String, String) async throws -> HealthSleepResponseDTO = { _, _ in HealthSleepResponseDTO(nights: []) }
    var workoutsHandler: (String, String) async throws -> HealthWorkoutsResponseDTO = { _, _ in HealthWorkoutsResponseDTO(workouts: []) }
    var statusHandler: () async throws -> HealthSyncStatusDTO = {
        HealthSyncStatusDTO(lastRuns: [], lastSuccessAt: nil, lagHours: 0.5, interrupted: false)
    }
    private let lock = NSLock()
    private var recorded: [String] = []

    /// The reads of one screen run side by side, so the log is guarded.
    var calls: [String] {
        lock.lock()
        defer { lock.unlock() }
        return recorded
    }

    private func record(_ call: String) {
        lock.lock()
        recorded.append(call)
        lock.unlock()
    }

    func fetchHealthMetrics(dateFrom: String, dateTo: String) async throws -> HealthMetricsResponseDTO {
        record("metrics \(dateFrom)...\(dateTo)")
        return try await metricsHandler(dateFrom, dateTo)
    }

    func fetchHealthMetricDays(identifier: String, dateFrom: String, dateTo: String) async throws -> HealthMetricDaysResponseDTO {
        record("days \(identifier) \(dateFrom)...\(dateTo)")
        return try await daysHandler(identifier, dateFrom, dateTo)
    }

    func fetchHealthMetricHours(identifier: String, date: String) async throws -> HealthMetricHoursResponseDTO {
        record("hours \(identifier) \(date)")
        return try await hoursHandler(identifier, date)
    }

    func fetchHealthSleep(dateFrom: String, dateTo: String) async throws -> HealthSleepResponseDTO {
        record("sleep \(dateFrom)...\(dateTo)")
        return try await sleepHandler(dateFrom, dateTo)
    }

    func fetchHealthWorkouts(dateFrom: String, dateTo: String) async throws -> HealthWorkoutsResponseDTO {
        record("workouts \(dateFrom)...\(dateTo)")
        return try await workoutsHandler(dateFrom, dateTo)
    }

    func fetchHealthSyncStatus() async throws -> HealthSyncStatusDTO {
        record("status")
        return try await statusHandler()
    }
}

enum HealthMetricsFixtures {
    static func steps(days: [(String, Double)]) -> HealthMetricSeriesDTO {
        HealthMetricSeriesDTO(
            identifier: "HKQuantityTypeIdentifierStepCount", displayName: "Шаги", group: "movement", kind: "cumulative",
            canonicalUnit: "count", days: days.map { HealthDayValueDTO(date: $0.0, value: $0.1) }, baseline: nil
        )
    }

    static func night(_ date: String, asleep: Double = 430) -> HealthSleepNightDTO {
        HealthSleepNightDTO(
            date: date, bedtime: "\(date)T00:10:00+03:00", wakeTime: "\(date)T07:20:00+03:00",
            inBedMin: 0, asleepMin: asleep, awakeMin: 0, coreMin: asleep, deepMin: 0, remMin: 0, unspecifiedMin: 0
        )
    }
}
