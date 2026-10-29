// [review:need-review] PHASE-01/265
// summary: LifeAPI — GET /day-mode (the server's day, which turns at the day boundary, not at midnight) and GET /days?from&to (the same two reads the mobile web timeline makes); APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Life screen; `APIClient` is the production implementation.
protocol LifeAPI {
    func fetchServerDay() async throws -> LifeServerDayDTO
    /// Recorded days of `[from, to]`, both `yyyy-MM-dd`. The server refuses ranges wider than five years.
    func fetchDays(from: String, to: String) async throws -> [LifeDayDTO]
}

extension APIClient: LifeAPI {
    func fetchServerDay() async throws -> LifeServerDayDTO {
        try await getJSON(path: "/day-mode", query: [])
    }

    func fetchDays(from: String, to: String) async throws -> [LifeDayDTO] {
        try await getJSON(
            path: "/days",
            query: [URLQueryItem(name: "from", value: from), URLQueryItem(name: "to", value: to)]
        )
    }
}
