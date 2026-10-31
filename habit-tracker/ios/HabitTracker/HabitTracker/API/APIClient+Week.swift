// [review:need-review] PHASE-03/229, PHASE-03/244
// summary: WeekAPI — GET /week-review[/{iso}] (the bare path asks for the server's running week) and POST /week-review/{iso}/narrative (no body, AI text on request) and POST /health-advice (the advice for seven days, on request); APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Week screen; `APIClient` is the production implementation.
protocol WeekAPI {
    /// `iso == nil` asks for the server's running week (it turns at the day boundary, not at midnight).
    func fetchWeekReview(iso: String?) async throws -> WeekReviewDTO
    /// 422: the week is empty. 503: the server has no model. 502: the model failed.
    func writeWeekNarrative(iso: String) async throws -> WeekNarrativeDTO
    /// The advice for the last seven closed days. 422: too little data. 503: no model. 502: the model failed
    /// or the dose net dropped its answer.
    func writeHealthAdvice() async throws -> HealthAdviceDTO
}

private struct HealthAdviceBody: Encodable {
    let days = 7
}

extension APIClient: WeekAPI {
    func fetchWeekReview(iso: String?) async throws -> WeekReviewDTO {
        try await getJSON(path: iso.map { "/week-review/\($0)" } ?? "/week-review", query: [])
    }

    func writeWeekNarrative(iso: String) async throws -> WeekNarrativeDTO {
        let url = try makeAPIURL(path: "/week-review/\(iso)/narrative", query: [])
        return try decodeJSON(try await send(makeRequest(url: url, method: "POST")))
    }

    func writeHealthAdvice() async throws -> HealthAdviceDTO {
        try await sendJSON(path: "/health-advice", method: "POST", body: HealthAdviceBody())
    }
}
