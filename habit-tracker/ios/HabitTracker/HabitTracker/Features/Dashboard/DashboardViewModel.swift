// [review:need-review] PHASE-03/304
// summary: Dashboard state — the server's summary of the week or the month through the read cache (each period under its own key; offline answers carry their moment), the period switch with a late answer of a period left behind dropped, a return to the screen and pull to refresh read in place, errors in Russian; the day is the server's `today`, the phone's clock is never asked
import Foundation

@MainActor
final class DashboardViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var summary: DashboardSummaryDTO?
    @Published private(set) var period: DashboardPeriod = .week
    /// Set while the screen shows a cached answer because the server was out of reach: when it was fetched.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last in-place refresh failed; the screen keeps what it had.
    @Published private(set) var refreshError: String?

    private let apiProvider: () -> DashboardSummaryAPI?
    private let cache: ReadThroughCache
    /// Bumped by every read; an answer that finds a newer number was asked about a period the person left.
    private var generation = 0

    init(
        apiProvider: @escaping () -> DashboardSummaryAPI?,
        cacheStore: CacheStore,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
    }

    convenience init(api: DashboardSummaryAPI, cacheStore: CacheStore, now: @escaping () -> Date = Date.init) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, now: now)
    }

    /// The provider is re-evaluated on every read, so a changed server address in Settings takes effect without a restart.
    static func live() -> DashboardViewModel {
        DashboardViewModel(apiProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared)
    }

    static func cacheKey(for period: DashboardPeriod) -> String {
        "dashboard.summary.\(period.rawValue)"
    }

    /// The server's day of the answer on screen.
    var serverToday: String? { summary?.today }

    // MARK: Reading

    func load() async {
        await read(silent: false)
    }

    /// The screen came on again. With numbers already shown they are read in place:
    /// a loader over what the person was reading would be a step back.
    func appear() async {
        if summary == nil {
            await load()
        } else {
            await refresh()
        }
    }

    /// Pull to refresh: the screen stays, so the gesture is not cancelled by its own redraw.
    func refresh() async {
        await read(silent: true)
    }

    /// Switches the window. The numbers of the other period are dropped at once: under «Месяц» they would be a lie.
    func select(_ newPeriod: DashboardPeriod) async {
        guard newPeriod != period else { return }
        period = newPeriod
        summary = nil
        offlineAsOf = nil
        await read(silent: false)
    }

    private func read(silent: Bool) async {
        generation += 1
        let mine = generation
        let asked = period
        refreshError = nil
        if !silent { state = .loading }
        guard let api = apiProvider() else {
            fail(DashboardFormat.notConfiguredMessage, silent: silent)
            return
        }
        do {
            let outcome = try await cache.load(key: Self.cacheKey(for: asked)) {
                try await api.fetchDashboardSummary(period: asked)
            }
            guard mine == generation else { return }
            show(outcome)
        } catch let error as APIClientError {
            guard mine == generation else { return }
            fail(DashboardFormat.message(for: error), silent: silent)
        } catch {
            guard mine == generation else { return }
            fail(DashboardFormat.loadFailedMessage, silent: silent)
        }
    }

    private func show(_ outcome: CacheOutcome<DashboardSummaryDTO>) {
        switch outcome {
        case .fresh(let value):
            summary = value
            offlineAsOf = nil
        case .stale(let value, let updatedAt):
            summary = value
            offlineAsOf = updatedAt
        }
        state = .loaded
    }

    private func fail(_ message: String, silent: Bool) {
        if silent {
            refreshError = message
        } else {
            state = .failure(message)
        }
    }
}
