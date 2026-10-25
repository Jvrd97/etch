// [review:need-review] PHASE-03/155, PHASE-03/163
// summary: sends idempotent batches of title-free activity intervals to the API and names the bundle a 422 refused; the default session keeps no cache or cookies on disk
import Foundation

enum AgentAPIError: Error, Equatable {
    /// The catalogue has no such app; the server rejects every batch carrying it.
    case unknownApp(bundleID: String)
    /// A 422 that names none of the sent apps: resending the batch cannot succeed.
    case invalidBatch
    case http(status: Int)
}

struct AgentAPIClient {
    static let requestTimeout: TimeInterval = 10
    private static let unprocessableStatus = 422
    private static let loopbackHosts: Set<String> = ["localhost", "127.0.0.1", "::1"]
    private static let activityPath = "/api/v1/agent/activity"

    let serverAddress: String
    let apiKey: String
    var session: URLSession = AgentAPIClient.diskFreeSession

    /// `URLSession.shared` keeps `Caches/<bundle>/Cache.db` open for writing; the
    /// agent writes only under its own directory (ADR-0019), so nothing is cached.
    static let diskFreeSession = URLSession(configuration: {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        return configuration
    }())

    static func activityEndpoint(for address: String) -> URL? {
        guard let base = URL(string: address.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = base.host?.lowercased(), !host.isEmpty else { return nil }
        let isLoopback = loopbackHosts.contains(host)
        guard base.scheme?.lowercased() == "https" || (base.scheme?.lowercased() == "http" && isLoopback) else {
            return nil
        }
        var components = URLComponents(url: base, resolvingAgainstBaseURL: false)
        components?.path = activityPath
        return components?.url
    }

    /// Maps a refused response onto what the sender should do with the batch.
    ///
    /// The server's 422 names the unknown bundle inside a sentence, so the
    /// bundle is found as a whole word among the ones this batch carried.
    static func error(status: Int, body: Data, sent: [ActivityInterval]) -> AgentAPIError {
        guard status == unprocessableStatus else { return .http(status: status) }
        let detail = (try? JSONDecoder().decode(ErrorBody.self, from: body))?.detail ?? ""
        let words = Set(detail.split(whereSeparator: \.isWhitespace).map(String.init))
        guard let bundleID = sent.lazy.map(\.bundleID).first(where: words.contains) else {
            return .invalidBatch
        }
        return .unknownApp(bundleID: bundleID)
    }

    func send(_ intervals: [ActivityInterval]) async throws {
        guard !intervals.isEmpty else { return }
        guard let url = Self.activityEndpoint(for: serverAddress) else { throw URLError(.badURL) }

        var request = URLRequest(url: url, timeoutInterval: Self.requestTimeout)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        request.httpBody = try encoder.encode(Batch(intervals: intervals))
        let (body, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(response.statusCode) else {
            throw Self.error(status: response.statusCode, body: body, sent: intervals)
        }
    }

    private struct Batch: Encodable {
        let intervals: [ActivityInterval]
    }

    /// A string `detail` is the catalogue refusal; a validation list decodes to nothing.
    private struct ErrorBody: Decodable {
        let detail: String
    }
}
