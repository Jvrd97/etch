// [review:need-review] PHASE-01/268
// summary: HealthMetricsAPI — the read ends of /health (metrics with baseline, one metric's days and hours, sleep nights, workouts, sync status); APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Health metrics screens; `APIClient` is the production implementation.
protocol HealthMetricsAPI {
    func fetchHealthMetrics(dateFrom: String, dateTo: String) async throws -> HealthMetricsResponseDTO
    func fetchHealthMetricDays(identifier: String, dateFrom: String, dateTo: String) async throws -> HealthMetricDaysResponseDTO
    func fetchHealthMetricHours(identifier: String, date: String) async throws -> HealthMetricHoursResponseDTO
    func fetchHealthSleep(dateFrom: String, dateTo: String) async throws -> HealthSleepResponseDTO
    func fetchHealthWorkouts(dateFrom: String, dateTo: String) async throws -> HealthWorkoutsResponseDTO
    func fetchHealthSyncStatus() async throws -> HealthSyncStatusDTO
}

extension APIClient: HealthMetricsAPI {
    func fetchHealthMetrics(dateFrom: String, dateTo: String) async throws -> HealthMetricsResponseDTO {
        try await getJSON(path: "/health/metrics", query: Self.range(dateFrom, dateTo))
    }

    func fetchHealthMetricDays(identifier: String, dateFrom: String, dateTo: String) async throws -> HealthMetricDaysResponseDTO {
        try await getJSON(path: "/health/metrics/\(identifier)/days", query: Self.range(dateFrom, dateTo))
    }

    func fetchHealthMetricHours(identifier: String, date: String) async throws -> HealthMetricHoursResponseDTO {
        try await getJSON(
            path: "/health/metrics/\(identifier)/hours",
            query: [URLQueryItem(name: "date", value: date)]
        )
    }

    func fetchHealthSleep(dateFrom: String, dateTo: String) async throws -> HealthSleepResponseDTO {
        try await getJSON(path: "/health/sleep", query: Self.range(dateFrom, dateTo))
    }

    func fetchHealthWorkouts(dateFrom: String, dateTo: String) async throws -> HealthWorkoutsResponseDTO {
        try await getJSON(path: "/health/workouts", query: Self.range(dateFrom, dateTo))
    }

    func fetchHealthSyncStatus() async throws -> HealthSyncStatusDTO {
        try await getJSON(path: "/health/sync-status", query: [])
    }

    private static func range(_ dateFrom: String, _ dateTo: String) -> [URLQueryItem] {
        [URLQueryItem(name: "date_from", value: dateFrom), URLQueryItem(name: "date_to", value: dateTo)]
    }
}
