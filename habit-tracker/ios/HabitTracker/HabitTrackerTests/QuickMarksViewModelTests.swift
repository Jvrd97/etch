// [review:need-review] PHASE-01/210, PHASE-03/225, PHASE-03/236, PHASE-03/242
// summary: PHASE-03/236, 242 — an offline press carries its moment (01:00 delivered at 08:00 sends 01:00, no day), waiting presses are said to VoiceOver, the directory is read while the queue still sends; the double sits on the main actor
// summary: tests for QuickMarksViewModel — directory order from the server, a tap repaints from its own answer in one call, an offline tap goes to the shared outbox under the same key with the server's day and is shown at once, a refusal is shown and not queued, undo of the last tap, the day's sets, the cache and the queued taps over a stale directory, a delivered press re-reads the directory; also the scriptable QuickMarksAPI double shared with the Today tests
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the quick-mark endpoints. On the main actor: a screen reads it while the
/// queue replays through it, and the two must not race on its state.
@MainActor
final class MockQuickMarksAPI: QuickMarksAPI {
    var marksResult: Result<[QuickMarkDTO], Error> = .success([])
    /// Consumed one per tap; an empty script answers `invalidResponse`.
    var tapResults: [Result<QuickMarkEventDTO, Error>] = []
    var undoResult: Result<QuickMarkUndoDTO, Error> = .failure(APIClientError.invalidResponse)
    var dayEventsResult: Result<[QuickMarkDayEventDTO], Error> = .success([])
    /// Runs inside the next tap request, before its answer.
    var duringTap: (@MainActor () async -> Void)?
    private(set) var taps: [(id: Int, request: QuickMarkEventRequestDTO, key: String)] = []
    private(set) var undoneIDs: [Int] = []
    private(set) var fetchedDayEventCategories: [Int] = []
    private(set) var directoryFetches = 0
    /// What reached the double, in order: "fetch", "tap", "tap answered".
    private(set) var log: [String] = []

    /// Runs once inside the next directory read, after its answer is fixed and before it returns.
    var duringFetch: (@MainActor () async -> Void)?
    private(set) var directoryAnswers = 0

    func fetchQuickMarks() async throws -> [QuickMarkDTO] {
        directoryFetches += 1
        log.append("fetch")
        let answer = marksResult
        if let hook = duringFetch {
            duringFetch = nil
            await hook()
        }
        directoryAnswers += 1
        return try answer.get()
    }

    func tapQuickMark(
        id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String
    ) async throws -> QuickMarkEventDTO {
        taps.append((id: id, request: request, key: idempotencyKey))
        log.append("tap")
        if let hook = duringTap {
            duringTap = nil
            await hook()
        }
        defer { log.append("tap answered") }
        guard !tapResults.isEmpty else { throw APIClientError.invalidResponse }
        return try tapResults.removeFirst().get()
    }

    func undoQuickMarkEvent(id: Int) async throws -> QuickMarkUndoDTO {
        undoneIDs.append(id)
        return try undoResult.get()
    }

    func fetchQuickMarkDayEvents(categoryId: Int) async throws -> [QuickMarkDayEventDTO] {
        fetchedDayEventCategories.append(categoryId)
        return try dayEventsResult.get()
    }
}

extension QuickMarkEventDTO {
    static func stub(
        eventId: Int = 1, markId: Int = 1, total: Double? = nil, done: Bool = true
    ) -> QuickMarkEventDTO {
        QuickMarkEventDTO(
            eventId: eventId, quickMarkId: markId, entryId: 10, entryDate: "2026-10-25",
            occurredAt: "2026-10-25T09:00:00+00:00", todayTotal: total, done: done
        )
    }
}


@MainActor
final class QuickMarksViewModelTests: XCTestCase {
    private func mark(
        id: Int,
        kind: String = "increment",
        category: Int = 1,
        step: Double? = 1,
        total: Double? = nil,
        done: Bool = false,
        planned: Bool = false,
        day: String = "2026-10-25"
    ) -> QuickMarkDTO {
        QuickMarkDTO(
            id: id, label: "Mark \(id)", categoryId: category, fieldId: 10 + id, kind: kind,
            step: step, unitLabel: nil, icon: nil, color: nil, hotkey: nil, order: id,
            showInAgent: true, isActive: true, entryDate: day, todayTotal: total,
            done: done, planned: planned, planItemId: nil
        )
    }

    /// 2026-10-25 09:00 UTC unless a test moves it.
    private var clock = Date(timeIntervalSince1970: 1_792_918_800)

    private func makeViewModel(
        api: MockQuickMarksAPI,
        cache: CacheStore = InMemoryCacheStore(),
        queue: OutboxQueue? = nil
    ) -> (QuickMarksViewModel, OutboxQueue) {
        let queue = queue ?? makeQueue(api: api)
        let viewModel = QuickMarksViewModel(
            api: api, cacheStore: cache, outbox: queue,
            timeZone: TimeZone(identifier: "UTC")!,
            now: { [unowned self] in clock }
        )
        return (viewModel, queue)
    }

    private func makeQueue(api: MockQuickMarksAPI) -> OutboxQueue {
        let server = FakeOutboxServer()
        return OutboxQueue(
            store: InMemoryOutboxStore(),
            sender: { OutboxReplay(entries: server, quickMarks: api, day: server) }
        )
    }

    private func replay(_ api: MockQuickMarksAPI) -> OutboxReplay {
        let server = FakeOutboxServer()
        return OutboxReplay(entries: server, quickMarks: api, day: server)
    }

    private func queuedTap(_ markID: Int, category: Int = 1, day: String? = "2026-10-25") -> OutboxAction {
        .tapQuickMark(QueuedTap(quickMarkId: markID, categoryId: category, utcOffsetMinutes: 0, serverDay: day))
    }

    func testLoadKeepsTheServersOrderPlannedFirst() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 2, planned: true), mark(id: 1)])
        let (viewModel, _) = makeViewModel(api: api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.marks.map(\.id), [2, 1], "the client does not reorder")
        XCTAssertEqual(viewModel.coveredCategoryIDs, [1])
    }

    func testAnEmptyDirectoryIsLoadedNotAnError() async {
        let api = MockQuickMarksAPI()
        let (viewModel, _) = makeViewModel(api: api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertTrue(viewModel.marks.isEmpty)
    }

    func testATapIsOneCallAndRepaintsTheButtonFromItsOwnAnswer() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1)])
        api.tapResults = [.success(.stub(eventId: 7, markId: 1, total: 2, done: true))]
        let (viewModel, _) = makeViewModel(api: api)
        var changedCategories: [Int] = []
        viewModel.onDayChanged = { changedCategories.append($0) }
        await viewModel.load()

        await viewModel.tap(viewModel.marks[0])

        XCTAssertEqual(api.taps.count, 1)
        XCTAssertEqual(api.directoryFetches, 1, "the directory is not read again after a tap")
        XCTAssertNil(
            api.taps[0].request.entryDate,
            "the day rule may end at 04:00: a date guard from the device's calendar would refuse night taps"
        )
        XCTAssertEqual(api.taps[0].request.utcOffsetMinutes, 0)
        XCTAssertEqual(api.taps[0].request.source, "ios")
        XCTAssertNil(api.taps[0].request.value)
        XCTAssertEqual(viewModel.marks[0].todayTotal, 2)
        XCTAssertTrue(viewModel.marks[0].done)
        XCTAssertEqual(viewModel.lastEvent?.eventId, 7)
        XCTAssertEqual(changedCategories, [1])
    }

    func testAnOfflineTapIsQueuedUnderTheKeyOfTheFailedAttemptAndShownAtOnce() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, step: 0.25, total: 1)])
        api.tapResults = [.failure(APIClientError.transport(code: -1009))]
        let (viewModel, queue) = makeViewModel(api: api)
        var changedCategories: [Int] = []
        viewModel.onDayChanged = { changedCategories.append($0) }
        await viewModel.load()

        await viewModel.tap(viewModel.marks[0])

        XCTAssertNil(viewModel.errorMessage, "an offline tap is deferred, not failed")
        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertEqual(queue.pending.first?.key, api.taps.first?.key)
        XCTAssertEqual(queue.pending.first?.label, "Mark 1")
        XCTAssertEqual(
            queue.pending.first?.action,
            .tapQuickMark(
                QueuedTap(quickMarkId: 1, categoryId: 1, utcOffsetMinutes: 0, serverDay: nil, occurredAt: clock)
            ),
            "the press keeps the moment it was made; the server reads its day off it"
        )
        XCTAssertEqual(viewModel.marks[0].todayTotal, 1.25, "the press is visible straight away")
        XCTAssertTrue(viewModel.marks[0].done)
        XCTAssertNil(viewModel.lastEvent, "a tap the server has not seen cannot be taken back")
        XCTAssertTrue(changedCategories.isEmpty)
    }

    func testTheQueuedTapReachesTheServerOnceAfterTheNetworkReturns() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 0)])
        api.tapResults = [
            .failure(APIClientError.timeout),
            .success(.stub(eventId: 8, markId: 1, total: 1)),
        ]
        let (viewModel, queue) = makeViewModel(api: api)
        await viewModel.load()
        await viewModel.tap(viewModel.marks[0])
        let firstKey = api.taps[0].key

        await queue.flush(using: replay(api))

        XCTAssertEqual(api.taps.count, 2)
        XCTAssertEqual(api.taps[1].key, firstKey, "a replay is the same tap, so the day's sum cannot double")
        XCTAssertEqual(api.taps[1].request.occurredAt, "2026-10-25T09:00:00.000Z")
        XCTAssertNil(api.taps[1].request.entryDate)
        XCTAssertNil(api.taps[0].request.occurredAt, "a direct tap is the server's own moment")
        XCTAssertEqual(queue.pendingCount, 0)
    }

    func testAfterAFlushTheDirectoryIsReadAgainAndTheDaysAreAnnounced() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1, done: true)])
        let (viewModel, _) = makeViewModel(api: api)
        var changedCategories: [Int] = []
        viewModel.onDayChanged = { changedCategories.append($0) }

        await viewModel.reconcileAfterFlush(categoryIDs: [1, 2])

        XCTAssertEqual(viewModel.marks[0].todayTotal, 1)
        XCTAssertEqual(changedCategories, [1, 2])
    }

    func testADeliveredQueuedPressIsAnnouncedForItsCategory() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, category: 4, total: 0)])
        let (viewModel, queue) = makeViewModel(api: api)
        await viewModel.load()
        queue.enqueue(queuedTap(1, category: 4), label: "Mark 1")
        let announced = expectation(description: "day of category 4 announced")
        viewModel.onDayChanged = { category in
            if category == 4 { announced.fulfill() }
        }
        api.tapResults = [.success(.stub(markId: 1, total: 1))]

        await queue.flush(using: replay(api))

        await fulfillment(of: [announced], timeout: 1)
    }

    func testARefusedTapIsShownAndNotQueued() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1)])
        api.tapResults = [.failure(APIClientError.unexpectedStatus(409))]
        let (viewModel, queue) = makeViewModel(api: api)
        await viewModel.load()

        await viewModel.tap(viewModel.marks[0])

        XCTAssertNotNil(viewModel.errorMessage)
        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(viewModel.marks[0].todayTotal, 1)
        XCTAssertNil(viewModel.lastEvent)
    }

    func testUndoLastTakesTheTapBackAndRepaintsFromTheAnswer() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1)])
        api.tapResults = [.success(.stub(eventId: 7, markId: 1, total: 2))]
        api.undoResult = .success(
            QuickMarkUndoDTO(
                eventId: 7, quickMarkId: 1, entryDate: "2026-10-25",
                undoneAt: "2026-10-25T09:01:00+00:00", todayTotal: 1, done: true
            )
        )
        let (viewModel, _) = makeViewModel(api: api)
        var changedCategories: [Int] = []
        viewModel.onDayChanged = { changedCategories.append($0) }
        await viewModel.load()
        await viewModel.tap(viewModel.marks[0])
        changedCategories.removeAll()

        await viewModel.undoLast()

        XCTAssertEqual(api.undoneIDs, [7])
        XCTAssertEqual(viewModel.marks[0].todayTotal, 1)
        XCTAssertNil(viewModel.lastEvent)
        XCTAssertEqual(changedCategories, [1])
    }

    func testARefusedUndoShowsTheMessageAndRetiresTheOffer() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1)])
        api.tapResults = [.success(.stub(eventId: 7, markId: 1, total: 1))]
        api.undoResult = .failure(APIClientError.unexpectedStatus(409))
        let (viewModel, _) = makeViewModel(api: api)
        await viewModel.load()
        await viewModel.tap(viewModel.marks[0])

        await viewModel.undoLast()

        XCTAssertNotNil(viewModel.errorMessage)
        XCTAssertNil(viewModel.lastEvent, "an offer that answers 409 forever is worse than none")
    }

    func testUndoCaptionNamesTheButtonItBelongsTo() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1)])
        api.tapResults = [.success(.stub(eventId: 7, markId: 1, total: 1))]
        let (viewModel, _) = makeViewModel(api: api)
        await viewModel.load()
        XCTAssertNil(viewModel.undoCaption)

        await viewModel.tap(viewModel.marks[0])

        XCTAssertEqual(viewModel.undoCaption, "Отменить «Mark 1»")
    }

    func testUndoEventOfAnotherSetAnswersTheServersSentenceOnRefusal() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1)])
        api.undoResult = .failure(APIClientError.unexpectedStatus(409))
        let (viewModel, _) = makeViewModel(api: api)
        await viewModel.load()

        let refusal = await viewModel.undoEvent(42)

        XCTAssertNotNil(refusal)
        XCTAssertNil(viewModel.errorMessage, "the list that asked shows the sentence, not the screen under it")
    }

    func testOfflineLoadServesTheCachedDirectoryWithTheQueuedTapsOnTop() async {
        let cache = InMemoryCacheStore()
        let online = MockQuickMarksAPI()
        online.marksResult = .success([mark(id: 1, total: 1)])
        let (first, _) = makeViewModel(api: online, cache: cache)
        await first.load()

        let offline = MockQuickMarksAPI()
        offline.marksResult = .failure(APIClientError.timeout)
        offline.tapResults = [.failure(APIClientError.timeout)]
        let queue = makeQueue(api: offline)
        queue.enqueue(queuedTap(1), label: "Mark 1")
        queue.enqueue(queuedTap(2), label: "Mark 2")
        let (second, _) = makeViewModel(api: offline, cache: cache, queue: queue)
        await second.load()

        XCTAssertEqual(second.state, .loaded)
        XCTAssertNotNil(second.offlineAsOf)
        XCTAssertEqual(second.marks[0].todayTotal, 2, "the cached 1 plus the queued press")
    }

    func testOfflineWithoutACacheIsAFailure() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .failure(APIClientError.timeout)
        let (viewModel, _) = makeViewModel(api: api)

        await viewModel.load()

        guard case .failure = viewModel.state else {
            return XCTFail("expected a failure, got \(viewModel.state)")
        }
    }

    func testTheOptimisticPressFollowsTheKindOfTheButton() {
        XCTAssertEqual(mark(id: 1, kind: "increment", step: 0.5, total: 1).afterOfflineTap().todayTotal, 1.5)
        XCTAssertEqual(mark(id: 1, kind: "increment", step: 1, total: nil).afterOfflineTap().todayTotal, 1)
        XCTAssertEqual(mark(id: 1, kind: "set_value", step: 7, total: 3).afterOfflineTap().todayTotal, 7)
        let check = mark(id: 1, kind: "check", step: nil).afterOfflineTap()
        XCTAssertTrue(check.done)
        XCTAssertNil(check.todayTotal)
    }

    func testARefusedQueuedPressIsNoLongerShownOnTheButton() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1)])
        let queue = makeQueue(api: api)
        queue.enqueue(queuedTap(1), label: "Mark 1")
        api.tapResults = [.failure(APIClientError.unexpectedStatus(409))]
        let (viewModel, _) = makeViewModel(api: api, queue: queue)

        await viewModel.load()

        XCTAssertEqual(queue.failed.map(\.label), ["Mark 1"], "kept in the not-sent list with its reason")
        XCTAssertEqual(viewModel.marks[0].todayTotal, 1, "a press that is not going to land is not counted")
    }

    func testAPressAtOneAtNightDeliveredAtEightCarriesTheMomentOfThePress() async {
        // 01:00 is the previous day for a server whose day turns at 04:00; the list, read at
        // 00:30, says so. The press must not land silently on the day of delivery.
        clock = Date(timeIntervalSince1970: 1_792_888_200) // 2026-10-25 00:30 UTC
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 0, day: "2026-10-24")])
        api.tapResults = [.failure(APIClientError.transport(code: -1009))]
        let (viewModel, queue) = makeViewModel(api: api)
        await viewModel.load()

        clock = Date(timeIntervalSince1970: 1_792_890_000) // 01:00
        await viewModel.tap(viewModel.marks[0])
        clock = Date(timeIntervalSince1970: 1_792_915_200) // 08:00
        api.tapResults = [.success(.stub(markId: 1, total: 1))]
        await queue.flush(using: replay(api))

        XCTAssertEqual(api.taps.last?.request.occurredAt, "2026-10-25T01:00:00.000Z", "the moment of the press, not of delivery")
        XCTAssertNil(api.taps.last?.request.entryDate, "the server's boundary decides the day, not the phone's calendar")
        XCTAssertTrue(queue.writes.isEmpty, "delivered, not refused as a turned day")
    }

    func testWaitingPressesAreSaidToVoiceOver() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1), mark(id: 2)])
        let (viewModel, queue) = makeViewModel(api: api)
        await viewModel.load()
        queue.enqueue(queuedTap(1), label: "Mark 1")
        queue.enqueue(queuedTap(1), label: "Mark 1")

        XCTAssertEqual(viewModel.waitingCaption(of: 1), "ждёт отправки: 2")
        XCTAssertNil(viewModel.waitingCaption(of: 2))
    }

    func testADirectoryReadSentBeforeADeliveryDoesNotOverwriteTheReadAfterIt() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 0)])
        let (viewModel, queue) = makeViewModel(api: api)
        queue.enqueue(queuedTap(1, day: nil), label: "Mark 1")
        api.tapResults = [.success(.stub(markId: 1, total: 1))]
        // The press lands once the load's read is on its way; from then on the server says 1.
        api.duringTap = {
            await waitUntil { api.directoryFetches > 0 }
            api.marksResult = .success([self.mark(id: 1, total: 1)])
        }
        // The load's read was answered with 0; it returns only after the re-read put 1 on screen.
        api.duringFetch = {
            await waitUntil { api.directoryAnswers > 0 && viewModel.marks.first?.todayTotal == 1 }
        }

        await viewModel.load()

        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(viewModel.marks.first?.todayTotal, 1, "the older 0 would invite a second press")
    }

    func testTheDirectoryIsReadWhileTheQueueIsStillSending() async throws {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 0)])
        let (viewModel, queue) = makeViewModel(api: api)
        queue.enqueue(queuedTap(1), label: "Mark 1")
        api.tapResults = [.success(.stub(markId: 1, total: 1))]
        api.duringTap = { try? await Task.sleep(nanoseconds: 200_000_000) }

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        let fetched = try XCTUnwrap(api.log.firstIndex(of: "fetch"))
        let answered = try XCTUnwrap(api.log.firstIndex(of: "tap answered"))
        XCTAssertLessThan(fetched, answered, "the read does not wait for the slow send")
        XCTAssertEqual(queue.pendingCount, 0, "load still ends with the queue sent")
    }

    func testDiscardingAWaitingPressTakesItOffTheButton() async {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([mark(id: 1, total: 1)])
        api.tapResults = [.failure(APIClientError.timeout)]
        let (viewModel, queue) = makeViewModel(api: api)
        await viewModel.load()
        await viewModel.tap(viewModel.marks[0])
        XCTAssertEqual(viewModel.marks[0].todayTotal, 2)

        queue.discard(id: queue.pending[0].id)

        XCTAssertEqual(viewModel.marks[0].todayTotal, 1)
    }
}
