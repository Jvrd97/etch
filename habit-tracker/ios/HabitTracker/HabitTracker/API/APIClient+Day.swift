// [review:need-review] PHASE-01/211
// summary: DayAPI — GET /day[/{on}] (with ?opened=true), PUT marks, category-linked facts (POST with Idempotency-Key, PUT, DELETE with ?mark=unmark), PUT notebook, POST close/review and close/final; APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Day screen; `APIClient` is the production implementation.
protocol DayAPI {
    /// `date == nil` asks for the server's today (the day turns at the rule's own hour).
    func fetchDay(date: String?) async throws -> DayDetailDTO
    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO
    func recordFact(
        date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String
    ) async throws -> PlanFactWriteDTO
    func correctFact(
        date: String, itemID: UUID, entryID: Int, _ payload: PlanFactRequestDTO
    ) async throws -> PlanFactWriteDTO
    func removeFact(
        date: String, itemID: UUID, entryID: Int, unmark: Bool
    ) async throws -> PlanFactWriteDTO
    func saveNotebook(date: String, content: String) async throws
    func reviewDay(
        date: String, _ payload: DayClosingRequestDTO, idempotencyKey: String
    ) async throws -> DaySummaryDTO
    func closeDay(
        date: String, _ payload: DayClosingRequestDTO, idempotencyKey: String
    ) async throws -> DaySummaryDTO
}

extension APIClient: DayAPI {
    func fetchDay(date: String?) async throws -> DayDetailDTO {
        // `opened=true`: a person is looking at this day, which is what fills `opened_at`.
        try await getJSON(
            path: date.map { "/day/\($0)" } ?? "/day",
            query: [URLQueryItem(name: "opened", value: "true")]
        )
    }

    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO {
        try await sendJSON(
            path: "/day/\(date)/marks/\(itemID.uuidString.lowercased())", method: "PUT", body: payload
        )
    }

    func recordFact(
        date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String
    ) async throws -> PlanFactWriteDTO {
        try await sendJSON(
            path: factsPath(date: date, itemID: itemID), method: "POST", body: payload,
            idempotencyKey: idempotencyKey
        )
    }

    func correctFact(
        date: String, itemID: UUID, entryID: Int, _ payload: PlanFactRequestDTO
    ) async throws -> PlanFactWriteDTO {
        try await sendJSON(
            path: factsPath(date: date, itemID: itemID) + "/\(entryID)", method: "PUT", body: payload
        )
    }

    func removeFact(
        date: String, itemID: UUID, entryID: Int, unmark: Bool
    ) async throws -> PlanFactWriteDTO {
        let query = unmark ? [URLQueryItem(name: "mark", value: "unmark")] : []
        let url = try makeAPIURL(
            path: factsPath(date: date, itemID: itemID) + "/\(entryID)", query: query
        )
        return try decodeJSON(try await send(makeRequest(url: url, method: "DELETE")))
    }

    func saveNotebook(date: String, content: String) async throws {
        let url = try makeAPIURL(path: "/day/\(date)/notebook", query: [])
        var request = makeRequest(url: url, method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try APIJSONCoding.makeEncoder().encode(NotebookRequestDTO(content: content))
        _ = try await send(request)
    }

    func reviewDay(
        date: String, _ payload: DayClosingRequestDTO, idempotencyKey: String
    ) async throws -> DaySummaryDTO {
        try await sendJSON(
            path: "/day/\(date)/close/review", method: "POST", body: payload,
            idempotencyKey: idempotencyKey
        )
    }

    func closeDay(
        date: String, _ payload: DayClosingRequestDTO, idempotencyKey: String
    ) async throws -> DaySummaryDTO {
        try await sendJSON(
            path: "/day/\(date)/close/final", method: "POST", body: payload,
            idempotencyKey: idempotencyKey
        )
    }

    private func factsPath(date: String, itemID: UUID) -> String {
        "/day/\(date)/plan/items/\(itemID.uuidString.lowercased())/facts"
    }
}
