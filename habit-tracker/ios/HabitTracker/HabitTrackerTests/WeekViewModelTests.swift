// [review:need-review] PHASE-01/270
// [review:need-review] PHASE-03/229, PHASE-03/243, PHASE-03/261, PHASE-03/262
// summary: Week screen state tests (return to the screen reads in place, pull to refresh offline and overtaken by a step, the running week opened by its code kept as «current», a cached week that ended loses its note, no «Текущая» on the running week, one narrative request per week, 422 and a slow model in words) — load of the running week through the read cache (fresh, offline with "обновлено", nothing to show), not-configured and server errors in words, stepping between weeks with a late answer dropped, in-place refresh that keeps the screen, and the narrative on request (statuses, no network, empty week, a week change drops it)
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
        _ api: MockWeekAPI, store: CacheStore = InMemoryCacheStore(), now: Date? = nil
    ) -> WeekViewModel {
        let at = now ?? moment
        return WeekViewModel(api: api, cacheStore: store, now: { at })
    }

    /// 12:00 UTC on a Wednesday of the fixture's running week.
    private let midWeek = Date(timeIntervalSince1970: 1_787_745_600)
    /// Monday 24 August 2026, 10:00 in Berlin: the day has begun and is not closed.
    private let mondayMorning = Date(timeIntervalSince1970: 1_787_558_400)

    private func neighbours(_ iso: String) throws -> WeekReviewDTO {
        switch iso {
        case "2026-W34": return try WeekFixtures.week("2026-W34", previous: "2026-W33", next: "2026-W35")
        case "2026-W35": return try WeekFixtures.review()
        default: return try WeekFixtures.week("2026-W36", previous: "2026-W35", next: "2026-W37")
        }
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

    func testPullToRefreshWithoutANetworkKeepsTheWeekAndSaysItIsOld() async throws {
        let api = MockWeekAPI()
        let week = try WeekFixtures.review()
        api.fetchHandler = { _ in week }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        api.fetchHandler = { _ in throw APIClientError.transport(code: -1009) }

        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .loaded, "the gesture must not swap the screen for a loader")
        XCTAssertEqual(viewModel.review, week)
        XCTAssertEqual(viewModel.offlineAsOf, moment)
        XCTAssertNil(viewModel.refreshError)
    }

    func testPullToRefreshWithoutANetworkAndNothingCachedSaysWhy() async throws {
        let api = MockWeekAPI()
        let week = try WeekFixtures.review()
        api.fetchHandler = { _ in week }
        let viewModel = makeViewModel(api, store: DiscardingCacheStore())
        await viewModel.load()
        api.fetchHandler = { _ in throw APIClientError.timeout }

        await viewModel.refresh()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.review, week)
        XCTAssertEqual(viewModel.refreshError, "Сервер не ответил вовремя")
    }

    func testARefreshOvertakenByAStepToAnotherWeekIsDropped() async throws {
        let api = MockWeekAPI()
        var release: CheckedContinuation<Void, Never>?
        var slow = false
        api.fetchHandler = { iso in
            if iso == nil, slow {
                await withCheckedContinuation { release = $0 }
                return try WeekFixtures.runningWeek()
            }
            return try self.neighbours(iso ?? "2026-W35")
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        slow = true

        let refreshing = Task { await viewModel.refresh() }
        while release == nil { await Task.yield() }
        await viewModel.showPrevious()
        release?.resume()
        await refreshing.value

        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W34", "the late refresh answered about the week left behind")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testComingBackToTheScreenReadsInPlaceInsteadOfShowingTheLoader() async throws {
        let api = MockWeekAPI()
        let week = try WeekFixtures.review()
        api.fetchHandler = { _ in week }
        let viewModel = makeViewModel(api)
        await viewModel.appear()
        XCTAssertEqual(viewModel.review, week)
        var release: CheckedContinuation<Void, Never>?
        api.fetchHandler = { _ in
            await withCheckedContinuation { release = $0 }
            return week
        }

        let again = Task { await viewModel.appear() }
        while release == nil { await Task.yield() }

        XCTAssertEqual(viewModel.state, .loaded, "the week stays on screen while it is read again")
        release?.resume()
        await again.value
        XCTAssertEqual(api.fetched.count, 2)
    }

    // MARK: Running week and the cache

    func testTheRunningWeekOpenedByItsCodeIsAlsoKeptAsCurrent() async throws {
        let store = InMemoryCacheStore()
        let api = MockWeekAPI()
        api.fetchHandler = { iso in
            iso == "2026-W35" ? try WeekFixtures.runningWeek() : try self.neighbours("2026-W34")
        }
        let viewModel = makeViewModel(api, store: store, now: midWeek)
        await viewModel.load()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W34")
        await viewModel.showNext()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W35")

        let current = store.load(WeekReviewDTO.self, forKey: WeekViewModel.cacheKey(for: nil))

        XCTAssertEqual(current?.value.window.isoCode, "2026-W35")
    }

    func testOnMondayBeforeTheDayClosesTheCurrentWeekIsStillCurrent() async throws {
        // The server counts no day yet and sends no «as of»; the calendar says the week began.
        let store = InMemoryCacheStore()
        let api = MockWeekAPI()
        api.fetchHandler = { iso in
            switch iso {
            case "2026-W35": return try WeekFixtures.unclosedWeek(iso: "2026-W35")
            default: return try self.neighbours("2026-W34")
            }
        }
        let viewModel = makeViewModel(api, store: store, now: mondayMorning)
        await viewModel.load()
        await viewModel.showNext()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W35")

        XCTAssertTrue(viewModel.isShowingRunningWeek)
        XCTAssertFalse(viewModel.showsCurrentButton)
        let current = store.load(WeekReviewDTO.self, forKey: WeekViewModel.cacheKey(for: nil))
        XCTAssertEqual(current?.value.window.isoCode, "2026-W35")
    }

    func testAFinishedWeekOpenedByItsCodeIsNotKeptAsCurrent() async throws {
        let store = InMemoryCacheStore()
        let api = MockWeekAPI()
        api.fetchHandler = { iso in try self.neighbours(iso ?? "2026-W35") }
        let viewModel = makeViewModel(api, store: store)
        await viewModel.load()
        await viewModel.showPrevious()

        let current = store.load(WeekReviewDTO.self, forKey: WeekViewModel.cacheKey(for: nil))

        XCTAssertEqual(current?.value.window.isoCode, "2026-W35")
    }

    func testTheUnfinishedNoteIsShownOnAFreshRunningWeek() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.runningWeek() }
        let viewModel = makeViewModel(api, now: midWeek)

        await viewModel.load()

        XCTAssertNotNil(viewModel.partialNote)
    }

    func testACachedRunningWeekThatHasEndedSinceLosesItsUnfinishedNote() async throws {
        let store = InMemoryCacheStore()
        store.save(try WeekFixtures.runningWeek(), forKey: WeekViewModel.cacheKey(for: nil), updatedAt: midWeek)
        let offline = MockWeekAPI()
        offline.fetchHandler = { _ in throw APIClientError.timeout }

        let stillRunning = makeViewModel(offline, store: store, now: midWeek)
        await stillRunning.load()
        XCTAssertNotNil(stillRunning.partialNote, "the week has not ended: the note is true")
        XCTAssertTrue(stillRunning.isShowingRunningWeek)

        let weeksLater = makeViewModel(offline, store: store)
        await weeksLater.load()
        XCTAssertEqual(weeksLater.offlineAsOf, midWeek)
        XCTAssertEqual(
            weeksLater.partialNote, WeekFormat.incompleteDataNote(countedDays: 3),
            "the cache says the week runs; the calendar says it ended, and only 3 of 7 days are in the figures"
        )
        XCTAssertFalse(weeksLater.isShowingRunningWeek)
    }

    func testACachedEndedWeekWithAllSevenDaysNeedsNoCaption() async throws {
        let store = InMemoryCacheStore()
        let full = try WeekFixtures.review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["is_complete"] = false
            window["counted_days"] = 7
            object["window"] = window
        }
        store.save(full, forKey: WeekViewModel.cacheKey(for: nil), updatedAt: midWeek)
        let offline = MockWeekAPI()
        offline.fetchHandler = { _ in throw APIClientError.timeout }

        let viewModel = makeViewModel(offline, store: store)
        await viewModel.load()

        XCTAssertNil(viewModel.partialNote)
    }

    func testTheButtonBackToTheCurrentWeekIsNotShownOnTheCurrentWeek() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { iso in
            switch iso {
            case nil, "2026-W35": return try WeekFixtures.runningWeek()
            case "2026-W36": return try WeekFixtures.unclosedWeek(iso: "2026-W36")
            default: return try self.neighbours(iso ?? "2026-W35")
            }
        }
        let viewModel = makeViewModel(api, now: midWeek)
        await viewModel.load()
        XCTAssertFalse(viewModel.showsCurrentButton, "the week was asked for without a code")

        await viewModel.showPrevious()
        XCTAssertTrue(viewModel.showsCurrentButton)

        await viewModel.showNext()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W35")
        XCTAssertFalse(viewModel.showsCurrentButton, "the running week opened by its code is the current one")

        await viewModel.showNext()
        XCTAssertEqual(viewModel.review?.window.isoCode, "2026-W36")
        XCTAssertTrue(viewModel.showsCurrentButton, "a week that has not begun is not the current one")
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
            (.unexpectedStatus(422), "В этой неделе нет данных для итога."),
            (.timeout, WeekFormat.narrativeSlow),
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

    func testComingBackToAWeekStillBeingWrittenShowsThatWriteAndAsksNothingNew() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { iso in try self.neighbours(iso ?? "2026-W35") }
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
        XCTAssertEqual(viewModel.narrative, .idle)
        await viewModel.showNext()

        XCTAssertEqual(viewModel.narrative, .writing)
        XCTAssertFalse(viewModel.canWriteNarrative)
        await viewModel.writeNarrative()
        XCTAssertEqual(api.narrated, ["2026-W35"], "W35 → W34 → W35 must not ask the model twice")
        release?.resume()
        await writing.value
        XCTAssertEqual(viewModel.narrative, .ready("Неделя прошла ровно."))
    }

    func testTheTextOfASupersededRequestIsDropped() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { iso in try self.neighbours(iso ?? "2026-W35") }
        var releases: [String: CheckedContinuation<Void, Never>] = [:]
        api.narrativeHandler = { iso in
            await withCheckedContinuation { releases[iso] = $0 }
            return WeekNarrativeDTO(isoCode: iso, text: "Текст \(iso)", model: "m")
        }
        let viewModel = makeViewModel(api)
        await viewModel.load()
        let first = Task { await viewModel.writeNarrative() }
        while releases["2026-W35"] == nil { await Task.yield() }
        await viewModel.showPrevious()
        let second = Task { await viewModel.writeNarrative() }
        while releases["2026-W34"] == nil { await Task.yield() }

        releases["2026-W35"]?.resume()
        await first.value
        XCTAssertEqual(viewModel.narrative, .writing, "the first request no longer owns the text")
        releases["2026-W34"]?.resume()
        await second.value

        XCTAssertEqual(viewModel.narrative, .ready("Текст 2026-W34"))
    }

    func testAnEmptyWeekAnswer422IsSaidInWordsOnTheScreenModel() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { _ in try WeekFixtures.review() }
        api.narrativeHandler = { _ in throw APIClientError.unexpectedStatus(422) }
        let viewModel = makeViewModel(api)
        await viewModel.load()

        await viewModel.writeNarrative()

        XCTAssertEqual(viewModel.narrative, .failure("В этой неделе нет данных для итога."))
        XCTAssertTrue(viewModel.canWriteNarrative, "a refusal does not lock the button")
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

    func testPrepareOpensOnTheNamedWeekAndIgnoresABadCode() async throws {
        let api = MockWeekAPI()
        api.fetchHandler = { [self] in try neighbours($0 ?? "2026-W35") }
        let model = makeViewModel(api)
        model.prepare(iso: "garbage")
        XCTAssertNil(model.requestedIso)
        model.prepare(iso: "2026-W34")
        await model.load()
        XCTAssertEqual(api.fetched, ["2026-W34"])
    }
}

/// A store that remembers nothing: a screen with an answer on it and no cache under it.
private final class DiscardingCacheStore: CacheStore {
    func save<T: Encodable>(_ value: T, forKey key: String, updatedAt: Date) {}
    func load<T: Decodable>(_ type: T.Type, forKey key: String) -> CachedValue<T>? { nil }
}
