// [review:need-review] PHASE-03/164
// summary: the agent's heartbeat — what it says about itself (alive, Accessibility, the titles switch read from the server — each null while unknown, queue depth, last flush, one error code from the server's closed vocabulary), the request that carries it, and the reporter that sends it at once, every minute and after each flush, losing nothing when a send is lost
import Foundation
import os

/// The only words the agent may put in `last_error`.
///
/// The server keeps a closed list (`AgentErrorCode` in
/// `backend/app/schemas/agent_heartbeat.py`) and answers 422 to anything else,
/// so an exception's text, a path or a window title cannot leave the mac by this
/// road even by mistake. A new case here needs a new member there.
enum HeartbeatErrorCode: String, CaseIterable, Encodable {
    /// Intervals did not reach the server within the retention and were dropped.
    case expired
    /// The catalogue has no such app.
    case unknownApp = "unknown_app"
    /// The server refuses a batch for good.
    case invalidBatch = "invalid_batch"
    /// A send failed: no network, or a server that is down.
    case network
    /// The disk queue could not be opened; intervals wait in memory.
    case queueUnavailable = "queue_unavailable"
    /// Claude Code logs were read and no record was recognised. Sent by the metrics reader.
    case claudeFormat = "claude_format"

    /// What a flush that attempted something says about it; nil for a clean one.
    init?(summary: FlushSummary) {
        if summary.serverRefuses {
            self = .invalidBatch
        } else if summary.failed {
            self = .network
        } else if !summary.droppedBundles.isEmpty {
            self = .unknownApp
        } else if summary.droppedInvalid > 0 {
            self = .invalidBatch
        } else if summary.expired > 0 {
            self = .expired
        } else {
            return nil
        }
    }
}

/// What the agent says about itself in one report.
struct Heartbeat: Encodable, Equatable {
    let agentID: String
    let agentVersion: String
    /// Nil — not known yet. Until window titles are collected (#156/#157) the agent
    /// has no use for the permission and says nil, which the web draws as no banner.
    let accessibilityGranted: Bool?
    /// Nil until the server has answered once; a guess would show a false «titles are off».
    let titlesEnabled: Bool?
    let samplingSeconds: Int
    let queueDepth: Int
    let lastFlushAt: Date?
    let lastError: HeartbeatErrorCode?

    enum CodingKeys: String, CodingKey {
        case agentID = "agent_id"
        case agentVersion = "agent_version"
        case accessibilityGranted = "accessibility_granted"
        case titlesEnabled = "titles_enabled"
        case samplingSeconds = "sampling_seconds"
        case queueDepth = "queue_depth"
        case lastFlushAt = "last_flush_at"
        case lastError = "last_error"
    }

    /// The two flags are written out as `null` when unknown: the server refuses a
    /// body that leaves them out, and the synthesized encoder would leave them out.
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(agentID, forKey: .agentID)
        try container.encode(agentVersion, forKey: .agentVersion)
        try container.encode(accessibilityGranted, forKey: .accessibilityGranted)
        try container.encode(titlesEnabled, forKey: .titlesEnabled)
        try container.encode(samplingSeconds, forKey: .samplingSeconds)
        try container.encode(queueDepth, forKey: .queueDepth)
        try container.encodeIfPresent(lastFlushAt, forKey: .lastFlushAt)
        try container.encodeIfPresent(lastError, forKey: .lastError)
    }
}

/// The server's answer about the titles switch to a poll that may carry the last ETag.
enum TitlesAnswer: Equatable {
    case notModified
    case value(Bool, etag: String?)
}

/// The part of a report that lives in the queue and the flusher.
struct HeartbeatState: Equatable {
    var queueDepth = 0
    var lastFlushAt: Date?
    var lastError: HeartbeatErrorCode?
}

enum HeartbeatError: Error {
    /// No server address or key yet: nothing to report to.
    case notConfigured
}

struct HeartbeatClient {
    private static let heartbeatPath = "/api/v1/agent/heartbeat"
    private static let configPath = "/api/v1/agent/config"

    let serverAddress: String
    let apiKey: String
    var session: URLSession = AgentAPIClient.diskFreeSession

    /// Nil for an address the agent does not talk to (plain HTTP to a remote host).
    static func request(for beat: Heartbeat, serverAddress: String, apiKey: String) -> URLRequest? {
        guard let url = PanelAPIClient.endpoint(for: serverAddress, path: heartbeatPath) else { return nil }
        var request = URLRequest(url: url, timeoutInterval: AgentAPIClient.requestTimeout)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        request.httpBody = try? encoder.encode(beat)
        return request
    }

    func send(_ beat: Heartbeat) async throws {
        guard let request = Self.request(for: beat, serverAddress: serverAddress, apiKey: apiKey) else {
            throw URLError(.badURL)
        }
        let (_, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(response.statusCode) else { throw AgentAPIError.http(status: response.statusCode) }
    }

    private static let notModified = 304

    /// The server's switch of window titles, which the web banner reports back.
    /// With the ETag of the last answer the server replies 304 and the body is not read again.
    func fetchTitles(etag: String?) async throws -> TitlesAnswer {
        guard let url = PanelAPIClient.endpoint(for: serverAddress, path: Self.configPath) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: AgentAPIClient.requestTimeout)
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        if let etag { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        let (body, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        if response.statusCode == Self.notModified { return .notModified }
        guard (200..<300).contains(response.statusCode) else { throw AgentAPIError.http(status: response.statusCode) }
        let titles = try JSONDecoder().decode(Titles.self, from: body).titlesEnabled
        return .value(titles, etag: response.value(forHTTPHeaderField: "ETag"))
    }

    private struct Titles: Decodable {
        let titlesEnabled: Bool

        enum CodingKeys: String, CodingKey {
            case titlesEnabled = "titles_enabled"
        }
    }
}

/// Sends the heartbeat at once, every `interval`, and whenever a flush asks for it.
@MainActor
final class HeartbeatReporter {
    /// The agent reports every minute; the server calls it silent after thirty missed.
    static let defaultInterval: TimeInterval = 60
    private static let agentIDKey = "agent-id"
    private static let logger = Logger(subsystem: AgentPaths.identifier, category: "Heartbeat")

    private let agentID: String
    private let agentVersion: String
    private let samplingSeconds: Int
    private let interval: TimeInterval
    private let state: @MainActor () -> HeartbeatState
    private let accessibilityGranted: @MainActor () -> Bool?
    /// Gets the last ETag; nil when the server could not be asked, and the last answer then stands.
    private let titles: @MainActor (String?) async -> TitlesAnswer?
    private let send: @MainActor (Heartbeat) async throws -> Void
    /// Nil until the server has answered once.
    private var knownTitlesEnabled: Bool?
    private var titlesETag: String?
    private var sending = false
    private var again = false
    private var loop: Task<Void, Never>?

    init(
        agentID: String,
        agentVersion: String,
        samplingSeconds: Int,
        interval: TimeInterval = HeartbeatReporter.defaultInterval,
        state: @escaping @MainActor () -> HeartbeatState,
        accessibilityGranted: @escaping @MainActor () -> Bool?,
        titles: @escaping @MainActor (String?) async -> TitlesAnswer?,
        send: @escaping @MainActor (Heartbeat) async throws -> Void
    ) {
        self.agentID = agentID
        self.agentVersion = agentVersion
        self.samplingSeconds = samplingSeconds
        self.interval = interval
        self.state = state
        self.accessibilityGranted = accessibilityGranted
        self.titles = titles
        self.send = send
    }

    /// The reporter wired to the real machine: its own id, the app's version,
    /// the system's answer about Accessibility and the server it already talks to.
    static func live(
        samplingSeconds: Int,
        state: @escaping @MainActor () -> HeartbeatState,
        client: @escaping @MainActor () -> HeartbeatClient?
    ) -> HeartbeatReporter {
        HeartbeatReporter(
            agentID: persistentAgentID(),
            agentVersion: String(
                (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0")
                    .prefix(20)
            ),
            samplingSeconds: samplingSeconds,
            state: state,
            // Unknown on purpose until #156/#157: no window titles are collected, so the
            // permission is not needed and `false` would raise a banner about nothing.
            // When titles are collected this becomes `AXIsProcessTrusted()`, and the web
            // banner appears by itself.
            accessibilityGranted: { nil },
            titles: { etag in try? await client()?.fetchTitles(etag: etag) },
            send: { beat in
                guard let client = client() else { throw HeartbeatError.notConfigured }
                try await client.send(beat)
            }
        )
    }

    /// One id per machine and per install, so a second mac is a second row on the server.
    private static func persistentAgentID(defaults: UserDefaults = .standard) -> String {
        if let stored = defaults.string(forKey: agentIDKey) { return stored }
        let fresh = UUID().uuidString
        defaults.set(fresh, forKey: agentIDKey)
        return fresh
    }

    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            // The loop holds the reporter only for the length of one beat: once it
            // is gone `tick()` answers nil and the loop ends.
            while !Task.isCancelled {
                guard let interval = await self?.tick() else { return }
                try? await Task.sleep(for: .seconds(interval))
            }
        }
    }

    func stop() {
        loop?.cancel()
        loop = nil
    }

    private func tick() async -> TimeInterval {
        await beat()
        return interval
    }

    /// Reports now. A request that comes while a report is on its way is answered
    /// by one more report with the state as it is by then, so a flush that ends
    /// during a send is never reported with the numbers from before it.
    func beat() async {
        if sending {
            again = true
            return
        }
        sending = true
        defer { sending = false }
        repeat {
            again = false
            await sendOnce()
        } while again
    }

    private func sendOnce() async {
        switch await titles(titlesETag) {
        case .value(let enabled, let etag):
            knownTitlesEnabled = enabled
            titlesETag = etag
        case .notModified, nil:
            break
        }
        let now = state()
        let beat = Heartbeat(
            agentID: agentID,
            agentVersion: agentVersion,
            accessibilityGranted: accessibilityGranted(),
            titlesEnabled: knownTitlesEnabled,
            samplingSeconds: samplingSeconds,
            queueDepth: now.queueDepth,
            lastFlushAt: now.lastFlushAt,
            lastError: now.lastError
        )
        do {
            try await send(beat)
        } catch {
            // The next beat is a minute away and carries the same facts; there is nothing to queue.
            Self.logger.notice("Heartbeat not sent: \(AgentLog.code(of: error), privacy: .public)")
        }
    }
}
