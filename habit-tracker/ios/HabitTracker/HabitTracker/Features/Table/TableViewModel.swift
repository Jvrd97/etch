// [review:need-review] PHASE-01/06-ios-table-view, PHASE-01/11-ios-read-cache, PHASE-01/208
// summary: Table screen state — loads GET /table (default 30 days) through the read cache (serves last window + offline flag when the network is down), paginates older, fetches cell details
import Foundation

@MainActor
final class TableViewModel: ObservableObject {
    /// Discriminated load state for the table grid.
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var grid: TableGrid = .empty
    @Published private(set) var isLoadingOlder = false
    /// When non-nil the grid is showing a cached window because the last load fell back
    /// to the read cache; the value is the timestamp of that cached snapshot.
    @Published private(set) var offlineAsOf: Date?
    @Published var loadOlderErrorMessage: String?

    static let notConfiguredMessage = "Set the server address in Settings"
    /// Number of days fetched per page (initial load and each "load older" step).
    static let pageDays = 30
    /// Read-cache key for the most-recent-window table response.
    static let cacheKey = "table.recent"

    private let apiProvider: () -> TableAPI?
    private let cache: ReadThroughCache
    private let dateFormatter: DateFormatter
    private let calendar: Calendar
    private let now: () -> Date

    /// Accumulated days keyed by their `YYYY-MM-DD` string; the source of truth
    /// the grid is rebuilt from as older pages arrive.
    private var loadedDays: [String: TableDayDTO] = [:]
    private var categories: [TableCategoryMetaDTO] = []
    /// Start of the oldest range already fetched; the next page ends the day before it.
    private var earliestLoadedFrom: Date?

    /// Primary init: the provider is re-evaluated on every load, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(
        apiProvider: @escaping () -> TableAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.now = now
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        self.dateFormatter = formatter
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        self.calendar = calendar
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(
        api: TableAPI,
        cacheStore: CacheStore = InMemoryCacheStore(),
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, timeZone: timeZone, now: now)
    }

    /// Builds the production view model from stored Settings (UserDefaults + Keychain).
    static func live() -> TableViewModel {
        TableViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared
        )
    }

    /// Loads the most recent `pageDays` days, replacing any previously loaded data.
    /// Runs through the read cache: a successful fetch refreshes the grid and the cache;
    /// when the network is down the last cached window is shown with an offline timestamp.
    func load() async {
        state = .loading
        loadOlderErrorMessage = nil
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        let to = now()
        let from = pageStart(endingAt: to)
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                try await api.fetchTable(
                    dateFrom: self.dateFormatter.string(from: from),
                    dateTo: self.dateFormatter.string(from: to)
                )
            }
            let response: TableResponseDTO
            switch outcome {
            case .fresh(let value):
                response = value
                offlineAsOf = nil
            case .stale(let value, let updatedAt):
                response = value
                offlineAsOf = updatedAt
            }
            categories = response.categories
            loadedDays = Dictionary(
                response.days.map { ($0.date, $0) }, uniquingKeysWith: { _, new in new }
            )
            earliestLoadedFrom = from
            rebuildGrid()
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// Fetches the previous `pageDays` days and merges them into the grid.
    /// No-op unless the initial load has succeeded and no page is already in flight.
    func loadOlder() async {
        guard state == .loaded, !isLoadingOlder,
              let api = apiProvider(),
              let currentFrom = earliestLoadedFrom,
              let newTo = calendar.date(byAdding: .day, value: -1, to: currentFrom) else {
            return
        }
        isLoadingOlder = true
        loadOlderErrorMessage = nil
        defer { isLoadingOlder = false }
        let newFrom = pageStart(endingAt: newTo)
        do {
            let response = try await api.fetchTable(
                dateFrom: dateFormatter.string(from: newFrom),
                dateTo: dateFormatter.string(from: newTo)
            )
            for day in response.days {
                loadedDays[day.date] = day
            }
            if !response.categories.isEmpty {
                categories = response.categories
            }
            earliestLoadedFrom = newFrom
            rebuildGrid()
        } catch let error as APIClientError {
            loadOlderErrorMessage = error.userMessage
        } catch {
            loadOlderErrorMessage = "Unexpected error"
        }
    }

    /// Source entries behind a cell: the day's records for the tapped habit,
    /// which the aggregated value was composed from.
    func fetchCellEntries(categoryId: Int, date: String) async throws -> [EntryDTO] {
        guard let api = apiProvider() else {
            throw APIClientError.invalidBaseURL
        }
        return try await api.fetchEntries(categoryId: categoryId, date: date)
    }

    private func pageStart(endingAt end: Date) -> Date {
        calendar.date(byAdding: .day, value: -(Self.pageDays - 1), to: end) ?? end
    }

    private func rebuildGrid() {
        let days = loadedDays.values.sorted { $0.date > $1.date }
        grid = TableGrid(from: TableResponseDTO(categories: categories, days: Array(days)))
    }
}
