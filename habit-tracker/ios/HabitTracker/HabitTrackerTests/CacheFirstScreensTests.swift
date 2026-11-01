// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — a return to a loaded table keeps the older pages; a Day step names the day it opens, counts from the day asked for and, when it fails, names that day and points the screen back; past midnight (and past the end of the running week) an appearance reads again however recent the snapshot
// summary: every screen with a cached snapshot opens from it while the server never answers and never passes through the loader; three appearances inside `minAge` cost at most one request per endpoint; the day-bound snapshots of another day are not shown as today's; an older answer does not replace a newer grid; the streak read does not wait for the table; snapshots of another server are not shown; a loaded day steps without the loader
import Combine
import XCTest
@testable import HabitTracker

/// Answers the app's requests by path (after `/api/v1`), or never answers at all. One test at a time owns it,
/// by its own host: a request a finished test leaves behind is neither answered nor counted.
final class ScriptedURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var host = ""
    private static var answers: [String: Data]?
    private static var sentPaths: [String] = []

    /// Hands the protocol to the test that talks to `host`; nothing is answered until `reset(answers:)`.
    static func begin(host: String) {
        lock.withLock {
            self.host = host
            answers = nil
            sentPaths = []
        }
    }

    /// `nil` answers nothing: every request hangs. A path missing from the dictionary answers 404.
    static func reset(answers: [String: Data]?) {
        lock.withLock {
            self.answers = answers
            sentPaths = []
        }
    }

    static var paths: [String] { lock.withLock { sentPaths } }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url else { return }
        let path = url.path.replacingOccurrences(of: "/api/v1", with: "")
        let script = Self.lock.withLock { () -> [String: Data]? in
            guard url.host == Self.host else { return nil }
            Self.sentPaths.append(path)
            return Self.answers
        }
        guard let script else { return }
        let body = script[path]
        let status = body == nil ? 404 : 200
        guard let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: nil) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body ?? Data())
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

/// A clock a test moves by hand.
final class TestClock {
    var now: Date
    init(_ now: Date) { self.now = now }
}

@MainActor
final class CacheFirstScreensTests: XCTestCase {
    /// Wednesday 2026-10-21 12:00 UTC: inside ISO week 2026-W43.
    private static let wednesday = Date(timeIntervalSince1970: 1_792_584_000)
    private static let today = "2026-10-21"
    private static let yesterday = "2026-10-20"
    private static let utc = TimeZone(identifier: "UTC")!

    /// Long enough that no request of a finished test times out while the suite runs.
    private static let requestTimeout: TimeInterval = 3600

    private var client: APIClient!
    private var clock: TestClock!
    private var store: InMemoryCacheStore!

    /// The session is never invalidated: a screen whose read still hangs when the test ends may send another
    /// request later, and a task on an invalidated session stops the process.
    override func setUp() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ScriptedURLProtocol.self]
        let host = "run-\(UUID().uuidString.lowercased()).test"
        ScriptedURLProtocol.begin(host: host)
        client = APIClient(
            baseURL: URL(string: "http://\(host)")!, apiKeyProvider: { nil },
            session: URLSession(configuration: configuration), timeout: Self.requestTimeout
        )
        clock = TestClock(Self.wednesday)
        store = InMemoryCacheStore()
    }

    private var now: () -> Date {
        let clock = clock!
        return { clock.now }
    }

    private var utcCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = Self.utc
        return calendar
    }

    private func category(id: Int, avoid: Bool = false) -> CategoryDTO {
        CategoryDTO(
            id: id, name: "Category \(id)", icon: nil, color: nil, displayMode: "form",
            streakMode: avoid ? CategoryDTO.avoidStreakMode : CategoryDTO.buildStreakMode, isActive: true, fields: []
        )
    }

    private func quickMark(day: String) -> QuickMarkDTO {
        QuickMarkDTO(
            id: 1, label: "Вода", categoryId: 1, fieldId: 11, kind: QuickMarkDTO.kindIncrement,
            step: 1, unitLabel: nil, icon: nil, color: nil, hotkey: nil, order: 1,
            showInAgent: true, isActive: true, entryDate: day, todayTotal: 2,
            done: false, planned: false, planItemId: nil
        )
    }

    private func json<T: Encodable>(_ value: T) throws -> Data {
        try APIJSONCoding.makeEncoder().encode(value)
    }

    // MARK: Screens

    private func todayScreen() -> TodayViewModel {
        TodayViewModel(apiProvider: { [client] in client }, cacheStore: store, timeZone: Self.utc, now: now)
    }

    private func dayScreen() -> DayViewModel {
        DayViewModel(apiProvider: { [client] in client }, timeZoneProvider: { Self.utc }, cacheStore: store, now: now)
    }

    private func weekScreen() -> WeekViewModel {
        WeekViewModel(
            apiProvider: { [client] in client }, narrativeAPIProvider: { [client] in client }, cacheStore: store, now: now
        )
    }

    private func tableScreen() -> TableViewModel {
        TableViewModel(apiProvider: { [client] in client }, cacheStore: store, timeZone: Self.utc, now: now)
    }

    private func goalsScreen(store: CacheStore? = nil) -> GoalsViewModel {
        GoalsViewModel(apiProvider: { [client] in client }, cacheStore: store ?? self.store, now: now)
    }

    private func healthScreen() -> HealthMetricsViewModel {
        HealthMetricsViewModel(
            apiProvider: { [client] in client }, stateAPIProvider: { [client] in client },
            cacheStore: store, now: now, calendar: utcCalendar
        )
    }

    private func dashboardScreen() -> DashboardViewModel {
        DashboardViewModel(apiProvider: { [client] in client }, cacheStore: store, now: now)
    }

    private func rolesScreen() -> RolesViewModel {
        RolesViewModel(apiProvider: { [client] in client }, cacheStore: store, now: now)
    }

    private func supplementsScreen() -> SupplementsViewModel {
        SupplementsViewModel(apiProvider: { [client] in client }, cacheStore: store, now: now)
    }

    private func lifeScreen() throws -> LifeViewModel {
        let suite = "CacheFirstScreensTests.life"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defaults.removePersistentDomain(forName: suite)
        return LifeViewModel(
            apiProvider: { [client] in client }, cacheStore: store, frameStore: UserDefaultsLifeFrameStore(defaults: defaults), now: now
        )
    }

    private func quickMarksScreen() -> QuickMarksViewModel {
        QuickMarksViewModel(apiProvider: { [client] in client }, cacheStore: store, timeZone: Self.utc, now: now)
    }

    // MARK: 1, 2 — the first frame does not wait for the network and never shows the loader

    /// The server never answers. With a snapshot in the cache the screen must show it, never pass through
    /// the loader on the way, and still send its read in the background.
    private func assertOpensFromCache<S: Equatable>(
        _ states: Published<S>.Publisher,
        loading: S,
        appear: @escaping @MainActor () async -> Void,
        showsSnapshot: @escaping @MainActor () -> Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        var seen: [S] = []
        let watch = states.sink { seen.append($0) }
        let running = Task { await appear() }
        await waitUntil(showsSnapshot, file: file, line: line)
        await waitUntil({ !ScriptedURLProtocol.paths.isEmpty }, file: file, line: line)
        XCTAssertFalse(seen.contains(loading), "the loader showed over a cached snapshot: \(seen)", file: file, line: line)
        running.cancel()
        watch.cancel()
    }

    func testTodayOpensFromCache() async {
        store.save(
            TodaySnapshot(categories: [category(id: 1)], entries: [], streaks: [:], day: Self.today),
            forKey: TodayViewModel.cacheKey, updatedAt: clock.now
        )
        let screen = todayScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.categories.map(\.id) == [1]
        }
    }

    func testDayOpensFromCache() async throws {
        store.save(try DayFixtures.day(date: Self.today), forKey: "day.today", updatedAt: clock.now)
        let screen = dayScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.shownDate == Self.today
        }
    }

    func testWeekOpensFromCache() async throws {
        store.save(try WeekFixtures.runningWeek(iso: "2026-W43"), forKey: WeekViewModel.cacheKey(for: nil), updatedAt: clock.now)
        let screen = weekScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.review?.window.isoCode == "2026-W43"
        }
    }

    func testTableOpensFromCache() async {
        store.save(
            TableResponseDTO(categories: [], days: [TableDayDTO(date: Self.today, cells: [])]),
            forKey: TableViewModel.cacheKey, updatedAt: clock.now
        )
        let screen = tableScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded
        }
    }

    func testGoalsOpenFromCache() async {
        store.save(GoalsFixtures.board(), forKey: GoalsViewModel.cacheKey, updatedAt: clock.now)
        let screen = goalsScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.board == GoalsFixtures.board()
        }
    }

    func testHealthOpensFromCache() async {
        let catalogue = HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [(Self.today, 100)])])
        store.save(catalogue, forKey: HealthMetricsViewModel.metricsKey, updatedAt: clock.now)
        let screen = healthScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.metrics == catalogue.metrics
        }
    }

    func testDashboardOpensFromCache() async throws {
        let week = try DashboardFixtures.week()
        store.save(week, forKey: DashboardViewModel.cacheKey(for: .week), updatedAt: clock.now)
        let screen = dashboardScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.summary == week
        }
    }

    func testDashboardPeriodSwitchOpensFromCache() async throws {
        let month = try DashboardFixtures.month()
        store.save(try DashboardFixtures.week(), forKey: DashboardViewModel.cacheKey(for: .week), updatedAt: clock.now)
        store.save(month, forKey: DashboardViewModel.cacheKey(for: .month), updatedAt: clock.now)
        let screen = dashboardScreen()
        screen.showCached()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.select(.month) }) {
            screen.state == .loaded && screen.summary == month
        }
    }

    func testRolesOpenFromCache() async throws {
        let snapshot = RolesViewModel.Snapshot(day: try RolesFixtures.day(), roles: try RolesFixtures.roles())
        store.save(snapshot, forKey: RolesViewModel.snapshotKey, updatedAt: clock.now)
        let screen = rolesScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.day == snapshot.day
        }
    }

    func testSupplementsOpenFromCache() async {
        let item = SupplementDTO(id: 1, name: "D3", dose: 1, unit: "капс", intakeTime: nil, isActive: true, takenToday: false)
        store.save(
            SupplementsViewModel.Snapshot(day: Self.today, items: [item], rule: nil),
            forKey: SupplementsViewModel.cacheKey, updatedAt: clock.now
        )
        let screen = supplementsScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.rows.map(\.id) == [1]
        }
    }

    func testLifeOpensFromCache() async throws {
        let snapshot = LifeSnapshotDTO(today: Self.today, days: [])
        store.save(snapshot, forKey: LifeViewModel.cacheKey, updatedAt: clock.now)
        let screen = try lifeScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.todayISO == Self.today
        }
    }

    func testQuickMarksOpenFromCache() async {
        store.save([quickMark(day: Self.today)], forKey: QuickMarksViewModel.cacheKey, updatedAt: clock.now)
        let screen = quickMarksScreen()
        await assertOpensFromCache(screen.$state, loading: .loading, appear: { await screen.appear() }) {
            screen.state == .loaded && screen.marks.map(\.id) == [1]
        }
    }

    // MARK: 3 — appearances inside minAge cost at most one request per endpoint

    /// Three appearances in a row, then one past `minAge`: the three cost at most one request per endpoint,
    /// the fourth reads again.
    private func assertOneReadPerWindow(
        answers: [String: Data],
        appear: @escaping @MainActor () async -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        ScriptedURLProtocol.reset(answers: answers)
        for _ in 0..<3 { await appear() }
        let sent = ScriptedURLProtocol.paths
        let perPath = Dictionary(grouping: sent, by: { $0 }).mapValues(\.count)
        XCTAssertFalse(sent.isEmpty, "nothing was read", file: file, line: line)
        XCTAssertTrue(perPath.values.allSatisfy { $0 == 1 }, "repeated reads inside minAge: \(perPath)", file: file, line: line)

        clock.now += ReadThroughCache.minAge
        await appear()
        XCTAssertGreaterThan(ScriptedURLProtocol.paths.count, sent.count, "past minAge the screen reads again", file: file, line: line)
    }

    func testTodayReadsOncePerWindow() async {
        let screen = todayScreen()
        await assertOneReadPerWindow(answers: ["/categories": Data("[]".utf8), "/entries": Data("[]".utf8)]) {
            await screen.appear()
        }
    }

    func testDayReadsOncePerWindow() async throws {
        let screen = dayScreen()
        await assertOneReadPerWindow(answers: ["/day": try json(DayFixtures.day(date: Self.today))]) { await screen.appear() }
    }

    func testWeekReadsOncePerWindow() async throws {
        let screen = weekScreen()
        let running = try json(WeekFixtures.runningWeek(iso: "2026-W43"))
        await assertOneReadPerWindow(answers: ["/week-review": running]) { await screen.appear() }
    }

    func testTableReadsOncePerWindow() async {
        let screen = tableScreen()
        await assertOneReadPerWindow(answers: ["/table": Data(#"{"categories":[],"days":[]}"#.utf8)]) { await screen.appear() }
    }

    func testGoalsReadOncePerWindow() async throws {
        let screen = goalsScreen()
        await assertOneReadPerWindow(answers: ["/goals": try json(GoalsFixtures.board())]) { await screen.appear() }
    }

    func testHealthReadsOncePerWindow() async {
        let screen = healthScreen()
        await assertOneReadPerWindow(answers: ["/health/metrics": Data(#"{"metrics":[]}"#.utf8)]) { await screen.appear() }
    }

    func testDashboardReadsOncePerWindow() async {
        let screen = dashboardScreen()
        await assertOneReadPerWindow(answers: ["/dashboard/summary": Data(DashboardFixtures.weekJSON.utf8)]) {
            await screen.appear()
        }
    }

    func testRolesReadOncePerWindow() async {
        let screen = rolesScreen()
        let answers = [
            "/roles/day": Data(RolesFixtures.dayJSON.utf8),
            "/roles": Data(RolesFixtures.rolesJSON.utf8),
            "/roles/summary": Data(RolesFixtures.summaryJSON.utf8),
        ]
        await assertOneReadPerWindow(answers: answers) { await screen.appear() }
    }

    func testSupplementsReadOncePerWindow() async {
        let screen = supplementsScreen()
        await assertOneReadPerWindow(answers: ["/supplements": Data("[]".utf8)]) { await screen.appear() }
    }

    func testLifeReadsOncePerWindow() async throws {
        let screen = try lifeScreen()
        let answers = ["/day-mode": Data(#"{"date":"2026-10-21"}"#.utf8), "/days": Data("[]".utf8)]
        await assertOneReadPerWindow(answers: answers) { await screen.appear() }
    }

    func testQuickMarksReadOncePerWindow() async {
        let screen = quickMarksScreen()
        await assertOneReadPerWindow(answers: ["/quick-marks": Data("[]".utf8)]) { await screen.appear() }
    }

    func testAWriteSentInsideTheWindowMakesTheNextAppearanceRead() async throws {
        let screen = goalsScreen()
        ScriptedURLProtocol.reset(answers: ["/goals": try json(GoalsFixtures.board())])
        await screen.appear()

        ServerWrites.note()
        await screen.appear()

        XCTAssertEqual(ScriptedURLProtocol.paths, ["/goals", "/goals"])
    }

    // MARK: 4 — the streak read does not wait for the table

    private func avoidAPI() -> MockTodayAPI {
        let api = MockTodayAPI()
        api.categoriesResult = .success([category(id: 1, avoid: true)])
        api.avoidStreaksResult = .success([])
        return api
    }

    func testStreaksAreAskedBeforeTheTableAnswers() async {
        let api = avoidAPI()
        var askedBeforeTable = false
        api.duringFetchTable = {
            await waitUntil { api.avoidStreakFetches > 0 }
            askedBeforeTable = api.avoidStreakFetches > 0
        }
        let screen = TodayViewModel(api: api, timeZone: Self.utc, now: now, usageReadLimit: .seconds(10))

        await screen.load()

        XCTAssertTrue(askedBeforeTable, "the streak read waited for the table")
        XCTAssertEqual(api.avoidStreakFetches, 1)
    }

    func testKnownAvoidCategoriesSendTheStreakReadWithTheFirstWave() async {
        store.save(
            TodaySnapshot(categories: [category(id: 1, avoid: true)], entries: [], streaks: [:], day: Self.today),
            forKey: TodayViewModel.cacheKey, updatedAt: clock.now
        )
        let api = avoidAPI()
        var askedBeforeCategories = false
        api.duringFetchCategories = {
            await waitUntil { api.avoidStreakFetches > 0 }
            askedBeforeCategories = api.avoidStreakFetches > 0
        }
        let screen = TodayViewModel(api: api, cacheStore: store, timeZone: Self.utc, now: now)

        await screen.appear()

        XCTAssertTrue(askedBeforeCategories, "the streak read waited for the categories")
        XCTAssertEqual(api.avoidStreakFetches, 1)
    }

    // MARK: 5 — an older answer that comes after a newer one replaces neither the screen nor the snapshot

    func testAnOlderTableAnswerDoesNotReplaceANewerGrid() async {
        let api = GatedTableAPI()
        let screen = TableViewModel(api: api, cacheStore: store, timeZone: Self.utc, now: now)
        let older = Task { await screen.load() }
        await waitUntil { api.isHolding }

        api.next = TableResponseDTO(categories: [], days: [TableDayDTO(date: Self.today, cells: [])])
        await screen.load()
        api.release(TableResponseDTO(categories: [], days: [TableDayDTO(date: Self.yesterday, cells: [])]))
        await older.value

        XCTAssertEqual(screen.grid.rows.map(\.date), [Self.today])
        XCTAssertEqual(store.load(TableResponseDTO.self, forKey: TableViewModel.cacheKey)?.value.days.map(\.date), [Self.today])
    }

    // MARK: 6 — a snapshot of yesterday is not shown as today's

    func testTodayDoesNotOpenOnYesterdaysSnapshot() async {
        store.save(
            TodaySnapshot(categories: [category(id: 1)], entries: [], streaks: [:], day: Self.yesterday),
            forKey: TodayViewModel.cacheKey, updatedAt: clock.now
        )
        let screen = todayScreen()
        let running = Task { await screen.appear() }
        await waitUntil { !ScriptedURLProtocol.paths.isEmpty }

        XCTAssertEqual(screen.state, .loading)
        running.cancel()
    }

    func testOfflineTodayDoesNotShowYesterdaysRecordsAsToday() async {
        let entry = EntryDTO(id: 5, categoryId: 1, entryDate: Self.yesterday, values: [])
        store.save(
            TodaySnapshot(categories: [category(id: 1)], entries: [entry], streaks: [:], day: Self.yesterday),
            forKey: TodayViewModel.cacheKey, updatedAt: clock.now
        )
        let api = MockTodayAPI()
        api.categoriesResult = .failure(APIClientError.timeout)
        api.entriesResult = .failure(APIClientError.timeout)
        let screen = TodayViewModel(api: api, cacheStore: store, timeZone: Self.utc, now: now)

        await screen.load()

        XCTAssertEqual(screen.state, .loaded)
        XCTAssertEqual(screen.categories.map(\.id), [1])
        XCTAssertEqual(screen.todayEntries, [], "yesterday's records shown as today's")
    }

    func testDayDoesNotOpenOnYesterdaysToday() async throws {
        store.save(try DayFixtures.day(date: Self.yesterday), forKey: "day.today", updatedAt: clock.now)
        let screen = dayScreen()
        let running = Task { await screen.appear() }
        await waitUntil { !ScriptedURLProtocol.paths.isEmpty }

        XCTAssertEqual(screen.state, .loading)
        XCTAssertNil(screen.detail)
        running.cancel()
    }

    func testWeekDoesNotOpenOnAnEndedWeekAsTheCurrentOne() async throws {
        store.save(try WeekFixtures.runningWeek(iso: "2026-W42"), forKey: WeekViewModel.cacheKey(for: nil), updatedAt: clock.now)
        let screen = weekScreen()
        let running = Task { await screen.appear() }
        await waitUntil { !ScriptedURLProtocol.paths.isEmpty }

        XCTAssertEqual(screen.state, .loading)
        XCTAssertNil(screen.review)
        running.cancel()
    }

    func testQuickMarksDoNotOpenOnYesterdaysTotals() async {
        store.save([quickMark(day: Self.yesterday)], forKey: QuickMarksViewModel.cacheKey, updatedAt: clock.now)
        let screen = quickMarksScreen()

        screen.showCached()

        XCTAssertEqual(screen.state, .idle)
        XCTAssertEqual(screen.marks, [])
    }

    // MARK: 7 — snapshots of another server are not shown

    func testAScreenDoesNotOpenOnTheSnapshotOfAnotherServer() {
        var server = "http://old:8000"
        let scoped = ServerScopedCacheStore(base: store, server: { server })
        scoped.save(GoalsFixtures.board(), forKey: GoalsViewModel.cacheKey, updatedAt: clock.now)

        server = "http://new:8000"
        let screen = goalsScreen(store: scoped)
        screen.showCached()

        XCTAssertEqual(screen.state, .idle)
        XCTAssertNil(screen.board)
    }

    // MARK: Table keeps the older pages when the screen comes back

    func testComingBackToTheTableKeepsThePagesReadWithLoadOlder() async {
        let api = RangeTableAPI()
        let screen = TableViewModel(api: api, cacheStore: store, timeZone: Self.utc, now: now)
        await screen.appear()
        await screen.loadOlder()
        XCTAssertEqual(screen.grid.rows.map(\.date), [Self.today, "2026-09-21"])

        clock.now += ReadThroughCache.minAge
        await screen.appear()

        XCTAssertEqual(screen.grid.rows.map(\.date), [Self.today, "2026-09-21"], "the older page was wiped")
        await screen.loadOlder()
        XCTAssertEqual(api.ranges.last?.to, "2026-08-22", "«load older» starts again from the first page")
    }

    func testPullToRefreshStillReplacesTheTable() async {
        let api = RangeTableAPI()
        let screen = TableViewModel(api: api, cacheStore: store, timeZone: Self.utc, now: now)
        await screen.appear()
        await screen.loadOlder()

        await screen.load()

        XCTAssertEqual(screen.grid.rows.map(\.date), [Self.today])
    }

    // MARK: 4 — past midnight a recent snapshot of yesterday is read again

    /// 23:59:50 UTC on the 21st.
    private static let beforeMidnight = wednesday.addingTimeInterval(12 * 3600 - 10)

    func testTodayReadsAgainPastMidnightHoweverRecentTheSnapshot() async {
        clock.now = Self.beforeMidnight
        ScriptedURLProtocol.reset(answers: ["/categories": Data("[]".utf8), "/entries": Data("[]".utf8)])
        let screen = todayScreen()
        await screen.appear()
        let before = ScriptedURLProtocol.paths.filter { $0 == "/entries" }.count

        clock.now += 15
        await screen.appear()

        XCTAssertEqual(ScriptedURLProtocol.paths.filter { $0 == "/entries" }.count, before + 1)
    }

    func testDayReadsAgainPastMidnightHoweverRecentTheCopy() async throws {
        clock.now = Self.beforeMidnight
        ScriptedURLProtocol.reset(answers: ["/day": try json(DayFixtures.day(date: Self.today))])
        let screen = dayScreen()
        await screen.appear()
        await screen.appear()
        XCTAssertEqual(ScriptedURLProtocol.paths, ["/day"], "inside the window and the same day: no second read")

        clock.now += 15
        await screen.appear()

        XCTAssertEqual(ScriptedURLProtocol.paths, ["/day", "/day"])
    }

    func testWeekReadsAgainOnceTheRunningWeekHasEnded() async throws {
        // Monday 2026-10-26 03:59:50 in Berlin (UTC+1): the server's day is still Sunday until 04:00.
        clock.now = Date(timeIntervalSince1970: 1_792_918_800 + 18 * 3600 - 10)
        ScriptedURLProtocol.reset(answers: ["/week-review": try json(WeekFixtures.runningWeek(iso: "2026-W43"))])
        let screen = weekScreen()
        await screen.appear()
        XCTAssertTrue(screen.isShowingRunningWeek)
        await screen.appear()
        XCTAssertEqual(ScriptedURLProtocol.paths, ["/week-review"], "inside the window and the week runs: no second read")

        clock.now += 15
        await screen.appear()

        XCTAssertEqual(ScriptedURLProtocol.paths, ["/week-review", "/week-review"])
    }

    // MARK: Day steps without the loader

    func testALoadedDayStepsWithoutTheLoader() async {
        ScriptedURLProtocol.reset(answers: ["/day": Data(DayFixtures.dayJSON.utf8)])
        let screen = dayScreen()
        await screen.appear()
        XCTAssertEqual(screen.state, .loaded)

        ScriptedURLProtocol.reset(answers: nil)
        var seen: [DayViewModel.LoadState] = []
        let watch = screen.$state.sink { seen.append($0) }
        let stepping = Task { await screen.showNextDay() }
        await waitUntil { !ScriptedURLProtocol.paths.isEmpty }

        XCTAssertFalse(seen.contains(.loading), "the step replaced the day with the loader: \(seen)")
        XCTAssertEqual(screen.state, .loaded)
        stepping.cancel()
        watch.cancel()
    }

    func testAStepNamesTheDayItOpensAndTheNextStepCountsFromIt() async {
        ScriptedURLProtocol.reset(answers: ["/day": Data(DayFixtures.dayJSON.utf8)])
        let screen = dayScreen()
        await screen.appear()
        ScriptedURLProtocol.reset(answers: nil)

        let first = Task { await screen.showPreviousDay() }
        await waitUntil { ScriptedURLProtocol.paths.contains("/day/2026-10-24") }
        XCTAssertEqual(screen.steppingTo, "2026-10-24")
        XCTAssertEqual(screen.shownDate, DayFixtures.date, "the shown day stays until the next one comes")

        let second = Task { await screen.showPreviousDay() }
        await waitUntil { ScriptedURLProtocol.paths.contains("/day/2026-10-23") }
        XCTAssertEqual(screen.steppingTo, "2026-10-23", "two taps are two days")
        first.cancel()
        second.cancel()
    }

    func testAStepThatFailsNamesTheDayAndPointsTheScreenBack() async {
        ScriptedURLProtocol.reset(answers: ["/day": Data(DayFixtures.dayJSON.utf8)])
        let screen = dayScreen()
        await screen.appear()

        await screen.showPreviousDay()

        XCTAssertEqual(screen.shownDate, DayFixtures.date)
        XCTAssertNil(screen.steppingTo)
        XCTAssertEqual(
            screen.refreshError?.hasPrefix("\(DayViewModel.openFailedPrefix) \(DayFormat.title(of: "2026-10-24"))"), true,
            "the line does not name the day that did not open: \(screen.refreshError ?? "nil")"
        )
        XCTAssertNil(screen.requestedDate, "the screen still asks for the day it does not show")
        await screen.rereadInPlace(reportingFailure: true)
        XCTAssertEqual(ScriptedURLProtocol.paths.last, "/day", "pull to refresh jumped to the day that failed")
    }
}

/// Answers each table read with the last day of the range asked for.
private final class RangeTableAPI: TableAPI {
    private(set) var ranges: [(from: String, to: String)] = []

    func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO {
        ranges.append((dateFrom, dateTo))
        return TableResponseDTO(categories: [], days: [TableDayDTO(date: dateTo, cells: [])])
    }

    func fetchEntries(categoryId: Int, date: String) async throws -> [EntryDTO] { [] }
}

/// A table read whose first answer waits for the test; later reads answer `next` at once.
@MainActor
private final class GatedTableAPI: TableAPI {
    var next = TableResponseDTO(categories: [], days: [])
    private var held: CheckedContinuation<TableResponseDTO, Never>?
    private var didHold = false
    var isHolding: Bool { held != nil }

    nonisolated func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO {
        await answer()
    }

    nonisolated func fetchEntries(categoryId: Int, date: String) async throws -> [EntryDTO] { [] }

    private func answer() async -> TableResponseDTO {
        if didHold { return next }
        didHold = true
        return await withCheckedContinuation { held = $0 }
    }

    func release(_ answer: TableResponseDTO) {
        held?.resume(returning: answer)
        held = nil
    }
}
