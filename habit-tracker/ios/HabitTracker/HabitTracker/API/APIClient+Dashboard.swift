// [review:need-review] PHASE-03/304
// summary: DashboardSummaryAPI — the one read behind the dashboard, GET /dashboard/summary?period=week|month; APIClient implements it on the shared request helpers
import Foundation

/// API surface of the dashboard screen; `APIClient` is the production implementation.
protocol DashboardSummaryAPI {
    func fetchDashboardSummary(period: DashboardPeriod) async throws -> DashboardSummaryDTO
}

extension APIClient: DashboardSummaryAPI {
    func fetchDashboardSummary(period: DashboardPeriod) async throws -> DashboardSummaryDTO {
        try await getJSON(path: "/dashboard/summary", query: [URLQueryItem(name: "period", value: period.rawValue)])
    }
}
