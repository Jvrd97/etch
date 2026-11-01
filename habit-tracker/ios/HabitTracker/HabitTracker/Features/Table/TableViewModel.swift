// [review:need-review] PHASE-01/06-ios-table-view, PHASE-01/11-ios-read-cache, PHASE-01/208
// summary: Table screen state — loads GET /table (default 30 days) through the read cache (serves last window + offline flag when the network is down), paginates older, fetches cell details
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the grid opens from the cached window (no loader), an appearance reads again only when the window is not recent, a re-read keeps the grid and says its failure as a line, an older answer never replaces a newer one
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
    /// Why the last re-read of a loaded grid failed; the grid stays.
    @Published private(set) var refreshError: String?

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
    /// Loads, numbered as they are sent, and the newest one shown: an older answer never replaces a newer grid.
    private var loadsSent = 0
    private var loadShown = 0

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

    /// The screen came on: the cached window goes on screen at once, the server is asked only when it is not recent.
    func appear() async {
        showCached()
        if state == .loaded, cache.isRecent(key: Self.cacheKey) { return }
        await load()
    }

    /// Puts the cached window on screen while nothing is shown, without the network.
    func showCached() {
        guard state != .loaded, let cached = cache.peek(TableResponseDTO.self, key: Self.cacheKey) else { return }
        show(cached.value, from: pageStart(endingAt: now()))
        state = .loaded
    }

    /// Loads the most recent `pageDays` days, replacing any previously loaded data.
    /// Runs through the read cache: a successful fetch refreshes the grid and the cache;
    /// when the network is down the last cached window is shown with an offline timestamp.
    /// A grid on screen stays while it is read again.
    func load() async {
        let showsData = state == .loaded
        if !showsData { state = .loading }
        loadOlderErrorMessage = nil
        guard let api = apiProvider() else {
            fail(Self.notConfiguredMessage, showsData: showsData)
            return
        }
        loadsSent += 1
        let load = loadsSent
        let to = now()
        let from = pageStart(endingAt: to)
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                try await api.fetchTable(
                    dateFrom: self.dateFormatter.string(from: from),
                    dateTo: self.dateFormatter.string(from: to)
                )
            }
            guard load > loadShown else { return }
            loadShown = load
            let response: TableResponseDTO
            switch outcome {
            case .fresh(let value):
                response = value
                offlineAsOf = nil
            case .stale(let value, let updatedAt):
                response = value
                offlineAsOf = updatedAt
            }
            show(response, from: from)
            refreshError = nil
            state = .loaded
        } catch let error as APIClientError {
            guard load > loadShown else { return }
            fail(error.userMessage, showsData: showsData)
        } catch {
            guard load > loadShown else { return }
            fail("Unexpected error", showsData: showsData)
        }
    }

    private func show(_ response: TableResponseDTO, from: Date) {
        categories = response.categories
        loadedDays = Dictionary(
            response.days.map { ($0.date, $0) }, uniquingKeysWith: { _, new in new }
        )
        earliestLoadedFrom = from
        rebuildGrid()
    }

    private func fail(_ message: String, showsData: Bool) {
        if showsData { refreshError = message } else { state = .failure(message) }
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
