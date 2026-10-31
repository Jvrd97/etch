// [review:need-review] PHASE-01/268
// summary: state of the Health tab list — the catalogue with 30 days and baseline, the sync/lag block, the week of nights and workouts, each through the read cache; the catalogue decides the screen (loading, error with retry, loaded, whole catalogue empty), the three side reads only add blocks and a failure of one hides just that block; offline answers carry their moment and a stale lag is not shown as current; a late answer of a superseded read is dropped
import Foundation

@MainActor
final class HealthMetricsViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var metrics: [HealthMetricSeriesDTO] = []
    @Published private(set) var syncStatus: HealthSyncStatusDTO?
    @Published private(set) var nights: [HealthSleepNightDTO]?
    @Published private(set) var workouts: [HealthWorkoutRecordDTO]?
    /// The server's index for «Состояние сегодня»; `nil` while the endpoint is missing or its read failed, and the card is then absent.
    @Published private(set) var healthState: HealthScoreDTO?
    /// Set while the catalogue on screen is the cached one: when it was fetched.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last in-place refresh failed; the screen keeps what it had.
    @Published private(set) var refreshError: String?
    /// The reader's today, `yyyy-MM-dd`, as of the last read.
    private(set) var today = ""

    static let metricsKey = "health.metrics.30"
    static let syncStatusKey = "health.sync-status"
    static let nightsKey = "health.sleep.week"
    static let workoutsKey = "health.workouts.30"
    static let stateKey = "health.state.week"

    private let apiProvider: () -> HealthMetricsAPI?
    private let stateAPIProvider: () -> HealthStateAPI?
    private let cache: ReadThroughCache
    private let now: () -> Date
    private let calendar: Calendar
    /// Bumped by every read; an answer that finds a newer number belongs to a read nobody waits for.
    private var generation = 0

    init(
        apiProvider: @escaping () -> HealthMetricsAPI?,
        stateAPIProvider: @escaping () -> HealthStateAPI? = { nil },
        cacheStore: CacheStore,
        now: @escaping () -> Date = Date.init,
        calendar: Calendar = .current
    ) {
        self.apiProvider = apiProvider
        self.stateAPIProvider = stateAPIProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.now = now
        self.calendar = calendar
    }

    convenience init(api: HealthMetricsAPI, cacheStore: CacheStore, now: @escaping () -> Date = Date.init) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, now: now)
    }

    static func live() -> HealthMetricsViewModel {
        HealthMetricsViewModel(
            apiProvider: { APIClient.live() }, stateAPIProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared
        )
    }

    /// Nothing has ever synced: every metric of the catalogue is without a day.
    var isCatalogEmpty: Bool { metrics.allSatisfy { $0.days.isEmpty } }

    func load() async {
        await read(silent: false)
    }

    /// The screen came on again: with an answer already shown it is read in place.
    func appear() async {
        if state == .loaded { await refresh() } else { await load() }
    }

    func refresh() async {
        await read(silent: true)
    }

    private func read(silent: Bool) async {
        generation += 1
        let mine = generation
        refreshError = nil
        if !silent { state = .loading }
        guard let api = apiProvider() else {
            fail(HealthMetricsFormat.notConfiguredMessage, silent: silent)
            return
        }
        let moment = HealthMetricsFormat.localDate(now(), calendar: calendar)
        let monthStart = HealthMetricsFormat.shiftDate(moment, by: 1 - HealthMetricsFormat.sparklineDays)
        let weekStart = HealthMetricsFormat.shiftDate(moment, by: 1 - HealthMetricsFormat.weekDays)
        let stateAPI = stateAPIProvider()

        // The five reads travel side by side; the cache store is not thread-safe, so what they brought
        // goes through it one after another, each as the `fetch` of its own read-through load.
        async let metricsAnswer = settle { try await api.fetchHealthMetrics(dateFrom: monthStart, dateTo: moment) }
        async let statusAnswer = settle { try await api.fetchHealthSyncStatus() }
        async let sleepAnswer = settle { try await api.fetchHealthSleep(dateFrom: weekStart, dateTo: moment) }
        async let workoutsAnswer = settle { try await api.fetchHealthWorkouts(dateFrom: monthStart, dateTo: moment) }
        async let stateAnswer = settle { () -> HealthStateResponseDTO in
            guard let stateAPI else { throw APIClientError.invalidResponse }
            return try await stateAPI.fetchHealthState()
        }
        let (metricsResult, statusResult, sleepResult, workoutsResult, stateResult) =
            await (metricsAnswer, statusAnswer, sleepAnswer, workoutsAnswer, stateAnswer)
        guard mine == generation else { return }
        do {
            let catalogue = try await cache.load(key: Self.metricsKey) { try metricsResult.get() }
            let syncOutcome = await sideRead(key: Self.syncStatusKey, statusResult)
            let sleepOutcome = await sideRead(key: Self.nightsKey, sleepResult)
            let workoutsOutcome = await sideRead(key: Self.workoutsKey, workoutsResult)
            let stateOutcome = await sideRead(key: Self.stateKey, stateResult)
            guard mine == generation else { return }
            today = moment
            switch catalogue {
            case .fresh(let value):
                metrics = value.metrics
                offlineAsOf = nil
            case .stale(let value, let updatedAt):
                metrics = value.metrics
                offlineAsOf = updatedAt
            }
            // A lag read from the cache is the lag of the moment it was cached, not of now.
            if case .fresh(let value)? = syncOutcome { syncStatus = value } else { syncStatus = nil }
            nights = sleepOutcome.map { $0.value.nights }
            workouts = workoutsOutcome.map { $0.value.workouts }
            healthState = stateOutcome?.value.scores.health
            state = .loaded
        } catch let error as APIClientError {
            guard mine == generation else { return }
            fail(HealthMetricsFormat.message(for: error), silent: silent)
        } catch {
            guard mine == generation else { return }
            fail(HealthMetricsFormat.loadFailedMessage, silent: silent)
        }
    }

    /// A read that only adds a block to the screen: its failure leaves the block out, it never fails the screen.
    private func sideRead<T: Codable>(key: String, _ result: Result<T, Error>) async -> CacheOutcome<T>? {
        try? await cache.load(key: key) { try result.get() }
    }

    private func settle<T>(_ work: () async throws -> T) async -> Result<T, Error> {
        do { return .success(try await work()) } catch { return .failure(error) }
    }

    private func fail(_ message: String, silent: Bool) {
        if silent {
            refreshError = message
        } else {
            state = .failure(message)
        }
    }
}

private extension CacheOutcome {
    var value: T {
        switch self {
        case .fresh(let value): return value
        case .stale(let value, _): return value
        }
    }
}
