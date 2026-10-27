// [review:need-review] PHASE-03/225, PHASE-03/242
// summary: PHASE-03/242 — the cached-day notice says the day is from the cache, not that today is missing (wrong between midnight and the server's 04:00)
// summary: the Day screen without a network — a mark, a new fact and the notebook go to the shared outbox (the fact under the key of its attempt, the mark and notebook with the server state they were made over) and stay on screen through a re-read; a mark or notebook whose older write still waits goes through the queue, so the old one cannot land last; a delivery reads the day again; the day opens from the read cache and says when the cached day is not today; closing and fact corrections say they need the server and keep what was typed
import XCTest
@testable import HabitTracker

extension MockDayAPI: OutboxDayAPI {
    func fetchDayUnopened(date: String) async throws -> DayDetailDTO {
        try await fetchDay(date: date)
    }
}

@MainActor
final class DayOfflineTests: XCTestCase {
    private let offline = APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)
    private var api: MockDayAPI!
    private var outbox: OutboxQueue!
    private var cache: InMemoryCacheStore!
    private var viewModel: DayViewModel!

    override func setUp() async throws {
        api = MockDayAPI()
        api.fetchResults = [.success(try DayFixtures.day())]
        let day: MockDayAPI = api
        let server = FakeOutboxServer()
        outbox = OutboxQueue(
            store: InMemoryOutboxStore(),
            sender: { OutboxReplay(entries: server, quickMarks: server, day: day) }
        )
        cache = InMemoryCacheStore()
        viewModel = makeViewModel()
        await viewModel.load()
    }

    private func makeViewModel(now: Date = Date(timeIntervalSince1970: 1_792_918_800)) -> DayViewModel {
        let day: MockDayAPI = api
        return DayViewModel(
            apiProvider: { day }, timeZoneProvider: { TimeZone(identifier: "UTC")! }, outbox: outbox,
            cacheStore: cache, now: { now }
        )
    }

    // MARK: Marks

    func testAnOfflineMarkStaysOnScreenAndWaitsInTheQueue() async {
        api.markResult = .failure(offline)

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertNil(viewModel.actionError, "an offline mark is deferred, not failed")
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done")
        XCTAssertEqual(viewModel.queuedItems, [DayFixtures.minimumID])
        XCTAssertEqual(
            outbox.pending.first?.action,
            .setDayMark(
                QueuedDayMark(date: DayFixtures.date, itemID: DayFixtures.minimumID, state: "done", note: nil, expected: "")
            )
        )
        XCTAssertEqual(outbox.pending.first?.label, "Отметка «Минимум: собрать сборку»")
    }

    func testAQueuedMarkIsNotRolledBackByAReread() async {
        api.markResult = .failure(offline)
        await viewModel.cycleMark(DayFixtures.minimumID)

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done", "the server does not have it yet")
    }

    func testADeliveredMarkReadsTheDayAgainAndLosesItsQueuedSign() async throws {
        api.markResult = .failure(offline)
        await viewModel.cycleMark(DayFixtures.minimumID)
        api.markResult = .success(DayFixtures.mark(DayFixtures.minimumID, "done"))
        api.fetchResults = [.success(try DayFixtures.day(marks: [DayFixtures.mark(DayFixtures.minimumID, "done")]))]
        let readsBefore = api.fetchedDates.count

        await outbox.flush()
        for _ in 0..<100 where api.fetchedDates.count < readsBefore + 2 {
            try await Task.sleep(nanoseconds: 10_000_000)
        }

        XCTAssertEqual(api.markCalls.last?.body.state, "done")
        XCTAssertTrue(viewModel.queuedItems.isEmpty)
        XCTAssertEqual(api.fetchedDates.count, readsBefore + 2, "one read for the replay check, one for the screen")
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done")
    }

    // MARK: Facts

    func testAnOfflineFactIsQueuedUnderTheKeyOfItsAttempt() async {
        api.factResult = .failure(offline)

        let cleared = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("30"))

        XCTAssertTrue(cleared, "the input clears: the fact is kept")
        XCTAssertNil(viewModel.actionError)
        XCTAssertEqual(outbox.pending.first?.key, api.recordCalls.first?.key)
        XCTAssertEqual(viewModel.queuedItems, [DayFixtures.pushupsID])
        guard case .recordPlanFact(let fact)? = outbox.pending.first?.action else { return XCTFail("no fact queued") }
        XCTAssertEqual(fact.date, DayFixtures.date)
        XCTAssertEqual(fact.body, api.recordCalls.first?.body)
    }

    func testCorrectingAFactWithoutANetworkSaysItNeedsTheServer() async {
        api.factResult = .failure(offline)

        let cleared = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("120"), correcting: 501)

        XCTAssertFalse(cleared)
        XCTAssertEqual(viewModel.actionError, DayViewModel.factNeedsServerMessage)
        XCTAssertEqual(outbox.pendingCount, 0)
    }

    // MARK: Notebook

    func testAnOfflineNotebookSaveIsKeptAsSavedWithTheTextItWasTypedOver() async {
        api.notebookError = offline
        viewModel.notebook = "Заметка дня и вечер"

        await viewModel.saveNotebook()

        XCTAssertNil(viewModel.actionError)
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertTrue(viewModel.isNotebookQueued)
        XCTAssertEqual(
            outbox.pending.first?.action,
            .saveNotebook(QueuedNotebook(date: DayFixtures.date, content: "Заметка дня и вечер", expected: "Заметка дня"))
        )
    }

    func testAQueuedNotebookIsShownOverTheServerTextWithoutAConflict() async {
        api.notebookError = offline
        viewModel.notebook = "Заметка дня и вечер"
        await viewModel.saveNotebook()

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.notebook, "Заметка дня и вечер")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertNil(viewModel.notebookConflict)
    }

    // MARK: Reading and closing

    func testTheDayOpensFromTheCacheWithoutANetwork() async {
        api.fetchResults = [.failure(offline)]
        let reopened = makeViewModel()

        await reopened.load()

        XCTAssertEqual(reopened.state, .loaded)
        XCTAssertEqual(reopened.shownDate, DayFixtures.date)
        XCTAssertNotNil(reopened.offlineAsOf)
        XCTAssertNil(viewModel.offlineAsOf)
    }

    func testClosingWithoutANetworkSaysItNeedsTheServerAndKeepsTheFields() async {
        api.closingResult = .failure(offline)
        viewModel.closingBody = "итог дня"

        await viewModel.closeDay()

        XCTAssertEqual(viewModel.actionError, DayViewModel.closingNeedsServerMessage)
        XCTAssertEqual(viewModel.closingBody, "итог дня")
        XCTAssertEqual(outbox.pendingCount, 0)
    }

    // MARK: A write of an object that still waits

    func testAMarkOfALineWhoseOlderMarkWaitsGoesThroughTheQueue() async throws {
        api.markResult = .failure(offline)
        await viewModel.cycleMark(DayFixtures.minimumID)
        api.markResult = .success(DayFixtures.mark(DayFixtures.minimumID, "failed"))
        api.fetchResults = [.success(try DayFixtures.day(marks: [DayFixtures.mark(DayFixtures.minimumID, "failed")]))]

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertEqual(api.markCalls.map(\.body.state), ["done", "failed"], "the old tick is never sent after the new one")
        XCTAssertEqual(outbox.pendingCount, 0)
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "failed")
    }

    func testANotebookSaveWhoseOlderSaveWaitsGoesThroughTheQueue() async {
        api.notebookError = offline
        viewModel.notebook = "первый"
        await viewModel.saveNotebook()
        api.notebookError = nil

        viewModel.notebook = "второй"
        await viewModel.saveNotebook()

        XCTAssertEqual(api.notebookCalls, ["первый", "второй"])
        XCTAssertEqual(outbox.pendingCount, 0)
        XCTAssertFalse(viewModel.isNotebookDirty)
    }

    // MARK: The cached day after midnight

    func testACachedDayThatIsNotTodaySaysSo() async {
        api.fetchResults = [.failure(offline)]
        let nextMorning = makeViewModel(now: Date(timeIntervalSince1970: 1_792_990_800)) // 2026-10-26 07:00 UTC

        await nextMorning.load()

        XCTAssertEqual(nextMorning.shownDate, DayFixtures.date)
        XCTAssertEqual(nextMorning.cachedDayNotice, "Показан день из кэша: \(DayFormat.title(of: DayFixtures.date)).")
        XCTAssertNil(viewModel.cachedDayNotice)
    }

    func testBetweenMidnightAndTheServersBoundaryTheCachedDayIsNotCalledMissing() async {
        // 01:00: the phone's calendar is already on the 26th, the server's day (turning at 04:00) is
        // still the 25th, which is exactly the day in the cache.
        api.fetchResults = [.failure(offline)]
        let night = makeViewModel(now: Date(timeIntervalSince1970: 1_792_976_400)) // 2026-10-26 01:00 UTC

        await night.load()

        XCTAssertEqual(night.shownDate, DayFixtures.date)
        XCTAssertEqual(
            night.cachedDayNotice, "Показан день из кэша: \(DayFormat.title(of: DayFixtures.date)).",
            "the cache is not said to lack the day"
        )
    }

    // MARK: A read sent before a delivery

    func testADayReadSentBeforeADeliveryDoesNotOverwriteTheReadAfterIt() async throws {
        let day: MockDayAPI = api
        let server = FakeOutboxServer()
        let queue = OutboxQueue(
            store: InMemoryOutboxStore(), sender: { OutboxReplay(entries: server, quickMarks: server, day: server) }
        )
        queue.enqueue(
            .setDayMark(QueuedDayMark(date: DayFixtures.date, itemID: DayFixtures.minimumID, state: "done", note: nil, expected: nil)),
            label: "Минимум"
        )
        let marked = DayMarkDTO(itemId: DayFixtures.minimumID, state: "done", note: nil)
        // The re-read after the delivery is answered first and takes the first answer; the load's read,
        // sent before the delivery, takes the older second one.
        day.fetchResults = [.success(try DayFixtures.day(marks: [marked])), .success(try DayFixtures.day())]
        let readsBefore = day.fetchedDates.count
        let fresh = DayViewModel(
            apiProvider: { day }, timeZoneProvider: { TimeZone(identifier: "UTC")! }, outbox: queue,
            cacheStore: InMemoryCacheStore(), now: { Date(timeIntervalSince1970: 1_792_918_800) }
        )
        server.duringWrite = { await waitUntil { day.fetchedDates.count > readsBefore } }
        day.duringFetch = {
            await waitUntil { queue.pendingCount == 0 && day.fetchedDates.count > readsBefore + 1 && fresh.shownDate != nil }
        }

        await fresh.load()

        XCTAssertGreaterThan(day.fetchedDates.count, readsBefore + 1, "a delivery during the first load reads the day again")
        XCTAssertEqual(fresh.state(of: DayFixtures.minimumID), "done", "the older answer would drop the delivered mark")
        XCTAssertEqual(fresh.state, .loaded)
    }
}
