// [review:need-review] PHASE-01/274
// [review:need-review] PHASE-01/270 — days dictionary, weekStatuses once per pair, weekSpeech, future birth refused
// [review:need-review] PHASE-01/265
// summary: Life screen state — the server's day plus the days of the last three years and this one through the read cache (one key; offline shows the last snapshot with its moment), five views (жизнь, год, месяц, неделя, день) over one cursor that stays on the server's day until the reader moves it, stepping per view, the birth date and frame kept on the device, a late answer of a superseded read dropped
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the timeline opens from its cached snapshot (no loader), an appearance reads again only when the snapshot is not recent
import Foundation

enum LifeViewKind: String, CaseIterable, Identifiable {
    case life, year, month, week, day

    var id: String { rawValue }

    var title: String {
        switch self {
        case .life: return "жизнь"
        case .year: return "год"
        case .month: return "месяц"
        case .week: return "неделя"
        case .day: return "день"
        }
    }
}

/// Where the frame is kept between launches.
protocol LifeFrameStore {
    func load() -> LifeFrame?
    func save(_ frame: LifeFrame)
}

struct UserDefaultsLifeFrameStore: LifeFrameStore {
    /// Same name the web keeps its frame under.
    static let key = "habit-tracker:life-frame"
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load() -> LifeFrame? {
        guard let data = defaults.data(forKey: Self.key) else { return nil }
        return try? JSONDecoder().decode(LifeFrame.self, from: data)
    }

    func save(_ frame: LifeFrame) {
        if let data = try? JSONEncoder().encode(frame) {
            defaults.set(data, forKey: Self.key)
        }
    }
}

@MainActor
final class LifeViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    static let notConfiguredMessage = "Укажите адрес сервера в More → Settings"
    static let loadFailedMessage = "Не удалось загрузить дни"
    static let cacheKey = "life.days"

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var snapshot: LifeSnapshotDTO? {
        didSet {
            days = Dictionary((snapshot?.days ?? []).map { ($0.date, $0) }, uniquingKeysWith: { _, last in last })
            snapshotVersion += 1
        }
    }
    /// The snapshot's days by `yyyy-MM-dd`, rebuilt when the snapshot changes.
    private(set) var days: [String: LifeDayDTO] = [:]
    private var snapshotVersion = 0
    private var weekStatusCache: (version: Int, frame: LifeFrame, statuses: [LifeStatus])?
    /// Set while the screen shows a cached answer: when it was fetched.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last in-place refresh failed; the screen keeps what it had.
    @Published private(set) var refreshError: String?
    @Published private(set) var view: LifeViewKind = .life
    @Published private(set) var frame: LifeFrame
    @Published private var movedCursor: Date?

    private let apiProvider: () -> LifeAPI?
    private let cache: ReadThroughCache
    private let frameStore: LifeFrameStore
    private let now: () -> Date
    private var generation = 0

    init(
        apiProvider: @escaping () -> LifeAPI?,
        cacheStore: CacheStore,
        frameStore: LifeFrameStore,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.frameStore = frameStore
        self.now = now
        let stored = frameStore.load()
        // A stored value that no longer parses, or a birth date ahead of today, must not break the counter.
        if let stored, LifeCalendar.parse(stored.birth) != nil, stored.birth <= LifeCalendar.iso(now()), LifeFrame.yearsRange.contains(stored.targetYears) {
            self.frame = stored
        } else {
            self.frame = .standard
        }
    }

    convenience init(api: LifeAPI, cacheStore: CacheStore, frameStore: LifeFrameStore, now: @escaping () -> Date = Date.init) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, frameStore: frameStore, now: now)
    }

    static func live() -> LifeViewModel {
        LifeViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared,
            frameStore: UserDefaultsLifeFrameStore()
        )
    }

    // MARK: Derived

    /// The server's day; until the first answer the screen has no squares to paint.
    var today: Date? { snapshot.flatMap { LifeCalendar.parse($0.today) } }
    var todayISO: String? { snapshot?.today }
    /// Until the reader moves it, the view stays on today.
    var cursor: Date? { movedCursor ?? today }
    var counter: LifeCounter? { today.map { LifeCalendar.counter(frame: frame, today: $0) } }

    /// The status of every week cell of the life canvas (row × 53 + column), computed once per pair
    /// (snapshot, frame): drawing and VoiceOver read the same array.
    var weekStatuses: [LifeStatus] {
        if let cache = weekStatusCache, cache.version == snapshotVersion, cache.frame == frame { return cache.statuses }
        var statuses: [LifeStatus] = []
        if let birth = LifeCalendar.parse(frame.birth), let todayISO {
            statuses = (0..<(frame.targetYears * LifeCalendar.weeksPerRow)).map {
                LifeCalendar.weekStatus(monday: LifeCalendar.weekMonday(birth: birth, index: $0), days: days, today: todayISO)
            }
        }
        weekStatusCache = (snapshotVersion, frame, statuses)
        return statuses
    }

    /// The Monday of a canvas cell; `nil` outside the grid.
    func weekMonday(row: Int, column: Int) -> Date? {
        guard row >= 0, row < frame.targetYears, column >= 0, column < LifeCalendar.weeksPerRow,
              let birth = LifeCalendar.parse(frame.birth) else { return nil }
        return LifeCalendar.weekMonday(birth: birth, index: row * LifeCalendar.weeksPerRow + column)
    }

    /// The cell holding the running week, where VoiceOver starts.
    var currentWeekIndex: Int? {
        guard let birth = LifeCalendar.parse(frame.birth), let today else { return nil }
        let seconds = LifeCalendar.startOfWeek(today).timeIntervalSince(LifeCalendar.startOfWeek(birth))
        let weeks = Int((seconds / (LifeCalendar.secondsPerDay * Double(LifeCalendar.daysInWeek))).rounded())
        return min(max(weeks, 0), frame.targetYears * LifeCalendar.weeksPerRow - 1)
    }

    /// What VoiceOver says for a canvas cell: the year of life, the ISO week, the state and the tally.
    func weekSpeech(index: Int) -> String? {
        guard let birth = LifeCalendar.parse(frame.birth), index >= 0, index < weekStatuses.count else { return nil }
        let monday = LifeCalendar.weekMonday(birth: birth, index: index)
        let tally = LifeCalendar.weekTally(monday: monday, days: days)
        return "Год \(index / LifeCalendar.weeksPerRow), неделя \(LifeCalendar.isoWeekCode(monday)), "
            + "\(weekStatuses[index].label), выиграно \(tally.won), проиграно \(tally.lost)"
    }

    func status(of date: Date) -> LifeStatus {
        let iso = LifeCalendar.iso(date)
        return LifeCalendar.dayStatus(days[iso], date: iso, today: todayISO ?? iso)
    }

    // MARK: Reading

    func load() async { await read(silent: false) }

    /// The screen came on: the cached snapshot goes on screen at once; with one shown it is read in place,
    /// and not at all while recent.
    func appear() async {
        showCached()
        if snapshot != nil, cache.isRecent(key: Self.cacheKey) { return }
        if snapshot == nil { await load() } else { await refresh() }
    }

    /// Puts the cached snapshot on screen while nothing is shown, without the network.
    func showCached() {
        guard snapshot == nil, let cached = cache.peek(LifeSnapshotDTO.self, key: Self.cacheKey) else { return }
        snapshot = cached.value
        state = .loaded
    }

    func refresh() async { await read(silent: true) }

    private func read(silent: Bool) async {
        generation += 1
        let mine = generation
        refreshError = nil
        if !silent { state = .loading }
        guard let api = apiProvider() else {
            fail(Self.notConfiguredMessage, silent: silent)
            return
        }
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                let day = try await api.fetchServerDay()
                guard let today = LifeCalendar.parse(day.date) else { throw APIClientError.invalidResponse }
                let range = LifeCalendar.historyRange(today: today)
                return LifeSnapshotDTO(today: day.date, days: try await api.fetchDays(from: range.from, to: range.to))
            }
            guard mine == generation else { return }
            switch outcome {
            case .fresh(let value):
                snapshot = value
                offlineAsOf = nil
            case .stale(let value, let updatedAt):
                snapshot = value
                offlineAsOf = updatedAt
            }
            state = .loaded
        } catch let error as APIClientError {
            guard mine == generation else { return }
            fail(Self.message(for: error), silent: silent)
        } catch {
            guard mine == generation else { return }
            fail(Self.loadFailedMessage, silent: silent)
        }
    }

    private func fail(_ message: String, silent: Bool) {
        if silent { refreshError = message } else { state = .failure(message) }
    }

    static func message(for error: APIClientError) -> String {
        switch error {
        case .invalidBaseURL: return "Неверный адрес сервера"
        case .unauthorized: return "Неверный ключ API (401)"
        case .timeout: return "Сервер не ответил вовремя"
        case .transport: return "Нет связи с сервером"
        case .unexpectedStatus(let status): return "Сервер ответил ошибкой \(status)"
        case .invalidResponse: return "Сервер вернул непонятный ответ"
        }
    }

    // MARK: Views

    func select(_ kind: LifeViewKind) { view = kind }

    func pickWeek(_ monday: Date) {
        movedCursor = monday
        view = .week
    }

    func pickMonth(_ first: Date) {
        movedCursor = first
        view = .month
    }

    func pickDay(_ date: Date) {
        movedCursor = date
        view = .day
    }

    /// Previous (-1) or next (+1) of what the current view looks at: a year, a month, a week or a day.
    func step(_ delta: Int) {
        guard let cursor else { return }
        switch view {
        case .life: break
        case .year:
            movedCursor = LifeCalendar.date(year: LifeCalendar.year(cursor) + delta, month: LifeCalendar.month(cursor))
        case .month:
            movedCursor = LifeCalendar.addMonths(LifeCalendar.date(year: LifeCalendar.year(cursor), month: LifeCalendar.month(cursor)), delta)
        case .week:
            movedCursor = LifeCalendar.addDays(cursor, delta * LifeCalendar.daysInWeek)
        case .day:
            movedCursor = LifeCalendar.addDays(cursor, delta)
        }
    }

    // MARK: Frame

    /// `false` leaves the frame as it was: the text is not a real `yyyy-MM-dd` date, or the date is ahead of today.
    @discardableResult
    func setBirth(_ iso: String) -> Bool {
        guard LifeCalendar.parse(iso) != nil, iso <= (todayISO ?? LifeCalendar.iso(now())) else { return false }
        frame.birth = iso
        frameStore.save(frame)
        return true
    }

    func setTargetYears(_ years: Int) {
        frame.targetYears = min(max(years, LifeFrame.yearsRange.lowerBound), LifeFrame.yearsRange.upperBound)
        frameStore.save(frame)
    }
}
