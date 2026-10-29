// [review:need-review] PHASE-03/229, PHASE-03/243, PHASE-03/261, PHASE-03/262
// summary: Week screen state — the running or a named week through the read cache (each week under its own key, the week running by the calendar also under `current` whichever way it was opened, so stepping back works offline; offline answers carry their moment; a cached week that has since ended loses its «не закончилась» note), stepping between weeks with a late answer dropped, return to the screen refreshes in place, and the AI narrative on request (one request per week, a late text of a superseded request dropped, statuses in words)
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

    /// The AI text is written on the server by a model. The server gives the model 120 s per attempt
    /// (`LLM_TIMEOUT_SECONDS`) and answers 502 when it gives up. The client waits 150 s, so the usual
    /// refusal arrives before the client's own timeout. With `LLM_BACKEND=api` the SDK retries a timeout
    /// (two retries by default), so a slow answer can take up to about 360 s: the client then times out
    /// first and says «модель отвечает долго», which is true.
    static let narrativeTimeout: TimeInterval = 150

    private let apiProvider: () -> WeekAPI?
    private let narrativeAPIProvider: () -> WeekAPI?
    private let store: CacheStore
    private let cache: ReadThroughCache
    private let now: () -> Date
    /// Bumped by every read; an answer that finds a newer number was asked about a week the person left.
    private var generation = 0
    /// Bumped by every narrative request: only the newest one may put its text on screen.
    private var narrativeToken = 0
    /// The week whose text is being written right now, if any: coming back to it shows «пишу», not a second button.
    private var narrativeWeek: String?

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

    /// The screen came on again. With an answer already shown it is read in place: a loader over
    /// weeks the person was reading would be a step back.
    func appear() async {
        if review == nil {
            await load()
        } else {
            await refresh()
        }
    }

    /// The note under an unfinished week. A cached answer of a week that has ended since is not
    /// «unfinished» any more, whatever the cache remembers; if its figures still cover fewer than seven days,
    /// the note says the data is incomplete.
    var partialNote: String? {
        guard let window = review?.window else { return nil }
        if offlineAsOf != nil, WeekFormat.hasEnded(window, at: now()) {
            if window.countedDays == 0 { return WeekFormat.noCountedDaysText }
            return window.countedDays < WeekFormat.daysInWeek
                ? WeekFormat.incompleteDataNote(countedDays: window.countedDays) : nil
        }
        return WeekFormat.partialNote(window)
    }

    /// The week on screen is the running one; the button back to it has nothing to do there.
    var isShowingRunningWeek: Bool {
        guard let window = review?.window else { return false }
        return WeekFormat.isRunning(window, at: now())
    }

    var showsCurrentButton: Bool {
        requestedIso != nil && !isShowingRunningWeek
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
            fail(WeekFormat.loadFailedMessage, silent: silent)
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
            } else if WeekFormat.isRunning(value.window, at: now()) {
                // …and the other way round: the running week opened by its code is the one «current» means.
                store.save(value, forKey: Self.cacheKey(for: nil), updatedAt: now())
            }
        case .stale(let value, let updatedAt):
            response = value
            offlineAsOf = updatedAt
        }
        if review?.window.isoCode != response.window.isoCode {
            narrative = narrativeWeek == response.window.isoCode ? .writing : .idle
        }
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
    /// One request per week: leaving a week mid-write and coming back shows the same write, not a second one.
    func writeNarrative() async {
        guard canWriteNarrative, let iso = review?.window.isoCode else { return }
        guard let api = narrativeAPIProvider() else {
            narrative = .failure(WeekFormat.notConfiguredMessage)
            return
        }
        narrativeToken += 1
        let mine = narrativeToken
        narrativeWeek = iso
        narrative = .writing
        let result: NarrativeState
        do {
            result = .ready(try await api.writeWeekNarrative(iso: iso).text)
        } catch let error as APIClientError {
            result = .failure(WeekFormat.narrativeMessage(for: error))
        } catch {
            result = .failure(WeekFormat.narrativeFallback)
        }
        // A newer request owns the text now.
        guard mine == narrativeToken else { return }
        narrativeWeek = nil
        // The person may have stepped to another week while the model wrote.
        guard review?.window.isoCode == iso else { return }
        narrative = result
    }
}
