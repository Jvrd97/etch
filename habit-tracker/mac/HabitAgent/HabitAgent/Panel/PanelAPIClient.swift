// [review:need-review] PHASE-03/241
// summary: the two calls the floating panel makes — GET /agent/config with the last ETag, and POST /agent/activity/manual under an Idempotency-Key — over an ephemeral session, with the same address rules as the activity client; only 422 and 409 are final, every other 4xx (401/403/404 included) goes back to the outbox's Backoff; since #162 also PUT/DELETE /day-mode/{date}, the switch of the day mode (an answer it cannot read is logged to `panel-mode` instead of vanishing)
import Foundation
import os

enum PanelAPIError: Error, Equatable {
    /// No server address or no key yet: nothing to retry until a person sets them.
    case notConfigured
    /// A refusal that may pass — 5xx, 408, 429, and every other 4xx this client does not
    /// name as final, including 401/403/404/405: a wrong key gets rotated, an old server
    /// gets upgraded, and resending the same interval then succeeds. Try again later.
    case http(status: Int)
    /// A refusal the server will repeat for the same request: retrying cannot help.
    /// 422 — the plan item the interval named does not exist; 409 — this
    /// `Idempotency-Key` is already on a record with different bounds, so the server
    /// read it as somebody else's retry (`#163`'s `AgentAPIClient` treats only its own
    /// 422 the same way — a manual interval also owns a key, hence the extra case).
    case rejected(status: Int)
}

struct PanelAPIClient {
    static let requestTimeout: TimeInterval = 10
    private static let configPath = "/api/v1/agent/config"
    private static let manualPath = "/api/v1/agent/activity/manual"
    private static let dayModePath = "/api/v1/day-mode"
    private static let notModified = 304
    private static let finalClientErrors: Set<Int> = [409, 422]

    let serverAddress: String
    let apiKey: String
    /// Ephemeral: the agent writes nothing outside its own folder, and the shared
    /// session keeps a response cache on disk.
    var session = URLSession(configuration: .ephemeral)

    private static let log = Logger(subsystem: "com.talvior.habitagent", category: "panel-mode")

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            let plain = ISO8601DateFormatter()
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            guard let date = plain.date(from: text) ?? fractional.date(from: text) else {
                throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "not a date: \(text)"))
            }
            return date
        }
        return decoder
    }()

    /// The address rules of the activity client (HTTPS, or HTTP for loopback), with another path.
    static func endpoint(for address: String, path: String) -> URL? {
        guard path.hasPrefix("/"),
              let base = AgentAPIClient.activityEndpoint(for: address),
              var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        components.path = path
        return components.url
    }

    /// The page of the day in the web, on the same origin the agent talks to.
    static func dayPageURL(serverAddress: String, dayPath: String) -> URL? {
        endpoint(for: serverAddress, path: dayPath)
    }

    func fetchConfig(etag: String?) async throws -> PollResponse<PanelConfig> {
        guard let url = Self.endpoint(for: serverAddress, path: Self.configPath) else { throw PanelAPIError.notConfigured }
        var request = authorized(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: Self.requestTimeout))
        if let etag { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        let (body, response) = try await data(for: request)
        if response.statusCode == Self.notModified { return .notModified }
        guard response.statusCode == 200 else { throw Self.error(status: response.statusCode) }
        let config = try Self.decoder.decode(PanelConfig.self, from: body)
        return .modified(config, etag: response.value(forHTTPHeaderField: "ETag"))
    }

    func send(_ interval: ManualInterval) async throws {
        guard let url = Self.endpoint(for: serverAddress, path: Self.manualPath) else { throw PanelAPIError.notConfigured }
        var request = authorized(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: Self.requestTimeout))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(interval.key.uuidString, forHTTPHeaderField: "Idempotency-Key")
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        request.httpBody = try encoder.encode(ManualBody(interval))
        let (_, response) = try await data(for: request)
        guard (200..<300).contains(response.statusCode) else { throw Self.error(status: response.statusCode) }
    }

    /// Decides the mode of one date by hand (both fields go: they are independent) or hands the date back to the schedule.
    /// Answers with the mode the server wrote; nil when the body is not one the window knows
    /// (an unknown source): the write went through, the next config repaints.
    @discardableResult
    func change(mode: ModeChange, date: String) async throws -> PanelDayMode? {
        guard let url = Self.endpoint(for: serverAddress, path: "\(Self.dayModePath)/\(date)") else { throw PanelAPIError.notConfigured }
        var request = authorized(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: Self.requestTimeout))
        switch mode {
        case let .decide(kind, nocode):
            request.httpMethod = "PUT"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(DecisionBody(kind: kind, nocode: nocode))
        case .reset:
            request.httpMethod = "DELETE"
        }
        let (body, response) = try await data(for: request)
        guard (200..<300).contains(response.statusCode) else { throw Self.error(status: response.statusCode) }
        do {
            return try JSONDecoder().decode(PanelDayMode.self, from: body)
        } catch {
            // The write went through; only its answer is unreadable. Say why instead of dropping it silently.
            Self.log.error("Day-mode answer not decoded: \(String(describing: error), privacy: .public)")
            return nil
        }
    }

    static func error(status: Int) -> PanelAPIError {
        finalClientErrors.contains(status) ? .rejected(status: status) : .http(status: status)
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        return request
    }

    private func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (body, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (body, response)
    }

    private struct DecisionBody: Encodable {
        let kind: String
        let nocode: Bool
    }

    /// The task title travels in `note`: the interval then reads on the day's tape
    /// without a lookup, and `plan_item_id` is what the server counts time by.
    private struct ManualBody: Encodable {
        let startedAt: Date
        let endedAt: Date
        let localDate: String
        let utcOffsetMinutes: Int
        let planItemID: UUID?
        let note: String?

        init(_ interval: ManualInterval) {
            startedAt = interval.startedAt
            endedAt = interval.endedAt
            localDate = interval.localDate
            utcOffsetMinutes = interval.utcOffsetMinutes
            planItemID = interval.taskID
            note = interval.taskTitle
        }

        enum CodingKeys: String, CodingKey {
            case startedAt = "started_at"
            case endedAt = "ended_at"
            case localDate = "local_date"
            case utcOffsetMinutes = "utc_offset_minutes"
            case planItemID = "plan_item_id"
            case note
        }
    }
}
