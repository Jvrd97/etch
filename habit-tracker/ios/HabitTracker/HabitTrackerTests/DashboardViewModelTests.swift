// [review:need-review] PHASE-03/304
// summary: dashboard state tests — the first read for the week through the read cache (fresh, offline with its moment, nothing cached), the period switch (own cache key per period, a late answer of a period left behind dropped, answers in launch order), refresh in place that keeps the screen, not-configured and server errors in Russian, and the server's day coming from the answer
import Combine
import XCTest
@testable import HabitTracker

final class MockDashboardSummaryAPI: DashboardSummaryAPI {
    var handler: (DashboardPeriod) async throws -> DashboardSummaryDTO = { _ in throw APIClientError.invalidResponse }
    private(set) var asked: [DashboardPeriod] = []

    func fetchDashboardSummary(period: DashboardPeriod) async throws -> DashboardSummaryDTO {
        asked.append(period)
        return try await handler(period)
    }
}

@MainActor
final class DashboardViewModelTests: XCTestCase {
    private let moment = Date(timeIntervalSince1970: 1_800_000_000)

    private func makeViewModel(_ api: MockDashboardSummaryAPI, store: CacheStore = InMemoryCacheStore()) -> DashboardViewModel {
        DashboardViewModel(api: api, cacheStore: store, now: { [moment] in moment })
    }

    private func answering(_ week: DashboardSummaryDTO, _ month: DashboardSummaryDTO) -> MockDashboardSummaryAPI {
        let api = MockDashboardSummaryAPI()
        api.handler = { $0 == .week ? week : month }
        return api
    }

    // MARK: First read

    func testLoadAsksTheWeekFirstAndShowsIt() async throws {
        let week = try DashboardFixtures.week()
        let api = answering(week, try DashboardFixtures.month())
        let viewModel = makeViewModel(api)
        XCTAssertEqual(viewModel.state, .idle)

        await viewModel.load()

        XCTAssertEqual(api.asked, [.week])
        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.period, .week)
        XCTAssertEqual(viewModel.summary, week)
        XCTAssertNil(viewModel.offlineAsOf)
    }

    func testTheDayComesFromTheAnswerAndNotFromTheClock() async throws {
        let api = answering(try DashboardFixtures.week(), try DashboardFixtures.month())
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertEqual(viewModel.summary?.today, "2026-10-31")
        // The test clock stands in 2027: the screen still knows only the server's day.
        XCTAssertEqual(viewModel.serverToday, "2026-10-31")
    }

    func testWithoutAServerAddressTheScreenSaysSo() async {
        let viewModel = DashboardViewModel(apiProvider: { nil }, cacheStore: InMemoryCacheStore(), now: { Date() })
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure("Укажите адрес сервера в More → Settings"))
    }

    func testAServerErrorIsShownInWords() async {
        let api = MockDashboardSummaryAPI()
        api.handler = { _ in throw APIClientError.unexpectedStatus(500) }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure("Сервер не смог собрать сводку. Попробуйте ещё раз через минуту."))
        XCTAssertNil(viewModel.summary)
    }

    func testAnUnexpectedErrorIsInRussianToo() async {
        struct Odd: Error {}
        let api = MockDashboardSummaryAPI()
        api.handler = { _ in throw Odd() }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure("Не удалось загрузить сводку"))
    }

    // MARK: Offline

    func testOfflineShowsTheLastAnswerWithItsMoment() async throws {
        let store = InMemoryCacheStore()
        let week = try DashboardFixtures.week()
        await makeViewModel(answering(week, week), store: store).load()

        let offline = MockDashboardSummaryAPI()
        offline.handler = { _ in throw APIClientError.transport(code: -1009) }
        let viewModel = makeViewModel(offline, store: store)
        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.summary, week)
        XCTAssertEqual(viewModel.offlineAsOf, moment)
    }

    func testOfflineWithNothingCachedIsAnErrorInWords() async {
        let api = MockDashboardSummaryAPI()
        api.handler = { _ in throw APIClientError.timeout }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure("Сервер не ответил вовремя"))
    }

    func testBackOnlineClearsTheOfflineMark() async throws {
        let store = InMemoryCacheStore()
        let week = try DashboardFixtures.week()
        await makeViewModel(answering(week, week), store: store).load()
        let flaky = MockDashboardSummaryAPI()
        flaky.handler = { _ in throw APIClientError.transport(code: -1009) }
        let viewModel = makeViewModel(flaky, store: store)
        await viewModel.load()
        XCTAssertNotNil(viewModel.offlineAsOf)

        flaky.handler = { _ in week }
        await viewModel.refresh()

        XCTAssertNil(viewModel.offlineAsOf)
    }

    // MARK: Period switch

    func testSwitchingThePeriodAsksTheOtherWindowAndShowsIt() async throws {
        let month = try DashboardFixtures.month()
        let api = answering(try DashboardFixtures.week(), month)
        let viewModel = makeViewModel(api)
        await viewModel.load()

        await viewModel.select(.month)

        XCTAssertEqual(api.asked, [.week, .month])
        XCTAssertEqual(viewModel.period, .month)
        XCTAssertEqual(viewModel.summary, month)
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testChoosingThePeriodAlreadyShownAsksNothing() async throws {
        let api = answering(try DashboardFixtures.week(), try DashboardFixtures.month())
        let viewModel = makeViewModel(api)
        await viewModel.load()
        await viewModel.select(.week)
        XCTAssertEqual(api.asked, [.week])
    }

    func testEachPeriodHasItsOwnCacheEntry() async throws {
        let store = InMemoryCacheStore()
        let week = try DashboardFixtures.week()
        let month = try DashboardFixtures.month()
        let viewModel = makeViewModel(answering(week, month), store: store)
        await viewModel.load()
        await viewModel.select(.month)

        XCTAssertEqual(store.load(DashboardSummaryDTO.self, forKey: DashboardViewModel.cacheKey(for: .week))?.value, week)
        XCTAssertEqual(store.load(DashboardSummaryDTO.self, forKey: DashboardViewModel.cacheKey(for: .month))?.value, month)
    }

    func testTheMonthOfflineDoesNotShowTheWeeksCachedAnswer() async throws {
        let store = InMemoryCacheStore()
        let week = try DashboardFixtures.week()
        await makeViewModel(answering(week, week), store: store).load()

        let offline = MockDashboardSummaryAPI()
        offline.handler = { _ in throw APIClientError.transport(code: -1009) }
        let viewModel = makeViewModel(offline, store: store)
        await viewModel.load()
        await viewModel.select(.month)

        XCTAssertEqual(viewModel.period, .month)
        XCTAssertNil(viewModel.summary)
        XCTAssertEqual(viewModel.state, .failure("Нет связи с сервером. Сохранённой сводки пока нет: подключитесь и повторите."))
    }

    func testALateAnswerOfAPeriodLeftBehindIsDropped() async throws {
        let week = try DashboardFixtures.week()
        let month = try DashboardFixtures.month()
        let api = MockDashboardSummaryAPI()
        var release: CheckedContinuation<Void, Never>?
        api.handler = { period in
            if period == .month {
                await withCheckedContinuation { release = $0 }
                return month
            }
            return week
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()

        let slow = Task { await viewModel.select(.month) }
        while release == nil { await Task.yield() }
        await viewModel.select(.week)
        release?.resume()
        await slow.value

        XCTAssertEqual(viewModel.period, .week)
        XCTAssertEqual(viewModel.summary, week)
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testAFailedSwitchLeavesThePeriodChosenAndTheErrorInPlaceOfOldNumbers() async throws {
        let api = answering(try DashboardFixtures.week(), try DashboardFixtures.month())
        let viewModel = makeViewModel(api)
        await viewModel.load()
        api.handler = { _ in throw APIClientError.unexpectedStatus(500) }

        await viewModel.select(.month)

        XCTAssertEqual(viewModel.period, .month)
        XCTAssertNil(viewModel.summary)
        XCTAssertEqual(viewModel.state, .failure("Сервер не смог собрать сводку. Попробуйте ещё раз через минуту."))
    }

    // MARK: Refresh in place

    func testRefreshKeepsTheScreenAndTakesTheNewAnswer() async throws {
        let first = try DashboardFixtures.week()
        let api = answering(first, first)
        let viewModel = makeViewModel(api)
        await viewModel.load()
        let second = try DashboardFixtures.decode(DashboardFixtures.weekJSON.replacingOccurrences(of: "\"value\": 78", with: "\"value\": 80"))
        api.handler = { _ in second }

        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.summary?.scores.health.value, 80)
    }

    func testAFailedRefreshKeepsTheNumbersAndSaysWhy() async throws {
        let first = try DashboardFixtures.week()
        let api = answering(first, first)
        let viewModel = makeViewModel(api)
        await viewModel.load()
        api.handler = { _ in throw APIClientError.unexpectedStatus(500) }

        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.summary, first)
        XCTAssertEqual(viewModel.refreshError, "Сервер не смог собрать сводку. Попробуйте ещё раз через минуту.")
    }

    // MARK: A refresh that overtakes a read

    func testARefreshThatFailsWhileTheFirstLoadHangsShowsTheErrorAndNotAnEndlessLoader() async {
        let api = MockDashboardSummaryAPI()
        var release: CheckedContinuation<Void, Never>?
        var calls = 0
        api.handler = { _ in
            calls += 1
            if calls == 1 {
                await withCheckedContinuation { release = $0 }
            }
            throw APIClientError.timeout
        }
        let viewModel = makeViewModel(api)

        let first = Task { await viewModel.load() }
        while release == nil { await Task.yield() }
        XCTAssertEqual(viewModel.state, .loading)
        await viewModel.refresh()
        release?.resume()
        await first.value

        XCTAssertEqual(viewModel.state, .failure("Сервер не ответил вовремя"))
    }

    func testAFailedRetryAfterAFailureReplacesTheReasonWithTheNewOne() async {
        let api = MockDashboardSummaryAPI()
        api.handler = { _ in throw APIClientError.unexpectedStatus(500) }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure("Сервер не смог собрать сводку. Попробуйте ещё раз через минуту."))

        api.handler = { _ in throw APIClientError.timeout }
        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .failure("Сервер не ответил вовремя"))
        XCTAssertNil(viewModel.refreshError)
    }

    func testAPullWhileTheFirstLoadRunsAndSucceedsLeavesTheNumbersOnScreen() async throws {
        let week = try DashboardFixtures.week()
        let api = MockDashboardSummaryAPI()
        var release: CheckedContinuation<Void, Never>?
        var calls = 0
        api.handler = { _ in
            calls += 1
            if calls == 1 { await withCheckedContinuation { release = $0 } }
            return week
        }
        let viewModel = makeViewModel(api)
        let first = Task { await viewModel.load() }
        while release == nil { await Task.yield() }

        await viewModel.refresh()
        release?.resume()
        await first.value

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.summary, week)
    }

    // MARK: Leaving the screen

    func testLeavingTheScreenMidReadDoesNotMarkTheNumbersAsNotUpdated() async throws {
        let store = InMemoryCacheStore()
        let week = try DashboardFixtures.week()
        await makeViewModel(answering(week, week), store: store).load()

        let api = MockDashboardSummaryAPI()
        var release: CheckedContinuation<Void, Never>?
        api.handler = { _ in
            await withCheckedContinuation { release = $0 }
            // What a cancelled request looks like to the client: a transport error.
            throw APIClientError.transport(code: NSURLErrorCancelled)
        }
        let viewModel = makeViewModel(api, store: store)
        let reading = Task { await viewModel.load() }
        while release == nil { await Task.yield() }

        reading.cancel()
        release?.resume()
        await reading.value

        XCTAssertNil(viewModel.offlineAsOf)
        XCTAssertNil(viewModel.summary)
        XCTAssertNotEqual(viewModel.state, .failure(DashboardFormat.offlineEmptyMessage))
    }

    func testComingBackAfterACancelledReadLoadsAgain() async throws {
        let week = try DashboardFixtures.week()
        let api = MockDashboardSummaryAPI()
        var release: CheckedContinuation<Void, Never>?
        var calls = 0
        api.handler = { _ in
            calls += 1
            if calls == 1 {
                await withCheckedContinuation { release = $0 }
                throw APIClientError.transport(code: NSURLErrorCancelled)
            }
            return week
        }
        let viewModel = makeViewModel(api)
        let reading = Task { await viewModel.load() }
        while release == nil { await Task.yield() }
        reading.cancel()
        release?.resume()
        await reading.value

        await viewModel.appear()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.summary, week)
    }

    // MARK: Switch is synchronous

    func testTheSegmentChangesAtOnceAndTheOldAnswerCannotLandUnderTheNewPeriod() async throws {
        let week = try DashboardFixtures.week()
        let api = MockDashboardSummaryAPI()
        var release: CheckedContinuation<Void, Never>?
        api.handler = { _ in
            await withCheckedContinuation { release = $0 }
            return week
        }
        let viewModel = makeViewModel(api)
        let reading = Task { await viewModel.load() }
        while release == nil { await Task.yield() }

        XCTAssertTrue(viewModel.switchTo(.month))
        XCTAssertEqual(viewModel.period, .month)
        XCTAssertFalse(viewModel.switchTo(.month))
        release?.resume()
        await reading.value

        XCTAssertNil(viewModel.summary)
    }

    func testComingBackReadsInPlaceInsteadOfShowingTheLoader() async throws {
        let first = try DashboardFixtures.week()
        let api = answering(first, first)
        let viewModel = makeViewModel(api)
        await viewModel.appear()
        XCTAssertEqual(viewModel.state, .loaded)

        var states: [DashboardViewModel.LoadState] = []
        let watch = viewModel.$state.sink { states.append($0) }
        await viewModel.appear()
        watch.cancel()

        XCTAssertFalse(states.contains(.loading))
        XCTAssertEqual(api.asked.count, 2)
    }
}
