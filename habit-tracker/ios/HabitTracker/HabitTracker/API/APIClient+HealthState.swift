// [review:need-review] PHASE-03/305
// summary: HealthStateAPI — the one read behind the «Состояние сегодня» card, GET /dashboard/summary?period=week; APIClient implements it on the shared request helpers
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — asks `parts=health`: the server answers the health blocks alone (a few ms instead of the whole summary); a server without the parameter ignores it and answers in full
import Foundation

/// API surface of the state card; kept apart from `HealthMetricsAPI` because the endpoint belongs to the dashboard.
protocol HealthStateAPI {
    func fetchHealthState() async throws -> HealthStateResponseDTO
}

extension APIClient: HealthStateAPI {
    /// The week window: the index of the days just lived, as the dashboard shows it.
    func fetchHealthState() async throws -> HealthStateResponseDTO {
        try await getJSON(
            path: "/dashboard/summary",
            query: [URLQueryItem(name: "period", value: "week"), URLQueryItem(name: "parts", value: "health")]
        )
    }
}
