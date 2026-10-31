// [review:need-review] PHASE-03/305
// summary: HealthStateAPI — the one read behind the «Состояние сегодня» card, GET /dashboard/summary?period=week; APIClient implements it on the shared request helpers
import Foundation

/// API surface of the state card; kept apart from `HealthMetricsAPI` because the endpoint belongs to the dashboard.
protocol HealthStateAPI {
    func fetchHealthState() async throws -> HealthStateResponseDTO
}

extension APIClient: HealthStateAPI {
    /// The week window: the index of the days just lived, as the dashboard shows it.
    func fetchHealthState() async throws -> HealthStateResponseDTO {
        try await getJSON(path: "/dashboard/summary", query: [URLQueryItem(name: "period", value: "week")])
    }
}
