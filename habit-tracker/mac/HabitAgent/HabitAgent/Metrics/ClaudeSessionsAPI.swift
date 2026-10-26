// [review:need-review] PHASE-03/165
// summary: sends a batch of Claude Code session aggregates to POST /api/v1/agent/claude-sessions over the agent's disk-free session; a 422 is told apart from every other refusal so the sender can stop resending a session the server will never take
import Foundation

enum ClaudeSessionsAPIError: Error, Equatable {
    /// The body is invalid for the server (422); resending the same body cannot succeed.
    case rejected
    case http(status: Int)
}

struct ClaudeSessionsAPI {
    static let path = "/api/v1/agent/claude-sessions"
    private static let unprocessableStatus = 422

    let serverAddress: String
    let apiKey: String
    var session: URLSession = AgentAPIClient.diskFreeSession

    /// Same address rules as the activity endpoint (https, or http on loopback); only the path differs.
    static func endpoint(for address: String) -> URL? {
        guard let activity = AgentAPIClient.activityEndpoint(for: address),
              var components = URLComponents(url: activity, resolvingAgainstBaseURL: false) else { return nil }
        components.path = path
        return components.url
    }

    func send(_ sessions: [ClaudeSessionPayload]) async throws {
        guard !sessions.isEmpty else { return }
        guard let url = Self.endpoint(for: serverAddress) else { throw URLError(.badURL) }

        var request = URLRequest(url: url, timeoutInterval: AgentAPIClient.requestTimeout)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        request.httpBody = try JSONEncoder.claudeMetrics.encode(ClaudeSessionBatch(sessions: sessions))
        let (_, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(response.statusCode) else {
            throw response.statusCode == Self.unprocessableStatus
                ? ClaudeSessionsAPIError.rejected
                : ClaudeSessionsAPIError.http(status: response.statusCode)
        }
    }
}
