// [review:need-review] PHASE-01/265
// summary: Life screen state — the server's day plus the days of the last three years and this one through the read cache (one key; offline shows the last snapshot with its moment), five views (жизнь, год, месяц, неделя, день) over one cursor that stays on the server's day until the reader moves it, stepping per view, the birth date and frame kept on the device, a late answer of a superseded read dropped
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
    @Published private(set) var snapshot: LifeSnapshotDTO?
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
        let stored = frameStore.load()
        // A stored value that no longer parses must not break the counter.
        if let stored, LifeCalendar.parse(stored.birth) != nil, LifeFrame.yearsRange.contains(stored.targetYears) {
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
    var days: [String: LifeDayDTO] {
        Dictionary((snapshot?.days ?? []).map { ($0.date, $0) }, uniquingKeysWith: { _, last in last })
    }
    /// Until the reader moves it, the view stays on today.
    var cursor: Date? { movedCursor ?? today }
    var counter: LifeCounter? { today.map { LifeCalendar.counter(frame: frame, today: $0) } }

    func status(of date: Date) -> LifeStatus {
        let iso = LifeCalendar.iso(date)
        return LifeCalendar.dayStatus(days[iso], date: iso, today: todayISO ?? iso)
    }

    // MARK: Reading

    func load() async { await read(silent: false) }

    func appear() async {
        if snapshot == nil { await load() } else { await refresh() }
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

    /// `false` leaves the frame as it was: the text is not a real `yyyy-MM-dd` date.
    @discardableResult
    func setBirth(_ iso: String) -> Bool {
        guard LifeCalendar.parse(iso) != nil else { return false }
        frame.birth = iso
        frameStore.save(frame)
        return true
    }

    func setTargetYears(_ years: Int) {
        frame.targetYears = min(max(years, LifeFrame.yearsRange.lowerBound), LifeFrame.yearsRange.upperBound)
        frameStore.save(frame)
    }
}
