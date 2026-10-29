// [review:need-review] PHASE-01/274
// [review:need-review] PHASE-01/270
// [review:need-review] PHASE-01/265
// summary: Life screen state tests — load through the read cache (fresh, offline with the cached moment, nothing to show, not configured, server error in words), a retry after failure, the cursor staying on the server's day until moved, stepping and picking per view, a late answer of a superseded read dropped, the frame kept on the device and a bad date refused
import XCTest
@testable import HabitTracker

private final class MockLifeAPI: LifeAPI {
    var dayHandler: () async throws -> LifeServerDayDTO = { LifeServerDayDTO(date: "2026-10-29") }
    var daysHandler: (String, String) async throws -> [LifeDayDTO] = { _, _ in [] }
    private(set) var ranges: [String] = []

    func fetchServerDay() async throws -> LifeServerDayDTO { try await dayHandler() }

    func fetchDays(from: String, to: String) async throws -> [LifeDayDTO] {
        ranges.append("\(from)...\(to)")
        return try await daysHandler(from, to)
    }
}

private final class MemoryFrameStore: LifeFrameStore {
    var frame: LifeFrame?
    func load() -> LifeFrame? { frame }
    func save(_ frame: LifeFrame) { self.frame = frame }
}

@MainActor
final class LifeViewModelTests: XCTestCase {
    private let moment = Date(timeIntervalSince1970: 1_800_000_000)

    private func row(_ date: String, _ verdict: String?) -> LifeDayDTO {
        LifeDayDTO(date: date, title: "t", verdict: verdict, verdictOrigin: "computed", done: 1, total: 2)
    }

    private func make(_ api: MockLifeAPI, store: CacheStore = InMemoryCacheStore(), frames: LifeFrameStore = MemoryFrameStore()) -> LifeViewModel {
        LifeViewModel(api: api, cacheStore: store, frameStore: frames, now: { self.moment })
    }

    func testLoadReadsTheServerDayThenTheHistoryWindowAgainstIt() async {
        let api = MockLifeAPI()
        api.daysHandler = { _, _ in [self.row("2026-10-28", "won"), self.row("2026-10-27", nil)] }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(api.ranges, ["2023-01-01...2026-12-31"])
        XCTAssertEqual(model.todayISO, "2026-10-29")
        XCTAssertEqual(model.status(of: LifeCalendar.parse("2026-10-28")!), .won)
        XCTAssertEqual(model.status(of: LifeCalendar.parse("2026-10-27")!), .open)
        XCTAssertEqual(model.status(of: LifeCalendar.parse("2026-10-26")!), .empty)
        XCTAssertEqual(model.status(of: LifeCalendar.parse("2026-10-30")!), .future)
        XCTAssertNil(model.offlineAsOf)
    }

    func testEmptyHistoryIsStillALoadedTimeline() async {
        let model = make(MockLifeAPI())
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertNotNil(model.counter)
        XCTAssertTrue(model.days.isEmpty)
    }

    func testCursorStaysOnTheServerDayUntilMoved() async {
        let model = make(MockLifeAPI())
        await model.load()
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2026-10-29")
        model.select(.week)
        model.step(-1)
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2026-10-22")
    }

    func testStepsMoveByTheUnitOfTheView() async {
        let model = make(MockLifeAPI())
        await model.load()
        model.select(.year); model.step(1)
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2027-10-01")
        model.select(.month); model.step(-1)
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2027-09-01")
        model.select(.day); model.step(1)
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2027-09-02")
        model.select(.life); model.step(1)
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2027-09-02")
    }

    func testPickingAWeekMonthOrDayChangesTheViewAndTheCursor() async {
        let model = make(MockLifeAPI())
        await model.load()
        model.pickWeek(LifeCalendar.parse("2026-10-19")!)
        XCTAssertEqual(model.view, .week)
        model.pickMonth(LifeCalendar.parse("2026-03-01")!)
        XCTAssertEqual(model.view, .month)
        model.pickDay(LifeCalendar.parse("2026-03-09")!)
        XCTAssertEqual(model.view, .day)
        XCTAssertEqual(LifeCalendar.iso(model.cursor!), "2026-03-09")
    }

    func testOfflineShowsTheLastSnapshotWithItsMoment() async {
        let store = InMemoryCacheStore()
        let api = MockLifeAPI()
        api.daysHandler = { _, _ in [self.row("2026-10-28", "lost")] }
        await make(api, store: store).load()

        let offline = MockLifeAPI()
        offline.dayHandler = { throw APIClientError.transport(code: -1009) }
        let model = make(offline, store: store)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertNotNil(model.offlineAsOf)
        XCTAssertEqual(model.days["2026-10-28"]?.verdict, "lost")
    }

    func testOfflineWithNothingCachedIsAnErrorInWords() async {
        let api = MockLifeAPI()
        api.dayHandler = { throw APIClientError.transport(code: -1009) }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .failure("Нет связи с сервером"))
    }

    func testServerErrorIsNotMaskedByTheCacheAndRetryRecovers() async {
        let api = MockLifeAPI()
        api.daysHandler = { _, _ in throw APIClientError.unexpectedStatus(500) }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .failure("Сервер ответил ошибкой 500"))
        api.daysHandler = { _, _ in [] }
        await model.load()
        XCTAssertEqual(model.state, .loaded)
    }

    func testNotConfiguredSaysWhere() async {
        let model = LifeViewModel(apiProvider: { nil }, cacheStore: InMemoryCacheStore(), frameStore: MemoryFrameStore())
        await model.load()
        XCTAssertEqual(model.state, .failure(LifeViewModel.notConfiguredMessage))
    }

    func testRefreshFailureKeepsWhatIsOnScreen() async {
        let api = MockLifeAPI()
        let model = make(api)
        await model.load()
        api.dayHandler = { throw APIClientError.unexpectedStatus(500) }
        await model.refresh()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.refreshError, "Сервер ответил ошибкой 500")
        XCTAssertNotNil(model.snapshot)
    }

    func testALateAnswerOfASupersededReadIsDropped() async {
        let api = MockLifeAPI()
        var calls = 0
        api.dayHandler = {
            calls += 1
            if calls == 1 {
                try await Task.sleep(nanoseconds: 200_000_000)
                return LifeServerDayDTO(date: "2026-01-01")
            }
            return LifeServerDayDTO(date: "2026-10-29")
        }
        let model = make(api)
        let slow = Task { await model.load() }
        try? await Task.sleep(nanoseconds: 30_000_000)
        await model.load()
        await slow.value
        XCTAssertEqual(model.todayISO, "2026-10-29")
    }

    func testFrameIsKeptOnTheDeviceAndABadDateIsRefused() async {
        let frames = MemoryFrameStore()
        let model = make(MockLifeAPI(), frames: frames)
        XCTAssertEqual(model.frame, .standard)
        XCTAssertTrue(model.setBirth("1990-03-04"))
        XCTAssertFalse(model.setBirth("1990-13-40"))
        model.setTargetYears(500)
        XCTAssertEqual(frames.frame, LifeFrame(birth: "1990-03-04", targetYears: 120))
        model.setTargetYears(0)
        XCTAssertEqual(model.frame.targetYears, 1)
        XCTAssertEqual(make(MockLifeAPI(), frames: frames).frame.birth, "1990-03-04")
    }

    func testAStoredBirthDateAheadOfTodayFallsBackToTheDefaults() {
        let frames = MemoryFrameStore()
        frames.frame = LifeFrame(birth: "2027-01-16", targetYears: 80)
        XCTAssertEqual(make(MockLifeAPI(), frames: frames).frame, .standard, "now is 2027-01-15")
        frames.frame = LifeFrame(birth: "2027-01-15", targetYears: 80)
        XCTAssertEqual(make(MockLifeAPI(), frames: frames).frame.birth, "2027-01-15")
    }

    func testACorruptStoredFrameFallsBackToTheDefaults() {
        let frames = MemoryFrameStore()
        frames.frame = LifeFrame(birth: "garbage", targetYears: 97)
        XCTAssertEqual(make(MockLifeAPI(), frames: frames).frame, .standard)
    }

    // MARK: #270

    func testABirthDateAheadOfTodayIsRefused() async {
        let model = make(MockLifeAPI())
        await model.load()
        XCTAssertFalse(model.setBirth("2026-10-30"))
        XCTAssertTrue(model.setBirth("2026-10-29"))
        XCTAssertEqual(model.frame.birth, "2026-10-29")
    }

    func testDaysFollowTheSnapshotAndWeekStatusesAreComputedOncePerPair() async {
        let api = MockLifeAPI()
        api.daysHandler = { _, _ in [self.row("2026-10-28", "won")] }
        let model = make(api, frames: MemoryFrameStore())
        await model.load()
        XCTAssertEqual(model.days["2026-10-28"]?.verdict, "won")
        let first = model.weekStatuses
        XCTAssertEqual(first.count, 97 * LifeCalendar.weeksPerRow)
        let index = model.currentWeekIndex!
        XCTAssertEqual(first[index], .won)

        api.daysHandler = { _, _ in [self.row("2026-10-28", "lost")] }
        await model.refresh()
        XCTAssertEqual(model.days["2026-10-28"]?.verdict, "lost")
        XCTAssertEqual(model.weekStatuses[index], .lost, "a new snapshot recounts")

        model.setTargetYears(50)
        XCTAssertEqual(model.weekStatuses.count, 50 * LifeCalendar.weeksPerRow, "a new frame recounts")
    }

    func testVoiceOverSpeaksTheWeekWithItsTally() async {
        let api = MockLifeAPI()
        api.daysHandler = { _, _ in [self.row("2026-10-27", "won"), self.row("2026-10-28", "lost"), self.row("2026-10-26", "won")] }
        let model = make(api)
        await model.load()
        let speech = model.weekSpeech(index: model.currentWeekIndex!)
        XCTAssertEqual(speech?.contains("2026-W44"), true)
        XCTAssertEqual(speech?.contains("выиграно 2, проиграно 1"), true)
        XCTAssertNil(model.weekSpeech(index: -1))
    }
}
