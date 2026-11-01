// [review:need-review] PHASE-01/216
// [review:need-review] PHASE-03/295
// summary: GoalsAPI — GET /goals (levels, milestones, the current quarter), PATCH /goals/milestones/{code} that moves one milestone, and PUT /goals/quarter/{quarter} that writes the quarter's goals as one set and hands the server's reason back on 409/422; APIClient implements it on the shared request helpers
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the quarter PUT, which does not go through `send`, notes its write in `ServerWrites` too
import Foundation

/// API surface of the Goals screen; `APIClient` is the production implementation.
protocol GoalsAPI {
    func fetchGoals() async throws -> GoalsBoardDTO
    /// `done` dates the milestone with the server's day; any other status clears the date.
    func patchMilestone(code: String, status: MilestoneStatus) async throws -> MilestoneDTO
    /// Replaces the quarter's goals with this set (at most five) and answers the whole board.
    func putQuarterGoals(quarter: String, goals: [QuarterGoalInDTO]) async throws -> GoalsBoardDTO
}

extension APIClient: GoalsAPI {
    func fetchGoals() async throws -> GoalsBoardDTO {
        try await getJSON(path: "/goals", query: [])
    }

    func patchMilestone(code: String, status: MilestoneStatus) async throws -> MilestoneDTO {
        try await sendJSON(path: "/goals/milestones/\(code)", method: "PATCH", body: MilestonePatchDTO(status: status))
    }

    func putQuarterGoals(quarter: String, goals: [QuarterGoalInDTO]) async throws -> GoalsBoardDTO {
        let url = try makeAPIURL(path: "/goals/quarter/\(quarter)", query: [])
        var request = makeRequest(url: url, method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try APIJSONCoding.makeEncoder().encode(QuarterGoalsPutDTO(goals: goals))
        // Answered or not, the write may have changed what a cached snapshot shows.
        defer { ServerWrites.note() }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            throw APIClientError.timeout
        } catch let error as URLError {
            throw APIClientError.transport(code: error.errorCode)
        }
        guard let http = response as? HTTPURLResponse else { throw APIClientError.invalidResponse }
        switch http.statusCode {
        case 200...299:
            return try decodeJSON(data)
        case 401:
            throw APIClientError.unauthorized
        case 409, 422:
            // `send` drops the body; here the reason is the point. FastAPI's own validation answers a
            // list in `detail`, which is not words for a person, so only a string passes.
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            guard let detail, !detail.isEmpty else { throw APIClientError.unexpectedStatus(http.statusCode) }
            throw GoalsWriteError.rejected(status: http.statusCode, detail: detail)
        default:
            throw APIClientError.unexpectedStatus(http.statusCode)
        }
    }
}
