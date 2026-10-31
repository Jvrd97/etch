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

    /// Switches the window at once and drops the numbers of the other period: under «Месяц» they would be a lie.
    /// Returns whether a read is needed. The segment calls this in its setter so it never bounces back for a frame;
    /// the read follows with `load()`. Bumping the generation keeps an answer still on its way for the old period off the screen.
    func switchTo(_ newPeriod: DashboardPeriod) -> Bool {
        guard newPeriod != period else { return false }
        period = newPeriod
        summary = nil
        offlineAsOf = nil
        refreshError = nil
        generation += 1
        return true
    }

    func select(_ newPeriod: DashboardPeriod) async {
        if switchTo(newPeriod) { await load() }
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
            // The screen was left: a cancelled request looks like a lost connection and would show a copy as «не обновлено».
            guard mine == generation, !Task.isCancelled else { return }
            show(outcome)
        } catch let error as APIClientError {
            guard mine == generation, !Task.isCancelled else { return }
            fail(DashboardFormat.message(for: error), silent: silent)
        } catch {
            guard mine == generation, !Task.isCancelled else { return }
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

    /// A quiet failure is only quiet when there are numbers to keep on screen. With nothing shown (the first read still
    /// running, or already failed) the error takes the place of the loader, whoever asked for the read.
    private func fail(_ message: String, silent: Bool) {
        if silent, summary != nil, state == .loaded {
            refreshError = message
        } else {
            state = .failure(message)
        }
    }
}
