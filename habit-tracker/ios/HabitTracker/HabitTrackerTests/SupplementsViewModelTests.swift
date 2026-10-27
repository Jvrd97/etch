// [review:need-review] PHASE-03/240
// summary: tests of the Supplements screen state — the list and its states (loading, loaded, empty, error, no server), the cached list offline and a cached list of another day not claiming «принял сегодня», a press online (one POST under a key, no day) and offline (queued under the same key with the day of the press, shown at once, «ждёт отправки», survives a restart), the day boundary at 04:00, a refused press shown and not queued, a double tap sent once, delivery re-reading the list, a replay refused on a turned day and its retry to today, and adding with its checks and its need for the network
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the supplement endpoints; the queue replays through it too, so it sits on the main actor.
@MainActor
final class MockSupplementsAPI: SupplementsAPI {
    var listResult: Result<[SupplementDTO], Error> = .success([])
    var createResult: Result<SupplementDTO, Error> = .failure(APIClientError.invalidResponse)
    /// Consumed one per press; an empty script answers success.
    var markResults: [Result<SupplementIntakeDTO, Error>] = []
    private(set) var marks: [(id: Int, date: String?, key: String)] = []
    private(set) var created: [SupplementCreateDTO] = []
    private(set) var listFetches = 0

    func fetchSupplements() async throws -> [SupplementDTO] {
        listFetches += 1
        return try listResult.get()
    }

    func createSupplement(_ payload: SupplementCreateDTO) async throws -> SupplementDTO {
        created.append(payload)
        return try createResult.get()
    }

    func markIntake(supplementID: Int, intakeDate: String?, idempotencyKey: String) async throws -> SupplementIntakeDTO {
        marks.append((id: supplementID, date: intakeDate, key: idempotencyKey))
        if !markResults.isEmpty { return try markResults.removeFirst().get() }
        return SupplementIntakeDTO(id: marks.count, supplementId: supplementID, intakeDate: intakeDate ?? "2026-10-27")
    }
}

extension SupplementDTO {
    static func stub(
        id: Int, name: String = "Магний", dose: Double = 400, unit: String = "мг",
        time: String? = nil, taken: Bool = false
    ) -> SupplementDTO {
        SupplementDTO(id: id, name: name, dose: dose, unit: unit, intakeTime: time, isActive: true, takenToday: taken)
    }
}

@MainActor
final class SupplementsViewModelTests: XCTestCase {
    /// 2026-10-27 09:00 UTC; the phone is on UTC, so the server's day is 2026-10-27 here.
    private var clock = Date(timeIntervalSince1970: 1_793_091_600)
    private let offline = APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)

    private func makeViewModel(
        api: MockSupplementsAPI?,
        cache: CacheStore = InMemoryCacheStore(),
        store: OutboxStore = InMemoryOutboxStore()
    ) -> (SupplementsViewModel, OutboxQueue) {
        let queue = OutboxQueue(
            store: store,
            now: { [unowned self] in self.clock },
            sender: { api.map { OutboxReplay(entries: Unused(), quickMarks: Unused(), day: Unused(), supplements: $0) } }
        )
        let model = SupplementsViewModel(
            apiProvider: { api }, cacheStore: cache, outbox: queue, timeZone: TimeZone(identifier: "UTC")!,
            now: { [unowned self] in self.clock }
        )
        return (model, queue)
    }

    // MARK: The list

    func testLoadShowsTheSupplementsWithTheirMarks() async {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1, taken: true), .stub(id: 2, name: "Омега-3", taken: false)])
        let (model, _) = makeViewModel(api: api)

        await model.load()

        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.rows.map(\.supplement.name), ["Магний", "Омега-3"])
        XCTAssertEqual(model.rows.map(\.isTaken), [true, false])
        XCTAssertEqual(model.rows.map(\.isWaiting), [false, false])
        XCTAssertNil(model.offlineAsOf)
    }

    func testAnEmptyDirectoryIsLoadedNotAnError() async {
        let (model, _) = makeViewModel(api: MockSupplementsAPI())

        await model.load()

        XCTAssertEqual(model.state, .loaded)
        XCTAssertTrue(model.rows.isEmpty)
    }

    func testWithoutAServerAddressTheScreenSaysSo() async {
        let (model, _) = makeViewModel(api: nil)

        await model.load()

        XCTAssertEqual(model.state, .failure(SupplementsFormat.notConfiguredMessage))
    }

    func testAServerErrorIsAFailureNotACacheHit() async {
        let cache = InMemoryCacheStore()
        cache.save(
            SupplementsViewModel.Snapshot(day: "2026-10-27", items: [.stub(id: 1)]),
            forKey: SupplementsViewModel.cacheKey, updatedAt: clock
        )
        let api = MockSupplementsAPI()
        api.listResult = .failure(APIClientError.unexpectedStatus(500))
        let (model, _) = makeViewModel(api: api, cache: cache)

        await model.load()

        XCTAssertEqual(model.state, .failure("Server returned status 500"))
    }

    func testOfflineShowsTheCachedListWithItsMoment() async {
        let cache = InMemoryCacheStore()
        let cachedAt = clock.addingTimeInterval(-3600)
        cache.save(
            SupplementsViewModel.Snapshot(day: "2026-10-27", items: [.stub(id: 1, taken: true), .stub(id: 2)]),
            forKey: SupplementsViewModel.cacheKey, updatedAt: cachedAt
        )
        let api = MockSupplementsAPI()
        api.listResult = .failure(offline)
        let (model, _) = makeViewModel(api: api, cache: cache)

        await model.load()

        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.offlineAsOf, cachedAt)
        XCTAssertEqual(model.rows.map(\.isTaken), [true, false])
    }

    func testACachedListOfAnotherDayDoesNotClaimTakenToday() async {
        let cache = InMemoryCacheStore()
        cache.save(
            SupplementsViewModel.Snapshot(day: "2026-10-26", items: [.stub(id: 1, taken: true)]),
            forKey: SupplementsViewModel.cacheKey, updatedAt: clock.addingTimeInterval(-86_400)
        )
        let api = MockSupplementsAPI()
        api.listResult = .failure(offline)
        let (model, _) = makeViewModel(api: api, cache: cache)

        await model.load()

        XCTAssertEqual(model.rows.map(\.isTaken), [false], "yesterday's mark is not today's")
    }

    func testOfflineWithNothingCachedIsAFailure() async {
        let api = MockSupplementsAPI()
        api.listResult = .failure(offline)
        let (model, _) = makeViewModel(api: api)

        await model.load()

        XCTAssertEqual(model.state, .failure("Network error (\(URLError.notConnectedToInternet.rawValue))"))
    }

    // MARK: A press online

    func testAPressOnlineIsOnePostUnderAKeyAndLeavesTheDayToTheServer() async {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (model, queue) = makeViewModel(api: api)
        await model.load()

        await model.markTaken(model.rows[0].supplement)

        XCTAssertEqual(api.marks.count, 1)
        XCTAssertEqual(api.marks[0].id, 1)
        XCTAssertNil(api.marks[0].date)
        XCTAssertFalse(api.marks[0].key.isEmpty)
        XCTAssertEqual(model.rows.map(\.isTaken), [true])
        XCTAssertEqual(model.rows.map(\.isWaiting), [false])
        XCTAssertTrue(queue.writes.isEmpty)
        XCTAssertNil(model.errorMessage)
    }

    func testAMarkedRowIsNotSentTwice() async {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (model, _) = makeViewModel(api: api)
        await model.load()
        let supplement = model.rows[0].supplement

        await model.markTaken(supplement)
        await model.markTaken(supplement)

        XCTAssertEqual(api.marks.count, 1)
    }

    func testARefusedPressIsShownAndNotQueued() async {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        api.markResults = [.failure(APIClientError.unexpectedStatus(409))]
        let (model, queue) = makeViewModel(api: api)
        await model.load()

        await model.markTaken(model.rows[0].supplement)

        XCTAssertEqual(model.errorMessage, "Сервер не принял отметку (409): добавка в архиве.")
        XCTAssertEqual(model.rows.map(\.isTaken), [false])
        XCTAssertTrue(queue.writes.isEmpty)
    }

    // MARK: A press offline

    func testAPressOfflineIsQueuedUnderTheKeyOfTheAttemptAndShownAtOnce() async throws {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1, name: "Магний"), .stub(id: 2, name: "Омега-3")])
        let (model, queue) = makeViewModel(api: api)
        await model.load()
        api.markResults = [.failure(offline)]

        await model.markTaken(model.rows[0].supplement)

        let write = try XCTUnwrap(queue.pending.first)
        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertEqual(write.key, api.marks[0].key, "the failed attempt and its replay are one write")
        XCTAssertEqual(write.label, "Принял: Магний")
        XCTAssertEqual(write.action.day, "2026-10-27", "the day of the press travels with it")
        XCTAssertFalse(write.mayHaveLanded, "a dead network never left the phone")
        XCTAssertEqual(model.rows.map(\.isTaken), [true, false])
        XCTAssertEqual(model.rows.map(\.isWaiting), [true, false])
        XCTAssertNil(model.errorMessage)
    }

    func testALostAnswerIsQueuedAsOneThatMayHaveLanded() async throws {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (model, queue) = makeViewModel(api: api)
        await model.load()
        api.markResults = [.failure(APIClientError.timeout)]

        await model.markTaken(model.rows[0].supplement)

        XCTAssertEqual(try XCTUnwrap(queue.pending.first).mayHaveLanded, true)
    }

    func testAPressBeforeFourInTheMorningBelongsToTheDayBefore() async throws {
        clock = Date(timeIntervalSince1970: 1_793_062_800) // 2026-10-27 01:00 UTC
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (model, queue) = makeViewModel(api: api)
        await model.load()
        api.markResults = [.failure(offline)]

        await model.markTaken(model.rows[0].supplement)

        XCTAssertEqual(try XCTUnwrap(queue.pending.first).action.day, "2026-10-26")
    }

    func testAWaitingPressSurvivesARestart() async {
        let store = InMemoryOutboxStore()
        let cache = InMemoryCacheStore()
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (first, _) = makeViewModel(api: api, cache: cache, store: store)
        await first.load()
        api.markResults = [.failure(offline)]
        await first.markTaken(first.rows[0].supplement)

        api.listResult = .failure(offline)
        api.markResults = [.failure(offline)] // the network is still down when the app starts again
        let (second, queue) = makeViewModel(api: api, cache: cache, store: store)
        await second.load()

        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertEqual(second.rows.map(\.isWaiting), [true], "the press made before the restart is still waiting")
    }

    func testTheNetworkReturningDeliversThePressOnceAndTheListIsReadAgain() async {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (model, queue) = makeViewModel(api: api)
        await model.load()
        api.markResults = [.failure(offline)]
        await model.markTaken(model.rows[0].supplement)
        let key = api.marks[0].key
        let fetchesBefore = api.listFetches
        api.listResult = .success([.stub(id: 1, taken: true)])

        await queue.flush()

        XCTAssertEqual(api.marks.count, 2)
        XCTAssertEqual(api.marks[1].key, key)
        XCTAssertEqual(api.marks[1].date, "2026-10-27")
        XCTAssertTrue(queue.writes.isEmpty)
        await waitUntil { api.listFetches > fetchesBefore && model.rows.first?.isWaiting == false }
        XCTAssertEqual(model.rows.map(\.isTaken), [true])
    }

    func testAReplayOnATurnedDayIsRefusedAndItsRetryGoesToToday() async throws {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (model, queue) = makeViewModel(api: api)
        await model.load()
        api.markResults = [.failure(offline), .failure(APIClientError.unexpectedStatus(409))]
        await model.markTaken(model.rows[0].supplement)

        await queue.flush()

        let refused = try XCTUnwrap(queue.failed.first)
        XCTAssertEqual(refused.failureKind, .dayTurned)
        XCTAssertEqual(refused.failure, OutboxQueue.supplementDayTurnedReason)
        XCTAssertEqual(refused.retryTitle, OutboxWrite.retryTodayTitle)
        XCTAssertEqual(model.rows.map(\.isTaken), [false], "a press in the not-sent list has not landed")

        await queue.retry(id: refused.id)

        XCTAssertNil(api.marks.last?.date, "a retry from the list is a press on the server's today")
        XCTAssertEqual(api.marks.last?.key, refused.key)
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAPressOfAnArchivedSupplementOnReplayIsRefusedForGood() async throws {
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1)])
        let (_, queue) = makeViewModel(api: api)
        queue.enqueue(
            .markSupplementTaken(QueuedSupplementIntake(supplementId: 1, intakeDate: nil, pressedAt: clock)),
            label: "Принял: Магний"
        )
        api.markResults = [.failure(APIClientError.unexpectedStatus(409))]

        await queue.flush()

        let refused = try XCTUnwrap(queue.failed.first)
        XCTAssertEqual(refused.failureKind, .refused)
        XCTAssertEqual(refused.failure, OutboxQueue.supplementArchivedReason)
    }

    // MARK: Adding

    func testAddingChecksTheFormBeforeAnyRequest() async {
        let api = MockSupplementsAPI()
        let (model, _) = makeViewModel(api: api)

        var draft = SupplementDraft()
        var added = await model.add(draft)
        XCTAssertFalse(added)
        XCTAssertEqual(model.errorMessage, SupplementsFormat.nameMissingMessage)

        draft.name = "Магний"
        draft.doseText = "0"
        added = await model.add(draft)
        XCTAssertFalse(added)
        XCTAssertEqual(model.errorMessage, SupplementsFormat.doseInvalidMessage)

        draft.doseText = "400"
        draft.unit = "  "
        added = await model.add(draft)
        XCTAssertFalse(added)
        XCTAssertEqual(model.errorMessage, SupplementsFormat.unitMissingMessage)
        XCTAssertTrue(api.created.isEmpty)
    }

    func testAddingSendsTheDraftAndPutsTheSupplementOnTheList() async {
        let api = MockSupplementsAPI()
        api.createResult = .success(.stub(id: 7, name: "D3", dose: 0.5, unit: "г", time: "08:30:00"))
        let (model, _) = makeViewModel(api: api)
        var draft = SupplementDraft()
        draft.name = " D3 "
        draft.doseText = "0,5"
        draft.unit = "г"
        draft.hasTime = true
        draft.hour = 8
        draft.minute = 30

        let added = await model.add(draft)

        XCTAssertTrue(added)
        XCTAssertEqual(api.created, [SupplementCreateDTO(name: "D3", dose: 0.5, unit: "г", intakeTime: "08:30:00")])
        XCTAssertEqual(model.rows.map(\.supplement.id), [7])
        XCTAssertEqual(model.rows.map(\.isTaken), [false])
        XCTAssertNil(model.errorMessage)
    }

    func testAddingWithoutANetworkSaysItNeedsOneAndKeepsTheForm() async {
        let api = MockSupplementsAPI()
        api.createResult = .failure(offline)
        let (model, queue) = makeViewModel(api: api)
        var draft = SupplementDraft()
        draft.name = "D3"
        draft.doseText = "2000"

        let added = await model.add(draft)

        XCTAssertFalse(added)
        XCTAssertEqual(model.errorMessage, SupplementsFormat.addNeedsNetworkMessage)
        XCTAssertTrue(model.rows.isEmpty)
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAddingRefusedByTheServerShowsItsStatus() async {
        let api = MockSupplementsAPI()
        api.createResult = .failure(APIClientError.unexpectedStatus(422))
        let (model, _) = makeViewModel(api: api)
        var draft = SupplementDraft()
        draft.name = "D3"
        draft.doseText = "2000"

        let added = await model.add(draft)

        XCTAssertFalse(added)
        XCTAssertEqual(model.errorMessage, "Server returned status 422")
    }
}

/// The queue's other halves; no supplement test sends through them.
private struct Unused: OutboxEntriesAPI, QuickMarksAPI, OutboxDayAPI {
    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO { fatalError() }
    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO { fatalError() }
    func fetchQuickMarks() async throws -> [QuickMarkDTO] { fatalError() }
    func tapQuickMark(id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String) async throws -> QuickMarkEventDTO { fatalError() }
    func undoQuickMarkEvent(id: Int) async throws -> QuickMarkUndoDTO { fatalError() }
    func fetchQuickMarkDayEvents(categoryId: Int) async throws -> [QuickMarkDayEventDTO] { fatalError() }
    func fetchDayUnopened(date: String) async throws -> DayDetailDTO { fatalError() }
    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO { fatalError() }
    func recordFact(date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String) async throws -> PlanFactWriteDTO { fatalError() }
    func saveNotebook(date: String, content: String) async throws { fatalError() }
}
