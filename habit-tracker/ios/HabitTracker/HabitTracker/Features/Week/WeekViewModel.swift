// [review:need-review] PHASE-03/229
// summary: Week screen state — the running or a named week through the read cache (each week under its own key, the running one also under its code, so stepping back works offline; offline answers carry their moment), stepping between weeks with a late answer dropped, refresh in place, and the AI narrative on request (statuses in words, dropped when the week changed)
import Foundation

@MainActor
final class WeekViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    enum NarrativeState: Equatable {
        case idle
        case writing
        case ready(String)
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var review: WeekReviewDTO?
    /// Set while the screen shows a cached answer because the server was out of reach: when it was fetched.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last in-place refresh failed; the screen keeps what it had.
    @Published private(set) var refreshError: String?
    @Published private(set) var narrative: NarrativeState = .idle

    /// The week asked for; `nil` is the server's running week.
    private(set) var requestedIso: String?

    /// The AI text is written on the server by a model: a generous timeout, like the insights.
    static let narrativeTimeout: TimeInterval = 120

    private let apiProvider: () -> WeekAPI?
    private let narrativeAPIProvider: () -> WeekAPI?
    private let store: CacheStore
    private let cache: ReadThroughCache
    private let now: () -> Date
    /// Bumped by every read; an answer that finds a newer number was asked about a week the person left.
    private var generation = 0

    init(
        apiProvider: @escaping () -> WeekAPI?,
        narrativeAPIProvider: @escaping () -> WeekAPI?,
        cacheStore: CacheStore,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.narrativeAPIProvider = narrativeAPIProvider
        self.store = cacheStore
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.now = now
    }

    convenience init(api: WeekAPI, cacheStore: CacheStore, now: @escaping () -> Date = Date.init) {
        self.init(
            apiProvider: { api }, narrativeAPIProvider: { api }, cacheStore: cacheStore, now: now
        )
    }

    static func live() -> WeekViewModel {
        WeekViewModel(
            apiProvider: { APIClient.live() },
            narrativeAPIProvider: { APIClient.live(timeout: narrativeTimeout) },
            cacheStore: ReadCacheLive.shared
        )
    }

    static func cacheKey(for iso: String?) -> String {
        "week.review.\(iso ?? "current")"
    }

    // MARK: Reading

    func load() async {
        await read(iso: requestedIso, silent: false)
    }

    /// Pull to refresh: the screen stays, so the gesture is not cancelled by its own redraw.
    func refresh() async {
        await read(iso: requestedIso, silent: true)
    }

    func showPrevious() async {
        guard let review else { return }
        await go(to: review.window.previousIsoCode)
    }

    func showNext() async {
        guard let review else { return }
        await go(to: review.window.nextIsoCode)
    }

    func showCurrent() async {
        await go(to: nil)
    }

    private func go(to iso: String?) async {
        requestedIso = iso
        await read(iso: iso, silent: false)
    }

    private func read(iso: String?, silent: Bool) async {
        generation += 1
        let mine = generation
        refreshError = nil
        if !silent { state = .loading }
        guard let api = apiProvider() else {
            fail(WeekFormat.notConfiguredMessage, silent: silent)
            return
        }
        do {
            let outcome = try await cache.load(key: Self.cacheKey(for: iso)) {
                try await api.fetchWeekReview(iso: iso)
            }
            guard mine == generation else { return }
            show(outcome, askedFor: iso)
        } catch let error as APIClientError {
            guard mine == generation else { return }
            fail(WeekFormat.message(for: error), silent: silent)
        } catch {
            guard mine == generation else { return }
            fail("Не удалось загрузить неделю", silent: silent)
        }
    }

    private func show(_ outcome: CacheOutcome<WeekReviewDTO>, askedFor iso: String?) {
        let response: WeekReviewDTO
        switch outcome {
        case .fresh(let value):
            response = value
            offlineAsOf = nil
            if iso == nil {
                // The running week is also kept under its own code: stepping away and back must not need the network.
                store.save(value, forKey: Self.cacheKey(for: value.window.isoCode), updatedAt: now())
            }
        case .stale(let value, let updatedAt):
            response = value
            offlineAsOf = updatedAt
        }
        if review?.window.isoCode != response.window.isoCode { narrative = .idle }
        review = response
        state = .loaded
    }

    private func fail(_ message: String, silent: Bool) {
        if silent {
            refreshError = message
        } else {
            state = .failure(message)
        }
    }

    // MARK: Narrative

    /// The button is on for a week with data, once at a time.
    var canWriteNarrative: Bool {
        guard state == .loaded, let review else { return false }
        return !WeekFormat.isEmpty(review) && narrative != .writing
    }

    /// Writes the AI text for the week on screen. It needs the network; the text is not kept anywhere.
    func writeNarrative() async {
        guard canWriteNarrative, let iso = review?.window.isoCode else { return }
        guard let api = narrativeAPIProvider() else {
            narrative = .failure(WeekFormat.notConfiguredMessage)
            return
        }
        narrative = .writing
        let result: NarrativeState
        do {
            result = .ready(try await api.writeWeekNarrative(iso: iso).text)
        } catch let error as APIClientError {
            result = .failure(WeekFormat.narrativeMessage(for: error))
        } catch {
            result = .failure(WeekFormat.narrativeFallback)
        }
        // The person may have stepped to another week while the model wrote.
        guard review?.window.isoCode == iso else { return }
        narrative = result
    }
}
