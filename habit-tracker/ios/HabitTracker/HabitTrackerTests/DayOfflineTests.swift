// [review:need-review] PHASE-03/225, PHASE-03/242, PHASE-03/248, PHASE-03/256
// summary: PHASE-03/256 — a load answered after a step does not roll back the day cache; a direct mark refused with 502/504 reads the day (landed: no error, not landed: rolled back)
// summary: PHASE-03/248, 256 round 2 — a direct mark refused with 502/504 is queued (landed or not); a notebook save left in the queue or refused by it is not remembered as written, on both branches; the cache copy put back keeps its read's stamp
// summary: PHASE-03/242 — the cached-day notice says the day is from the cache, not that today is missing (wrong between midnight and the server's 04:00); a load's read answered after a delivery's re-read replaces neither the day nor the cache, a failed re-read leaves the load's day; a direct mark or notebook that lost its answer is no conflict for the next one
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

    /// A hook a test set and the code never reached would leave its assertions vacuous.
    override func tearDown() async throws {
        XCTAssertEqual(api.hooksNeverRun, [], "a hook the test set never ran")
        try await super.tearDown()
    }

    private func makeViewModel(
        now: Date = Date(timeIntervalSince1970: 1_792_918_800), clock: (() -> Date)? = nil
    ) -> DayViewModel {
        let day: MockDayAPI = api
        return DayViewModel(
            apiProvider: { day }, timeZoneProvider: { TimeZone(identifier: "UTC")! }, outbox: outbox,
            cacheStore: cache, now: clock ?? { now }
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
        let store = InMemoryCacheStore()
        let fresh = DayViewModel(
            apiProvider: { day }, timeZoneProvider: { TimeZone(identifier: "UTC")! }, outbox: queue,
            cacheStore: store, now: { Date(timeIntervalSince1970: 1_792_918_800) }
        )
        server.duringWrite = { await waitUntil { day.fetchedDates.count > readsBefore } }
        day.duringFetch = {
            await waitUntil { queue.pendingCount == 0 && day.fetchedDates.count > readsBefore + 1 && fresh.shownDate != nil }
        }

        await fresh.load()

        XCTAssertGreaterThan(day.fetchedDates.count, readsBefore + 1, "a delivery during the first load reads the day again")
        XCTAssertEqual(fresh.state(of: DayFixtures.minimumID), "done", "the older answer would drop the delivered mark")
        XCTAssertEqual(fresh.state, .loaded)
        XCTAssertEqual(
            store.load(DayDetailDTO.self, forKey: "day.today")?.value.marks.first { $0.itemId == DayFixtures.minimumID }?.state,
            "done", "the cache keeps the newer day, not the older answer"
        )
    }

    func testAReReadThatFailsDuringALoadLeavesTheLoadsDay() async throws {
        let day: MockDayAPI = api
        let server = FakeOutboxServer()
        let queue = OutboxQueue(
            store: InMemoryOutboxStore(), sender: { OutboxReplay(entries: server, quickMarks: server, day: server) }
        )
        queue.enqueue(
            .setDayMark(QueuedDayMark(date: DayFixtures.date, itemID: DayFixtures.minimumID, state: "done", note: nil, expected: nil)),
            label: "Минимум"
        )
        // The re-read after the delivery fails; the load's own read, sent before, answers with the day.
        day.fetchResults = [.failure(APIClientError.timeout), .success(try DayFixtures.day())]
        let readsBefore = day.fetchedDates.count
        let fresh = DayViewModel(
            apiProvider: { day }, timeZoneProvider: { TimeZone(identifier: "UTC")! }, outbox: queue,
            cacheStore: InMemoryCacheStore(), now: { Date(timeIntervalSince1970: 1_792_918_800) }
        )
        server.duringWrite = { await waitUntil { day.fetchedDates.count > readsBefore } }
        day.duringFetch = {
            await waitUntil { queue.pendingCount == 0 && day.fetchedDates.count > readsBefore + 1 }
            for _ in 0..<10 { await Task.yield() }
        }

        await fresh.load()

        XCTAssertEqual(fresh.state, .loaded, "the failed re-read does not replace a day the load brought")
        XCTAssertEqual(fresh.shownDate, DayFixtures.date)
        XCTAssertNil(fresh.actionError)
    }

    func testALoadAnsweredAfterAStepToAnotherDayDoesNotRollBackTheCacheOfTheDayBefore() async throws {
        let readAt = Date(timeIntervalSince1970: 1_792_918_800)
        var clock = readAt
        let vm = makeViewModel(clock: { clock })
        await vm.load()
        let marked = [DayFixtures.mark(DayFixtures.minimumID, "done")]
        // Answers in the order they are given: the re-read after the mark, the step's day, then the load's old read.
        api.fetchResults = [
            .success(try DayFixtures.day(notebook: .some("Свежий"), marks: marked)),
            .success(try DayFixtures.day(date: "2026-10-24")),
            .success(try DayFixtures.day(notebook: .some("Старый"))),
        ]
        var loadIsInFlight = false
        var loadGate: CheckedContinuation<Void, Never>?
        api.duringFetch = {
            loadIsInFlight = true
            await withCheckedContinuation { loadGate = $0 }
        }
        let load = Task { await vm.load() }
        while !loadIsInFlight { await Task.yield() }
        clock = readAt.addingTimeInterval(600)
        api.markResult = .success(marked[0])
        await vm.setMark(DayFixtures.minimumID, state: "done")
        await vm.showPreviousDay()
        XCTAssertEqual(vm.shownDate, "2026-10-24")

        clock = readAt.addingTimeInterval(1_200)
        loadGate?.resume()
        await load.value

        XCTAssertEqual(
            cache.load(DayDetailDTO.self, forKey: "day.today")?.value.notebook, "Свежий",
            "the load's older answer does not stay in the cache of the day the screen left"
        )
        XCTAssertEqual(
            cache.load(DayDetailDTO.self, forKey: "day.today")?.updatedAt, readAt.addingTimeInterval(600),
            "the copy put back is stamped with the read it came from, not with the moment of putting back"
        )
        XCTAssertEqual(vm.shownDate, "2026-10-24", "and the screen stays on the day it stepped to")
    }

    // MARK: A direct write that lost its answer

    func testAMarkWhoseDirectAnswerWasLostIsNoConflictForTheNextMark() async throws {
        api.markResult = .failure(APIClientError.timeout)
        await viewModel.cycleMark(DayFixtures.minimumID)
        XCTAssertEqual(outbox.pending.first?.mayHaveLanded, true, "a timeout may have written the mark")
        // The first PUT did land: the server holds "done".
        let landed = DayMarkDTO(itemId: DayFixtures.minimumID, state: "done", note: nil)
        api.fetchResults = [.success(try DayFixtures.day(marks: [landed]))]
        let next = DayFormat.nextMark(after: "done")
        api.markResult = .success(DayMarkDTO(itemId: DayFixtures.minimumID, state: next, note: nil))

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertTrue(outbox.writes.isEmpty, "the server holding the lost mark is not a change made elsewhere")
        XCTAssertEqual(api.markCalls.last?.body.state, next)
    }

    func testANotebookWhoseDirectAnswerWasLostIsNoConflictForTheNextSave() async throws {
        api.notebookError = APIClientError.timeout
        viewModel.notebook = "один"
        await viewModel.saveNotebook()
        XCTAssertEqual(outbox.pending.first?.mayHaveLanded, true)
        // The first PUT did land: the server holds "один".
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("один")))]
        api.notebookError = nil

        viewModel.notebook = "один и два"
        await viewModel.saveNotebook()

        XCTAssertTrue(outbox.writes.isEmpty, "the server holding the lost save is not a change made elsewhere")
        XCTAssertEqual(api.notebookCalls.last, "один и два")
    }

    func testAMarkRefusedWith504IsQueuedAsOneThatMayHaveLanded() async {
        api.markResult = .failure(APIClientError.unexpectedStatus(504))

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertNil(viewModel.actionError, "the proxy timed out: the backend may have written the mark")
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done", "the tick stays, as after a timeout")
        XCTAssertEqual(viewModel.queuedItems, [DayFixtures.minimumID])
        XCTAssertEqual(outbox.pending.first?.mayHaveLanded, true)
    }

    func testAMarkRefusedWith502IsQueuedAndItsLandedStateIsNoConflictForTheNextMark() async throws {
        api.markResult = .failure(APIClientError.unexpectedStatus(502))
        await viewModel.cycleMark(DayFixtures.minimumID)
        XCTAssertEqual(outbox.pending.first?.mayHaveLanded, true)
        // The first PUT did land after the proxy gave up.
        let landed = DayMarkDTO(itemId: DayFixtures.minimumID, state: "done", note: nil)
        api.fetchResults = [.success(try DayFixtures.day(marks: [landed]))]
        let next = DayFormat.nextMark(after: "done")
        api.markResult = .success(DayMarkDTO(itemId: DayFixtures.minimumID, state: next, note: nil))

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertTrue(outbox.writes.isEmpty, "the server holding the mark the proxy lost is not a change made elsewhere")
        XCTAssertEqual(api.markCalls.last?.body.state, next)
    }

    func testAMarkRefusedWith500IsRolledBackAndNotQueued() async {
        api.markResult = .failure(APIClientError.unexpectedStatus(500))

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertEqual(outbox.pendingCount, 0, "a refusal of the backend itself wrote nothing")
        XCTAssertNil(viewModel.state(of: DayFixtures.minimumID))
        XCTAssertEqual(viewModel.actionError, DayViewModel.markFailedMessage)
    }

    // MARK: A save the server never took is not remembered as written

    /// The older save of day A waits; the new one replaces it in the queue, the replay finds the web's
    /// text on the server and refuses it. While that save ends, the person is on day B and the return to A is
    /// on its way: its answer holds the text the day started with, and must not be turned into the refused text.
    func testAQueuedNotebookSaveTheServerRefusedIsNotRememberedAsWritten() async throws {
        viewModel.notebook = "T2"
        outbox.enqueue(
            .saveNotebook(QueuedNotebook(date: DayFixtures.date, content: "T1", expected: "Заметка дня")), label: "Блокнот"
        )
        var returnIsInFlight = false
        var returnGate: CheckedContinuation<Void, Never>?
        var returned: Task<Void, Never>?
        api.fetchResults = [
            .success(try DayFixtures.day(date: "2026-10-24")),
            .success(try DayFixtures.day(notebook: .some("Веб"))),
            .success(try DayFixtures.day()),
        ]
        // The replay reads the day to check its base; in that read the person steps to B and back to A.
        api.duringFetch = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.duringFetch = {
                returnIsInFlight = true
                await withCheckedContinuation { returnGate = $0 }
            }
            returned = Task { await viewModel!.showNextDay() }
            while !returnIsInFlight { await Task.yield() }
        }

        await viewModel.saveNotebook()
        XCTAssertEqual(outbox.failedCount, 1, "the replay refused the save: the web changed the text")
        returnGate?.resume()
        await returned?.value

        XCTAssertEqual(viewModel.shownDate, DayFixtures.date)
        XCTAssertNotEqual(viewModel.notebook, "T2", "the server never took T2; an old answer must not say it did")
    }

    func testADirectNotebookSaveThatWaitsInTheQueueIsNotRememberedAsWritten() async throws {
        viewModel.notebook = "T"
        api.notebookError = offline
        var returnIsInFlight = false
        var returnGate: CheckedContinuation<Void, Never>?
        var returned: Task<Void, Never>?
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.duringFetch = {
                returnIsInFlight = true
                await withCheckedContinuation { returnGate = $0 }
            }
            returned = Task { await viewModel!.showNextDay() }
            while !returnIsInFlight { await Task.yield() }
        }
        await viewModel.saveNotebook()
        api.duringNotebookSave = nil
        XCTAssertEqual(outbox.pendingCount, 1)
        // The queue's replay then finds the web's text and refuses the save.
        api.notebookError = nil
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Веб"))), .success(try DayFixtures.day())]
        await outbox.flush()
        XCTAssertEqual(outbox.failedCount, 1)

        returnGate?.resume()
        await returned?.value

        XCTAssertEqual(viewModel.shownDate, DayFixtures.date)
        XCTAssertNotEqual(viewModel.notebook, "T", "the server never took T; an old answer must not say it did")
    }
}
