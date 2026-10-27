// [review:need-review] PHASE-03/229
// summary: Week screen state tests — load of the running week through the read cache (fresh, offline with "обновлено", nothing to show), not-configured and server errors in words, stepping between weeks with a late answer dropped, in-place refresh that keeps the screen, and the narrative on request (statuses, no network, empty week, a week change drops it)
import XCTest
@testable import HabitTracker

final class MockWeekAPI: WeekAPI {
    var fetchHandler: (String?) async throws -> WeekReviewDTO = { _ in throw APIClientError.invalidResponse }
    var narrativeHandler: (String) async throws -> WeekNarrativeDTO = { _ in throw APIClientError.invalidResponse }
    private(set) var fetched: [String?] = []
    private(set) var narrated: [String] = []

    func fetchWeekReview(iso: String?) async throws -> WeekReviewDTO {
        fetched.append(iso)
        return try await fetchHandler(iso)
    }

    func writeWeekNarrative(iso: String) async throws -> WeekNarrativeDTO {
        narrated.append(iso)
        return try await narrativeHandler(iso)
    }
}

@MainActor
final class WeekViewModelTests: XCTestCase {
    private let moment = Date(timeIntervalSince1970: 1_800_000_000)

    private func makeViewModel(
        _ api: MockWeekAPI, store: CacheStore = InMemoryCacheStore()
    ) -> WeekViewModel {
        WeekViewModel(api: api, cacheStore: store, now: { self.moment })
    }

    private func narrative(_ text: String = "Неделя прошла ровно.") -> WeekNarrativeDTO {
        WeekNarrativeDTO(isoCode: "2026-W35", text: text, model: "m")
    }

    // MARK: Loading

    func testLoadAsksForTheRunningWeekAndShowsIt() async throws {
        let api = MockWeekAPI()
        let week = try WeekFixtures.review()
        api.fetchHandler = { _ in week }
        let viewModel = makeViewModel(api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.review, week)
        XCTAssertNil(viewModel.offlineAsOf)
        XCTAssertEqual(api.fetched.count, 1)
        XCTAssertNil(api.fetched[0])
    }

    func testWithoutAServerAddressTheScreenSaysSo() async {
        let viewModel = WeekViewModel(
            apiProvider: { nil }, narrativeAPIProvider: { nil }, cacheStore: InMemoryCacheStore()
        )

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .failure(WeekFormat.notConfiguredMessage))
        XCTAssertNil(viewModel.review)
    }

    func testAServerErrorIsShownInWordsAndNotHiddenByOldData() async throws {
        let api = MockWeekAPI()
        let store = InMemoryCacheStore()
        store.save(try WeekFixtures.review(), forKey: WeekViewModel.cacheKey(for: nil), updatedAt: moment)
        api.fetchHandler = { _ in throw APIClientError.unexpectedStatus(500) }
        let viewModel = makeViewModel(api, store: store)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .failure("Сервер ответил ошибкой 500"))
    }

    func testOfflineShowsTheLastAnswerWithItsMoment() async throws {
        let store = InMemoryCacheStore()
        let online = MockWeekAPI()
        let week = try WeekFixtures.review()
        online.fetchHandler = { _ in week }
        await makeViewModel(online, store: store).load()

        let offline = MockWeekAPI()
        offline.fetchHandler = { _ in throw APIClientError.transport(code: -1009) }
        let viewModel = makeViewModel(offline, store: store)
        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.review, week)
        XCTAssertEqual(viewModel.offlineAsOf, moment)
    }

    func testOfflineWithNothingCachedIsAnError() async {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in throw APIClientError.timeout }
        let viewModel = makeViewModel(api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .failure("Сервер не ответил вовремя"))
    }

    func testBackOnlineClearsTheOfflineMark() async throws {
        let api = MockWeekAPI()
        let week = try WeekFixtures.review()
        api.fetchHandler = { _ in week }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        api.fetchHandler = { _ in throw APIClientError.timeout }
        await viewModel.load()
        XCTAssertEqual(viewModel.offlineAsOf, moment)

        api.fetchHandler = { _ in week }
        await viewModel.load()

        XCTAssertNil(viewModel.offlineAsOf)
    }

    // MARK: Stepping between weeks

    func testSteppingAsksForTheNeighbourNamedByTheServer() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { iso in
            switch iso {
            case "2026-W34": return try WeekFixtures.week("2026-W34", previous: "2026-W33", next: "2026-W35")
            case "2026-W36": return try WeekFixtures.week("2026-W36", previous: "2026-W35", next: "2026-W37")
            default: return try WeekFixtures.review()
            }
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()

        await viewModel.showPrevious()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W34")
        await viewModel.showNext()
        await viewModel.showNext()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W36")
        await viewModel.showCurrent()

        XCTAssertEqual(api.fetched, [nil, "2026-W34", "2026-W35", "2026-W36", nil])
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W35")
    }

    func testSteppingWithoutAWeekOnScreenDoesNothing() async {
        let api = MockWeekAPI()
        let viewModel = makeViewModel(api)

        await viewModel.showPrevious()

        XCTAssertTrue(api.fetched.isEmpty)
        XCTAssertEqual(viewModel.state, .idle)
    }

    func testEachWeekHasItsOwnCacheEntry() async throws {
        let store = InMemoryCacheStore()
        let online = MockWeekAPI()
        online.fetchHandler = { iso in
            iso == nil
                ? try WeekFixtures.review()
                : try WeekFixtures.week("2026-W34", previous: "2026-W33", next: "2026-W35")
        }
        let first = makeViewModel(online, store: store)
        await first.load()
        await first.showPrevious()

        let offline = MockWeekAPI()
        offline.fetchHandler = { _ in throw APIClientError.timeout }
        let second = makeViewModel(offline, store: store)
        await second.load()
        XCTAssertEqual(second.review?.window.isoCode, "2026-W35")
        await second.showPrevious()
        XCTAssertEqual(second.review?.window.isoCode, "2026-W34")
        await second.showNext()
        XCTAssertEqual(second.review?.window.isoCode, "2026-W35")
        XCTAssertEqual(second.offlineAsOf, moment)
        await second.showNext()
        XCTAssertEqual(second.state, .failure("Сервер не ответил вовремя"))
    }

    func testALateAnswerOfAWeekLeftBehindIsDropped() async throws {
        let api = MockWeekAPI()
        var release: CheckedContinuation<Void, Never>?
        api.fetchHandler = { iso in
            if iso == "2026-W34" {
                await withCheckedContinuation { release = $0 }
                return try WeekFixtures.week("2026-W34", previous: "2026-W33", next: "2026-W35")
            }
            return try WeekFixtures.review()
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()

        let slow = Task { await viewModel.showPrevious() }
        while release == nil { await Task.yield() }
        await viewModel.showCurrent()
        release?.resume()
        await slow.value

        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W35")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    // MARK: Refresh in place

    func testRefreshKeepsTheScreenAndTakesTheNewAnswer() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.runningWeek() }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        let fuller = try WeekFixtures.review()
        api.fetchHandler = { _ in fuller }

        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.review, fuller)
        XCTAssertNil(viewModel.refreshError)
    }

    func testAFailedRefreshKeepsTheWeekAndSaysWhy() async throws {
        let api = MockWeekAPI()
        let week = try WeekFixtures.review()
        api.fetchHandler = { _ in week }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        api.fetchHandler = { _ in throw APIClientError.unexpectedStatus(500) }

        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.review, week)
        XCTAssertEqual(viewModel.refreshError, "Сервер ответил ошибкой 500")
    }

    // MARK: Narrative

    func testTheNarrativeIsWrittenOnRequestForTheWeekOnScreen() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.review() }
        api.narrativeHandler = { _ in self.narrative() }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertEqual(viewModel.narrative, .idle)
        XCTAssertTrue(api.narrated.isEmpty)

        await viewModel.writeNarrative()

        XCTAssertEqual(api.narrated, ["2026-W35"])
        XCTAssertEqual(viewModel.narrative, .ready("Неделя прошла ровно."))
    }

    func testEachRefusalOfTheNarrativeHasItsWords() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.review() }
        let viewModel = makeViewModel(api)
        await viewModel.load()

        let expected: [(APIClientError, String)] = [
            (.unexpectedStatus(503), "Итог от ИИ выключен: на сервере не настроена модель."),
            (.unexpectedStatus(502), "Модель не ответила. Повторите позже."),
            (.timeout, WeekFormat.narrativeNeedsNetwork),
            (.transport(code: -1009), WeekFormat.narrativeNeedsNetwork),
        ]
        for (error, message) in expected {
            api.narrativeHandler = { _ in throw error }
            await viewModel.writeNarrative()
            XCTAssertEqual(viewModel.narrative, .failure(message))
        }
    }

    func testARetryAfterAFailureWritesTheText() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.review() }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        api.narrativeHandler = { _ in throw APIClientError.unexpectedStatus(502) }
        await viewModel.writeNarrative()
        api.narrativeHandler = { _ in self.narrative("Со второго раза.") }

        await viewModel.writeNarrative()

        XCTAssertEqual(viewModel.narrative, .ready("Со второго раза."))
    }

    func testAnEmptyWeekOffersNoNarrativeAndAsksNothing() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.emptyWeek() }
        let viewModel = makeViewModel(api)
        await viewModel.load()

        XCTAssertFalse(viewModel.canWriteNarrative)
        await viewModel.writeNarrative()

        XCTAssertTrue(api.narrated.isEmpty)
        XCTAssertEqual(viewModel.narrative, .idle)
    }

    func testAWeekWithDataOffersTheNarrativeUnlessOneIsBeingWritten() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.review() }
        var release: CheckedContinuation<Void, Never>?
        api.narrativeHandler = { _ in
            await withCheckedContinuation { release = $0 }
            return self.narrative()
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        XCTAssertTrue(viewModel.canWriteNarrative)

        let writing = Task { await viewModel.writeNarrative() }
        while release == nil { await Task.yield() }
        XCTAssertEqual(viewModel.narrative, .writing)
        XCTAssertFalse(viewModel.canWriteNarrative)
        await viewModel.writeNarrative()
        XCTAssertEqual(api.narrated.count, 1)
        release?.resume()
        await writing.value

        XCTAssertEqual(viewModel.narrative, .ready("Неделя прошла ровно."))
    }

    func testSteppingToAnotherWeekDropsTheText() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { iso in
            iso == nil
                ? try WeekFixtures.review()
                : try WeekFixtures.week("2026-W34", previous: "2026-W33", next: "2026-W35")
        }
        api.narrativeHandler = { _ in self.narrative() }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        await viewModel.writeNarrative()

        await viewModel.showPrevious()

        XCTAssertEqual(viewModel.narrative, .idle)
    }

    func testATextThatArrivesAfterALeftWeekIsNotShownOnTheNewOne() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { iso in
            iso == nil
                ? try WeekFixtures.review()
                : try WeekFixtures.week("2026-W34", previous: "2026-W33", next: "2026-W35")
        }
        var release: CheckedContinuation<Void, Never>?
        api.narrativeHandler = { _ in
            await withCheckedContinuation { release = $0 }
            return self.narrative()
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        let writing = Task { await viewModel.writeNarrative() }
        while release == nil { await Task.yield() }

        await viewModel.showPrevious()
        release?.resume()
        await writing.value

        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W34")
        XCTAssertEqual(viewModel.narrative, .idle)
    }

    func testWithoutAServerAddressTheNarrativeSaysSo() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.review() }
        let viewModel = WeekViewModel(
            apiProvider: { api }, narrativeAPIProvider: { nil }, cacheStore: InMemoryCacheStore()
        )
        await viewModel.load()

        await viewModel.writeNarrative()

        XCTAssertEqual(viewModel.narrative, .failure(WeekFormat.notConfiguredMessage))
    }

    // MARK: Entry point

    func testWeekIsOneRowUnderMore() {
        XCTAssertEqual(MoreDestination.allCases.filter { $0 == .week }.count, 1)
        XCTAssertEqual(MoreDestination.week.title, "Неделя")
        var navigation = AppNavigation()

        navigation.open(.more(.week))

        XCTAssertEqual(navigation.selectedTab, .more)
        XCTAssertEqual(navigation.morePath, [.week])
    }
}
