// [review:need-review] PHASE-01/36-ios-category-charts, PHASE-01/38-ios-avoid-streaks, PHASE-01/37-ios-insights, PHASE-01/39-server-idempotency-key-entries, PHASE-01/208
// summary: URLSession async/await HTTP client; /api/v1 JSON; EntriesAPI/CategoryDetailAPI refine a shared EntryMutationAPI base (list/patch/delete); CategoryDetailAPI exposes GET /table; TodayAPI adds GET /categories/{id}/streak; InsightsAPI adds POST/GET /insights; createEntry forwards an optional Idempotency-Key header; request helpers are internal for APIClient+<Feature>.swift extensions; APIClient.live() is the single production factory
import Foundation
import os

/// API surface needed by the Today screen; `APIClient` is the production implementation.
protocol TodayAPI {
    func fetchCategories() async throws -> [CategoryDTO]
    func fetchEntries(startDate: String, endDate: String) async throws -> [EntryDTO]
    func createEntry(_ entry: EntryCreateDTO) async throws -> EntryDTO
    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO
    func fetchStreak(categoryId: Int) async throws -> CategoryStreakDTO
}

/// API surface needed by the Table screen; `APIClient` is the production implementation.
protocol TableAPI {
    func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO
    func fetchEntries(categoryId: Int, date: String) async throws -> [EntryDTO]
}

/// API surface needed by the Categories screen; `APIClient` is the production implementation.
protocol CategoriesAPI {
    func fetchCategories() async throws -> [CategoryDTO]
    func createCategory(_ payload: CategoryCreateDTO) async throws -> CategoryDTO
    func updateCategory(id: Int, _ payload: CategoryUpdateDTO) async throws -> CategoryDTO
    func deleteCategory(id: Int) async throws
    func addField(categoryID: Int, _ payload: FieldCreateDTO) async throws -> FieldDTO
}

/// Entry-mutation endpoints shared by every entry-history view model: list one
/// (or all) category's entries, PATCH an entry, DELETE an entry. The single source
/// of these signatures — screen-specific protocols refine it rather than re-declaring.
protocol EntryMutationAPI {
    func fetchEntries(categoryId: Int?) async throws -> [EntryDTO]
    func updateEntry(id: Int, _ payload: EntryUpdateDTO) async throws -> EntryDTO
    func deleteEntry(id: Int) async throws
}

/// API surface needed by the Entries history screen; `APIClient` is the production
/// implementation. Adds all-category listing on top of the shared mutation surface.
protocol EntriesAPI: EntryMutationAPI {
    func fetchCategories() async throws -> [CategoryDTO]
}

/// API surface needed by the single-category detail screen; `APIClient` is the production
/// implementation. Adds generic entry creation (quick-add) and the aggregated
/// `GET /table` feed (used to draw the category chart) on top of the shared
/// mutation surface used for listing, editing, and deleting.
protocol CategoryDetailAPI: EntryMutationAPI {
    func createEntry(_ entry: EntryCreateDTO) async throws -> EntryDTO
    func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO
}

/// API surface needed by the Dashboard screen; `APIClient` is the production implementation.
/// Reuses existing list endpoints — the dashboard derives its counters and recent-activity
/// feed from unfiltered categories/entries plus the journal total (no dedicated stats endpoint).
protocol DashboardAPI {
    func fetchCategories() async throws -> [CategoryDTO]
    func fetchEntries(categoryId: Int?) async throws -> [EntryDTO]
    func fetchJournalList() async throws -> JournalListResponseDTO
}

/// API surface needed by the Journal screen; `APIClient` is the production implementation.
protocol JournalAPI {
    func fetchJournalEntries() async throws -> [JournalEntryDTO]
    func createJournalEntry(_ payload: JournalEntryCreateDTO) async throws -> JournalEntryDTO
    func updateJournalEntry(id: Int, _ payload: JournalEntryUpdateDTO) async throws -> JournalEntryDTO
    func deleteJournalEntry(id: Int) async throws
}

/// API surface needed by the Insights screen; `APIClient` is the production implementation.
/// Backs the "разбор периода" flow: run a fresh analysis (POST, generous timeout since the
/// backend calls the LLM synchronously), list past reports, and fetch one in full.
protocol InsightsAPI {
    func fetchInsights() async throws -> [InsightListItemDTO]
    func fetchInsight(id: Int) async throws -> InsightReportDTO
    func createInsight(_ payload: InsightRequestDTO) async throws -> InsightReportDTO
}

/// Errors surfaced by `APIClient`, suitable for user-facing mapping.
enum APIClientError: Error, Equatable {
    case invalidBaseURL
    case unauthorized
    case timeout
    case transport(code: Int)
    case unexpectedStatus(Int)
    case invalidResponse
}

extension APIClientError {
    /// Human-readable message for surfacing the error in UI state.
    var userMessage: String {
        switch self {
        case .invalidBaseURL:
            return "Invalid server address"
        case .unauthorized:
            return "Invalid API key (401)"
        case .timeout:
            return "Connection timed out"
        case .transport(let code):
            return "Network error (\(code))"
        case .unexpectedStatus(let status):
            return "Server returned status \(status)"
        case .invalidResponse:
            return "Invalid server response"
        }
    }
}

/// Thin async HTTP client for the Habit Tracker backend.
/// Base URL and API key are injected so Settings can reconfigure it at runtime.
final class APIClient {
    static let apiKeyHeader = "X-API-Key"
    static let defaultTimeout: TimeInterval = 10

    private let baseURL: URL
    private let apiKeyProvider: () -> String?
    /// Internal so a feature extension can open a byte stream (`session.bytes(for:)`,
    /// e.g. chat SSE) on the same configured session the JSON helpers use.
    let session: URLSession
    private let timeout: TimeInterval

    init(
        baseURL: URL,
        apiKeyProvider: @escaping () -> String?,
        session: URLSession = .shared,
        timeout: TimeInterval = APIClient.defaultTimeout
    ) {
        self.baseURL = baseURL
        self.apiKeyProvider = apiKeyProvider
        self.session = session
        self.timeout = timeout
    }

    /// Parses a user-entered server address into a validated base URL.
    /// Single source of truth for Settings and Today so the rules never diverge.
    static func makeBaseURL(from address: String) -> URL? {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme != nil, url.host != nil else {
            return nil
        }
        return url
    }

    /// Hits `GET /` (backend health/root endpoint). Throws a typed error on any failure.
    func checkConnection() async throws {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw APIClientError.invalidBaseURL
        }
        if components.path.isEmpty {
            components.path = "/"
        }
        guard let url = components.url else {
            throw APIClientError.invalidBaseURL
        }
        _ = try await send(makeRequest(url: url, method: "GET"))
    }
}

// MARK: - Production factory

extension APIClient {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "APIClient")

    /// Builds the production client from stored Settings: the server address from
    /// `UserDefaults`, the API key from the Keychain. The key is read again on every
    /// request, so a key saved in Settings applies without rebuilding the client.
    /// Returns `nil` while no valid server address is stored.
    ///
    /// `timeout` defaults to the standard budget; callers that hit a slow synchronous
    /// endpoint (AI insights block on the LLM) pass a longer one. The other parameters
    /// exist for Settings and tests; every screen calls plain `APIClient.live()`.
    static func live(
        timeout: TimeInterval = APIClient.defaultTimeout,
        defaults: UserDefaults = .standard,
        keychain: KeychainStore = KeychainStore(),
        session: URLSession = .shared
    ) -> APIClient? {
        let address = defaults.string(forKey: SettingsViewModel.serverAddressDefaultsKey) ?? ""
        guard let baseURL = makeBaseURL(from: address) else {
            return nil
        }
        return APIClient(
            baseURL: baseURL,
            apiKeyProvider: {
                do {
                    return try keychain.read(SettingsViewModel.apiKeyKeychainKey)
                } catch {
                    // A Keychain failure must not crash a background request:
                    // send it without a key and let the backend answer 401,
                    // which surfaces as a visible error. Logged (no secrets).
                    logger.error("Keychain read for API key failed: \(String(describing: error))")
                    return nil
                }
            },
            session: session,
            timeout: timeout
        )
    }
}

// MARK: - Screen APIs (JSON endpoints under /api/v1)
//
// Existing screens conform here. A new feature declares its protocol and endpoints
// in its own `API/APIClient+<Feature>.swift` (`extension APIClient: <Feature>API`)
// on top of the internal helpers below, and its DTOs in `API/DTOs+<Feature>.swift`.

extension APIClient: TodayAPI, TableAPI, CategoriesAPI, EntriesAPI, JournalAPI, DashboardAPI, CategoryDetailAPI, InsightsAPI {
    static let apiV1Path = "/api/v1"

    func fetchInsights() async throws -> [InsightListItemDTO] {
        try await getJSON(path: "/insights", query: [])
    }

    func fetchInsight(id: Int) async throws -> InsightReportDTO {
        try await getJSON(path: "/insights/\(id)", query: [])
    }

    func createInsight(_ payload: InsightRequestDTO) async throws -> InsightReportDTO {
        try await sendJSON(path: "/insights", method: "POST", body: payload)
    }

    func fetchCategories() async throws -> [CategoryDTO] {
        try await getJSON(path: "/categories", query: [])
    }

    func createCategory(_ payload: CategoryCreateDTO) async throws -> CategoryDTO {
        try await sendJSON(path: "/categories", method: "POST", body: payload)
    }

    func updateCategory(id: Int, _ payload: CategoryUpdateDTO) async throws -> CategoryDTO {
        try await sendJSON(path: "/categories/\(id)", method: "PATCH", body: payload)
    }

    func deleteCategory(id: Int) async throws {
        let url = try makeAPIURL(path: "/categories/\(id)", query: [])
        _ = try await send(makeRequest(url: url, method: "DELETE"))
    }

    func addField(categoryID: Int, _ payload: FieldCreateDTO) async throws -> FieldDTO {
        try await sendJSON(path: "/categories/\(categoryID)/fields", method: "POST", body: payload)
    }

    func fetchEntries(startDate: String, endDate: String) async throws -> [EntryDTO] {
        try await getJSON(
            path: "/entries",
            query: [
                URLQueryItem(name: "start_date", value: startDate),
                URLQueryItem(name: "end_date", value: endDate),
            ]
        )
    }

    /// Foreground create (`TodayAPI`/`CategoryDetailAPI`): no idempotency key — an
    /// online save posts once and never replays, so there is nothing to de-duplicate.
    func createEntry(_ entry: EntryCreateDTO) async throws -> EntryDTO {
        try await createEntry(entry, idempotencyKey: nil)
    }

    /// Outbox replay (`OutboxPosting`): carries the stable `PendingEntry.id` as the
    /// `Idempotency-Key` so a lost-ack retry returns the original entry, not a duplicate.
    func createEntry(
        _ entry: EntryCreateDTO, idempotencyKey: String?
    ) async throws -> EntryDTO {
        try await sendJSON(
            path: "/entries", method: "POST", body: entry, idempotencyKey: idempotencyKey
        )
    }

    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO {
        try await sendJSON(path: "/entries/checklist", method: "PUT", body: payload)
    }

    func fetchStreak(categoryId: Int) async throws -> CategoryStreakDTO {
        try await getJSON(path: "/categories/\(categoryId)/streak", query: [])
    }

    func fetchEntries(categoryId: Int?) async throws -> [EntryDTO] {
        var query: [URLQueryItem] = []
        if let categoryId {
            query.append(URLQueryItem(name: "category_id", value: String(categoryId)))
        }
        return try await getJSON(path: "/entries", query: query)
    }

    func updateEntry(id: Int, _ payload: EntryUpdateDTO) async throws -> EntryDTO {
        try await sendJSON(path: "/entries/\(id)", method: "PATCH", body: payload)
    }

    func deleteEntry(id: Int) async throws {
        let url = try makeAPIURL(path: "/entries/\(id)", query: [])
        _ = try await send(makeRequest(url: url, method: "DELETE"))
    }

    func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO {
        try await getJSON(
            path: "/table",
            query: [
                URLQueryItem(name: "date_from", value: dateFrom),
                URLQueryItem(name: "date_to", value: dateTo),
            ]
        )
    }

    func fetchEntries(categoryId: Int, date: String) async throws -> [EntryDTO] {
        try await getJSON(
            path: "/entries",
            query: [
                URLQueryItem(name: "category_id", value: String(categoryId)),
                URLQueryItem(name: "start_date", value: date),
                URLQueryItem(name: "end_date", value: date),
            ]
        )
    }

    func fetchJournalList() async throws -> JournalListResponseDTO {
        try await getJSON(path: "/journal", query: [])
    }

    func fetchJournalEntries() async throws -> [JournalEntryDTO] {
        try await fetchJournalList().items
    }

    func createJournalEntry(_ payload: JournalEntryCreateDTO) async throws -> JournalEntryDTO {
        try await sendJSON(path: "/journal", method: "POST", body: payload)
    }

    func updateJournalEntry(
        id: Int, _ payload: JournalEntryUpdateDTO
    ) async throws -> JournalEntryDTO {
        try await sendJSON(path: "/journal/\(id)", method: "PATCH", body: payload)
    }

    func deleteJournalEntry(id: Int) async throws {
        let url = try makeAPIURL(path: "/journal/\(id)", query: [])
        _ = try await send(makeRequest(url: url, method: "DELETE"))
    }

    func sendJSON<Body: Encodable, Response: Decodable>(
        path: String, method: String, body: Body, idempotencyKey: String? = nil
    ) async throws -> Response {
        let url = try makeAPIURL(path: path, query: [])
        var request = makeRequest(url: url, method: method)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let idempotencyKey {
            request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key")
        }
        request.httpBody = try APIJSONCoding.makeEncoder().encode(body)
        let data = try await send(request)
        return try decodeJSON(data)
    }

    func getJSON<T: Decodable>(path: String, query: [URLQueryItem]) async throws -> T {
        let url = try makeAPIURL(path: path, query: query)
        let data = try await send(makeRequest(url: url, method: "GET"))
        return try decodeJSON(data)
    }

    func decodeJSON<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try APIJSONCoding.makeDecoder().decode(T.self, from: data)
        } catch {
            throw APIClientError.invalidResponse
        }
    }

    /// Builds `<baseURL>/api/v1<path>` preserving any path prefix in the base URL.
    func makeAPIURL(path: String, query: [URLQueryItem]) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw APIClientError.invalidBaseURL
        }
        let basePath = components.path.hasSuffix("/")
            ? String(components.path.dropLast())
            : components.path
        components.path = basePath + Self.apiV1Path + path
        if !query.isEmpty {
            components.queryItems = query
        }
        guard let url = components.url else {
            throw APIClientError.invalidBaseURL
        }
        return url
    }

    func makeRequest(url: URL, method: String) -> URLRequest {
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        if let apiKey = apiKeyProvider() {
            request.setValue(apiKey, forHTTPHeaderField: Self.apiKeyHeader)
        }
        return request
    }

    /// Executes the request, maps transport/status errors, returns the body on 2xx.
    @discardableResult
    func send(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            throw APIClientError.timeout
        } catch let error as URLError {
            throw APIClientError.transport(code: error.errorCode)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }
        switch httpResponse.statusCode {
        case 200...299:
            return data
        case 401:
            throw APIClientError.unauthorized
        default:
            throw APIClientError.unexpectedStatus(httpResponse.statusCode)
        }
    }
}
