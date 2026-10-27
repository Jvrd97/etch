// [review:need-review] PHASE-01/12-ios-offline-queue, PHASE-03/225, PHASE-03/236, PHASE-03/242
// summary: PHASE-03/236, 242 — a press carries its moment and no day, a 422 on the moment is "not sent" with "write to today", a stored press without a moment still decodes; a write replacing one that landed with its answer lost is not a conflict, a state none of them made still is, nor one of a write that never left; which failures may have landed (timeout, dropped connection, 502/504) and which never left; a store written before the flag opens with it off; a retry over a newer write says so
// summary: tests for the one offline write queue — airplane mode → write → network back → one record on a server that dedupes by key; a send cut mid-way is repeated under the same key; a relaunch with a non-empty queue; order across kinds; 5xx kept (only five in a row give up, a dead network resets the count), 4xx in the visible "not sent" list with a reason, 401 waits and says so; an unreadable answer of the replay check refuses instead of passing for delivered; a 409 of a press without a day is not called a day turn; retry sends at once; a newer "set" replaces the waiting one; retry and discard from the list; the day a write was made survives midnight (explicit dates stay, a quick-mark press is refused instead of landing in the next day); a stale notebook or mark is refused instead of overwriting fresher server data; one-time import of the two old queues
import Combine
import SwiftData
import XCTest
@testable import HabitTracker

/// A server in miniature: it keeps what it was sent, answers a repeated Idempotency-Key with the
/// original instead of a second row, and holds the day state the replay checks against. On the main
/// actor, so a screen reading while the queue sends cannot race on its state.
@MainActor
final class FakeOutboxServer: OutboxEntriesAPI, QuickMarksAPI, OutboxDayAPI {
    /// What the server holds, one row per accepted key.
    private(set) var rowsByKey: [String: OutboxAction] = [:]
    private(set) var requests: [(action: String, key: String?)] = []
    /// The server's current day (quick-mark taps land here).
    var today = "2026-10-26"
    var notebooks: [String: String] = [:]
    var marks: [String: [UUID: String]] = [:]
    var unopenedFetches: [String] = []
    /// Thrown by the read of the day the replay checks run on.
    var dayFetchError: Error?
    /// Consumed one per write request before it is handled; empty answers normally.
    var failures: [Error] = []
    /// Fails after the server has stored the write: the answer is lost on the way back.
    var loseNextAnswer = false
    /// Runs inside the next write request, before its answer.
    var duringWrite: (@MainActor () async -> Void)?

    var rowCount: Int { rowsByKey.count }

    /// `apply` stores a write that has no key (a mark, a notebook), so a lost answer can follow it too.
    private func handle(
        _ name: String, key: String?, action: OutboxAction?, apply: () -> Void = {}
    ) async throws {
        requests.append((name, key))
        if let hook = duringWrite {
            duringWrite = nil
            await hook()
        }
        if !failures.isEmpty { throw failures.removeFirst() }
        if let key, let action, rowsByKey[key] == nil { rowsByKey[key] = action }
        apply()
        if loseNextAnswer {
            loseNextAnswer = false
            throw APIClientError.transport(code: URLError.networkConnectionLost.rawValue)
        }
    }

    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO {
        try await handle("entry", key: idempotencyKey, action: .createEntry(entry))
        return EntryDTO(id: 1, categoryId: entry.categoryId, entryDate: entry.entryDate, values: entry.values)
    }

    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO {
        try await handle("checklist", key: "checklist-\(payload.categoryId)-\(payload.entryDate)", action: .upsertChecklist(payload))
        return EntryDTO(id: 2, categoryId: payload.categoryId, entryDate: payload.entryDate, values: [])
    }

    private(set) var tapRequests: [QuickMarkEventRequestDTO] = []

    func fetchQuickMarks() async throws -> [QuickMarkDTO] { [] }

    func tapQuickMark(id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String) async throws -> QuickMarkEventDTO {
        tapRequests.append(request)
        if let day = request.entryDate, day != today {
            requests.append(("tap", idempotencyKey))
            throw APIClientError.unexpectedStatus(409)
        }
        let tap = QueuedTap(quickMarkId: id, categoryId: 0, utcOffsetMinutes: request.utcOffsetMinutes, serverDay: today)
        try await handle("tap", key: idempotencyKey, action: .tapQuickMark(tap))
        return QuickMarkEventDTO(
            eventId: 1, quickMarkId: id, entryId: 1, entryDate: today, occurredAt: "\(today)T09:00:00+00:00",
            todayTotal: 1, done: true
        )
    }

    func undoQuickMarkEvent(id: Int) async throws -> QuickMarkUndoDTO { throw APIClientError.invalidResponse }
    func fetchQuickMarkDayEvents(categoryId: Int) async throws -> [QuickMarkDayEventDTO] { [] }

    func fetchDayUnopened(date: String) async throws -> DayDetailDTO {
        unopenedFetches.append(date)
        if let dayFetchError { throw dayFetchError }
        let marks = (marks[date] ?? [:]).map { DayMarkDTO(itemId: $0.key, state: $0.value, note: nil) }
        return try DayFixtures.day(date: date, notebook: .some(notebooks[date]), marks: marks)
    }

    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO {
        try await handle("mark", key: nil, action: nil) { marks[date, default: [:]][itemID] = payload.state }
        return DayMarkDTO(itemId: itemID, state: payload.state, note: payload.note)
    }

    private(set) var factBodies: [PlanFactRequestDTO] = []

    func recordFact(date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String) async throws -> PlanFactWriteDTO {
        factBodies.append(payload)
        let fact = QueuedPlanFact(date: date, itemID: itemID, body: payload)
        try await handle("fact", key: idempotencyKey, action: .recordPlanFact(fact))
        return PlanFactWriteDTO(entryId: 9, facts: nil, mark: DayMarkDTO(itemId: itemID, state: "done", note: nil))
    }

    func saveNotebook(date: String, content: String) async throws {
        try await handle("notebook", key: nil, action: nil) { notebooks[date] = content }
    }
}

/// The queue's record as round 2 of #225 stored it, before `mayHaveLanded`: the same entity name, so
/// SwiftData opens a store written with it under the current model.
enum OutboxStoreRound2 {
    @Model
    final class PendingWriteRecord {
        @Attribute(.unique) var id: UUID
        var key: String
        var action: Data
        var label: String
        var createdAt: Date
        var serverErrors: Int = 0
        var statusRaw: String
        var failure: String?
        var failureKindRaw: String?

        init(key: String, action: Data, label: String) {
            self.id = UUID()
            self.key = key
            self.action = action
            self.label = label
            self.createdAt = Date(timeIntervalSince1970: 1_792_990_800)
            self.statusRaw = PendingStatus.pending.rawValue
        }
    }
}

/// Mock NWPathMonitor: records the flush handler and lets a test fire "became online".
final class MockNetworkMonitor: NetworkPathMonitoring {
    private var handler: (() async -> Void)?
    private(set) var started = false

    func onBecameOnline(_ handler: @escaping () async -> Void) {
        self.handler = handler
    }

    func start() {
        started = true
    }

    func simulateOnline() async {
        await handler?()
    }
}

@MainActor
final class OutboxQueueTests: XCTestCase {
    private var clock = Date(timeIntervalSince1970: 1_792_990_800) // 2026-10-26 07:00 UTC

    private func makeQueue(store: OutboxStore = InMemoryOutboxStore(), server: FakeOutboxServer? = nil) -> OutboxQueue {
        OutboxQueue(
            store: store,
            now: { [unowned self] in
                defer { clock += 1 }
                return clock
            },
            sender: { server.map { OutboxReplay(entries: $0, quickMarks: $0, day: $0) } }
        )
    }

    private func replay(_ server: FakeOutboxServer) -> OutboxReplay {
        OutboxReplay(entries: server, quickMarks: server, day: server)
    }

    private func entry(_ count: String, date: String = "2026-10-26") -> OutboxAction {
        .createEntry(
            EntryCreateDTO(categoryId: 1, entryDate: date, notes: nil, values: [EntryValueDTO(fieldId: 10, value: count)])
        )
    }

    private func tap(day: String? = "2026-10-26") -> OutboxAction {
        .tapQuickMark(QueuedTap(quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 180, serverDay: day))
    }

    private func momentTap(at pressed: Date) -> OutboxAction {
        .tapQuickMark(QueuedTap(quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 180, serverDay: nil, occurredAt: pressed))
    }

    private func notebook(_ content: String, expected: String?, date: String = "2026-10-26") -> OutboxAction {
        .saveNotebook(QueuedNotebook(date: date, content: content, expected: expected))
    }

    // MARK: Airplane mode, then the network

    func testAWriteMadeOfflineReachesTheServerOnceWhenTheNetworkReturns() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("42"), label: "Отжимания")
        server.failures = [APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)]

        await queue.flush(using: replay(server))
        XCTAssertEqual(queue.pendingCount, 1, "airplane mode keeps the write")
        XCTAssertEqual(server.rowCount, 0)

        await queue.flush(using: replay(server))
        XCTAssertEqual(server.rowCount, 1)
        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(Set(server.requests.map(\.key)).count, 1, "every attempt carried one key")
    }

    func testASendCutMidWayIsRepeatedUnderTheSameKeyAndTheServerKeepsOneRow() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("42"), label: "Отжимания")
        server.loseNextAnswer = true

        await queue.flush(using: replay(server))
        XCTAssertEqual(queue.pendingCount, 1, "no answer: the write may or may not have landed, so it stays")

        await queue.flush(using: replay(server))
        XCTAssertEqual(server.requests.count, 2)
        XCTAssertEqual(server.requests[0].key, server.requests[1].key)
        XCTAssertEqual(server.rowCount, 1, "the repeat is the same write, not a second one")
        XCTAssertEqual(queue.pendingCount, 0)
    }

    func testTheKeyOfTheFailedDirectAttemptIsTheKeyOfTheReplay() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("42"), key: "direct-attempt-key", label: "Отжимания")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.requests.map(\.key), ["direct-attempt-key"])
    }

    func testAutoFlushRunsWhenTheNetworkComesBack() async {
        let server = FakeOutboxServer()
        let queue = makeQueue(server: server)
        queue.enqueue(entry("42"), label: "Отжимания")
        let monitor = MockNetworkMonitor()

        queue.startAutoFlush(monitor: monitor)
        XCTAssertTrue(monitor.started)
        await monitor.simulateOnline()

        XCTAssertEqual(server.rowCount, 1)
        XCTAssertEqual(queue.pendingCount, 0)
    }

    // MARK: Relaunch

    func testAQueueWithWritesSurvivesARelaunch() async throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("outbox-\(UUID().uuidString).store")
        defer { Self.removeStore(at: url) }
        let first = makeQueue(store: try SwiftDataOutboxStore(url: url))
        first.enqueue(entry("42"), key: "k-entry", label: "Отжимания")
        first.enqueue(tap(), key: "k-tap", label: "Вода")
        first.enqueue(notebook("утро", expected: ""), key: "k-notebook", label: "Блокнот")

        let relaunched = makeQueue(store: try SwiftDataOutboxStore(url: url))

        XCTAssertEqual(relaunched.pending.map(\.key), ["k-entry", "k-tap", "k-notebook"])
        XCTAssertEqual(relaunched.pending.map(\.label), ["Отжимания", "Вода", "Блокнот"])
        XCTAssertEqual(relaunched.pending[1].action, tap())
        let server = FakeOutboxServer()
        await relaunched.flush(using: replay(server))
        XCTAssertEqual(server.requests.map(\.action), ["entry", "tap", "notebook"])
        XCTAssertEqual(relaunched.pendingCount, 0)
    }

    func testANotSentWriteAndItsReasonSurviveARelaunch() async throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("outbox-\(UUID().uuidString).store")
        defer { Self.removeStore(at: url) }
        let first = makeQueue(store: try SwiftDataOutboxStore(url: url))
        first.enqueue(entry("42"), label: "Отжимания")
        let server = FakeOutboxServer()
        server.failures = [APIClientError.unexpectedStatus(422)]
        await first.flush(using: replay(server))

        let relaunched = makeQueue(store: try SwiftDataOutboxStore(url: url))

        XCTAssertEqual(relaunched.failed.count, 1)
        XCTAssertEqual(relaunched.failed.first?.failure, first.failed.first?.failure)
        XCTAssertNotNil(relaunched.failed.first?.failure)
    }

    // MARK: Order and errors

    func testWritesOfEveryKindReplayInTheOrderTheyWereMade() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        queue.enqueue(tap(), label: "b")
        queue.enqueue(.setDayMark(QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: "done", note: nil, expected: "")), label: "c")
        queue.enqueue(entry("2"), label: "d")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.requests.map(\.action), ["entry", "tap", "mark", "entry"])
    }

    func testADeadNetworkStopsTheFlushSoNothingOvertakesTheWriteThatFailed() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        queue.enqueue(entry("2"), label: "b")
        server.failures = [APIClientError.timeout]

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.requests.count, 1)
        XCTAssertEqual(queue.pending.map(\.label), ["a", "b"])
    }

    func testAServerErrorKeepsTheWriteAndStopsTheFlush() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        queue.enqueue(entry("2"), label: "b")
        server.failures = [APIClientError.unexpectedStatus(503)]

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.requests.count, 1)
        XCTAssertEqual(queue.pendingCount, 2, "a 5xx loses nothing")
        XCTAssertEqual(queue.pending.first?.serverErrors, 1)
    }

    func testAServerErrorThatPersistsMovesTheWriteToNotSentInsteadOfDroppingIt() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        server.failures = Array(repeating: APIClientError.unexpectedStatus(500), count: OutboxQueue.maxServerErrorAttempts)

        for _ in 0..<OutboxQueue.maxServerErrorAttempts {
            await queue.flush(using: replay(server))
        }

        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(queue.failed.map(\.label), ["a"])
        XCTAssertTrue(queue.failed.first?.failure?.contains("500") == true)
    }

    func testARefusalGoesToNotSentWithItsReasonAndDoesNotBlockTheRest() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        queue.enqueue(entry("2"), label: "b")
        server.failures = [APIClientError.unexpectedStatus(422)]

        await queue.flush(using: replay(server))

        XCTAssertEqual(queue.failed.map(\.label), ["a"])
        XCTAssertTrue(queue.failed.first?.failure?.contains("422") == true)
        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(server.rowCount, 1)
        XCTAssertEqual(queue.failedCount, 1)
    }

    func testAWrongKeyKeepsEveryWriteWaiting() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        server.failures = [APIClientError.unauthorized]

        await queue.flush(using: replay(server))

        XCTAssertEqual(queue.pendingCount, 1, "fixing the key in Settings must not cost the writes")
        XCTAssertEqual(queue.failedCount, 0)
    }

    func testOnlyAFlushThatDeliveredSomethingAnnouncesIt() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        var announced: [[String]] = []
        let subscription = queue.delivered.sink { announced.append($0.map(\.label)) }
        queue.enqueue(entry("1"), label: "a")
        server.failures = [APIClientError.timeout]
        await queue.flush(using: replay(server))
        XCTAssertTrue(announced.isEmpty)

        await queue.flush(using: replay(server))

        XCTAssertEqual(announced, [["a"]])
        subscription.cancel()
    }

    // MARK: One object, several writes

    func testANewerSetOfTheSameObjectReplacesTheWaitingOneAndKeepsItsBase() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(notebook("утро", expected: "с сервера"), label: "Блокнот")
        queue.enqueue(notebook("утро и вечер", expected: "утро"), label: "Блокнот")

        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertEqual(
            queue.pending.first?.action, notebook("утро и вечер", expected: "с сервера"),
            "the replaced save never left the phone: its text is no state the server can hold"
        )
        server.notebooks["2026-10-26"] = "с сервера"
        await queue.flush(using: replay(server))
        XCTAssertEqual(server.notebooks["2026-10-26"], "утро и вечер")
    }

    func testAWriteMadeWhileTheSameObjectIsInFlightIsSentAfterIt() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        server.notebooks["2026-10-26"] = ""
        queue.enqueue(notebook("один", expected: ""), label: "Блокнот")
        server.duringWrite = { [unowned queue] in
            queue.enqueue(self.notebook("два", expected: "один"), label: "Блокнот")
        }

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.requests.map(\.action), ["notebook", "notebook"])
        XCTAssertEqual(server.notebooks["2026-10-26"], "два")
        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(queue.failedCount, 0)
    }

    func testAMarkThatLandedWithItsAnswerLostIsNoConflictForTheMarkReplacingIt() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        let first = QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: "done", note: nil, expected: "")
        queue.enqueue(.setDayMark(first), label: "Релиз")
        server.loseNextAnswer = true
        await queue.flush(using: replay(server))
        XCTAssertEqual(server.marks["2026-10-26"]?[DayFixtures.taskID], "done", "A landed, its answer did not")
        XCTAssertEqual(queue.pendingCount, 1)

        let second = QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: "failed", note: nil, expected: "done")
        queue.enqueue(.setDayMark(second), label: "Релиз")
        await queue.flush(using: replay(server))

        XCTAssertEqual(server.marks["2026-10-26"]?[DayFixtures.taskID], "failed")
        XCTAssertTrue(queue.writes.isEmpty, "the server holding A's state is not a change made elsewhere")
    }

    func testANotebookThatLandedWithItsAnswerLostIsNoConflictForTheSaveReplacingIt() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        server.notebooks["2026-10-26"] = ""
        queue.enqueue(notebook("один", expected: ""), label: "Блокнот")
        server.loseNextAnswer = true
        await queue.flush(using: replay(server))

        queue.enqueue(notebook("один и два", expected: "один"), label: "Блокнот")
        await queue.flush(using: replay(server))

        XCTAssertEqual(server.notebooks["2026-10-26"], "один и два")
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAMarkReplacingOneThatNeverLeftThePhoneStillSeesAChangeMadeElsewhere() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        let first = QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: "done", note: nil, expected: "")
        queue.enqueue(.setDayMark(first), label: "Релиз")
        let second = QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: nil, note: nil, expected: "done")
        queue.enqueue(.setDayMark(second), label: "Релиз")
        // On the web the same line was marked done meanwhile; the phone's "done" never reached the server.
        server.marks["2026-10-26"] = [DayFixtures.taskID: "done"]

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.marks["2026-10-26"]?[DayFixtures.taskID], "done", "the web's mark is not wiped silently")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.markChangedReason)
    }

    func testWhichFailuresMayHaveLanded() {
        func transport(_ code: URLError.Code) -> Error { APIClientError.transport(code: code.rawValue) }
        let neverLeft: [Error] = [
            transport(.notConnectedToInternet), transport(.cannotConnectToHost), transport(.cannotFindHost),
            transport(.dnsLookupFailed), APIClientError.unexpectedStatus(500), APIClientError.unexpectedStatus(503),
            APIClientError.unexpectedStatus(409), APIClientError.unauthorized, OutboxConflict(reason: "x"),
        ]
        let mayHaveLanded: [Error] = [
            APIClientError.timeout, transport(.networkConnectionLost), transport(.secureConnectionFailed),
            APIClientError.unexpectedStatus(502), APIClientError.unexpectedStatus(504),
        ]
        for error in neverLeft { XCTAssertFalse(OutboxQueue.mayHaveLanded(after: error), "\(error)") }
        for error in mayHaveLanded { XCTAssertTrue(OutboxQueue.mayHaveLanded(after: error), "\(error)") }
    }

    func testAProxysGatewayErrorCountsAsAWriteThatMayHaveLanded() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(notebook("один", expected: ""), label: "Блокнот")
        server.failures = [APIClientError.unexpectedStatus(502)]

        await queue.flush(using: replay(server))

        XCTAssertTrue(queue.pending[0].mayHaveLanded, "the backend behind the proxy may have written it")
    }

    func testAQueueStoredBeforeTheFlagOpensWithTheFlagOff() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("outbox-r2-\(UUID().uuidString).store")
        defer { Self.removeStore(at: url) }
        do {
            let container = try ModelContainer(
                for: OutboxStoreRound2.PendingWriteRecord.self, configurations: ModelConfiguration(url: url)
            )
            let context = ModelContext(container)
            let action = try CacheCoding.encoder().encode(notebook("один", expected: ""))
            context.insert(OutboxStoreRound2.PendingWriteRecord(key: "k-old", action: action, label: "Блокнот"))
            try context.save()
        }

        let writes = try SwiftDataOutboxStore(url: url).fetchAll()

        XCTAssertEqual(writes.map(\.key), ["k-old"])
        XCTAssertEqual(writes.first?.action, notebook("один", expected: ""))
        XCTAssertEqual(writes.first?.mayHaveLanded, false)
    }

    func testADeadNetworkDoesNotCountAsAWriteThatMayHaveLanded() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(notebook("один", expected: ""), label: "Блокнот")
        server.failures = [APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)]
        await queue.flush(using: replay(server))
        XCTAssertFalse(queue.pending[0].mayHaveLanded, "no connection: the request never left")

        server.failures = [APIClientError.timeout]
        await queue.flush(using: replay(server))
        XCTAssertTrue(queue.pending[0].mayHaveLanded, "a timeout may have landed")
    }

    func testAReplacementStillRefusesAStateNoneOfTheWritesMade() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(notebook("один", expected: ""), label: "Блокнот")
        queue.enqueue(notebook("один и два", expected: "один"), label: "Блокнот")
        server.notebooks["2026-10-26"] = "из веба"

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.notebooks["2026-10-26"], "из веба")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.notebookChangedReason)
    }

    func testAddingsAreNeverMerged() {
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        queue.enqueue(entry("1"), label: "a")
        queue.enqueue(tap(), label: "b")
        queue.enqueue(tap(), label: "b")

        XCTAssertEqual(queue.pendingCount, 4, "two presses are two presses")
    }

    // MARK: Not sent: retry and discard

    func testRetryFromNotSentSendsAgainUnderTheSameKeyAfterTheNewerWrites() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), key: "k1", label: "a")
        server.failures = [APIClientError.unexpectedStatus(409)]
        await queue.flush(using: replay(server))
        queue.enqueue(entry("2"), key: "k2", label: "b")

        await queue.retry(id: queue.failed[0].id)

        XCTAssertEqual(queue.pending.map(\.key), ["k2", "k1"], "a deliberate retry is the newest action")
        XCTAssertEqual(queue.pending.last?.serverErrors, 0)
        XCTAssertNil(queue.pending.last?.failure)
        await queue.flush(using: replay(server))
        XCTAssertEqual(server.rowCount, 2)
    }

    func testRetryOfAnOlderWriteSaysItWillWriteOverTheNewerOne() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        server.notebooks["2026-10-26"] = "из веба"
        queue.enqueue(notebook("утро", expected: "с сервера"), label: "Блокнот утро")
        await queue.flush(using: replay(server))
        queue.enqueue(notebook("вечер", expected: "из веба"), label: "Блокнот вечер")
        queue.enqueue(entry("1"), label: "Отжимания")

        XCTAssertEqual(
            queue.retryWarning(for: queue.failed[0]),
            "Повтор запишет это поверх более новой записи «Блокнот вечер»."
        )
        XCTAssertNil(queue.retryWarning(for: queue.pending[0]), "nothing newer of that object")
    }

    func testRetryOfAnAdditionWarnsOfNothing() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        server.failures = [APIClientError.unexpectedStatus(400)]
        await queue.flush(using: replay(server))
        queue.enqueue(entry("1"), label: "a")

        XCTAssertNil(queue.retryWarning(for: queue.failed[0]), "two entries are two entries")
    }

    func testDiscardForgetsTheWrite() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        server.failures = [APIClientError.unexpectedStatus(404)]
        await queue.flush(using: replay(server))

        queue.discard(id: queue.failed[0].id)

        XCTAssertTrue(queue.writes.isEmpty)
    }

    // MARK: Midnight

    func testAnEntryMadeBeforeMidnightKeepsItsDayWhenSentAfter() async {
        let server = FakeOutboxServer()
        server.today = "2026-10-27"
        let queue = makeQueue()
        queue.enqueue(entry("42", date: "2026-10-26"), label: "Отжимания")

        await queue.flush(using: replay(server))

        guard case .createEntry(let sent)? = server.rowsByKey.values.first else { return XCTFail("nothing sent") }
        XCTAssertEqual(sent.entryDate, "2026-10-26")
    }

    func testAPressMadeBeforeMidnightIsRefusedInsteadOfLandingInTheNextDay() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(tap(day: "2026-10-26"), label: "Вода")
        server.today = "2026-10-27"

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.tapRequests.map(\.entryDate), ["2026-10-26"])
        XCTAssertEqual(server.rowCount, 0, "nothing lands in the 27th")
        XCTAssertEqual(queue.failed.map(\.label), ["Вода"])
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.dayTurnedReason)
        XCTAssertEqual(queue.failed.first?.retryTitle, OutboxWrite.retryTodayTitle)
    }

    func testRetryingARefusedPressSendsItToTheServersToday() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(tap(day: "2026-10-26"), label: "Вода")
        server.today = "2026-10-27"
        await queue.flush(using: replay(server))

        await queue.retry(id: queue.failed[0].id)
        await queue.flush(using: replay(server))

        XCTAssertEqual(server.tapRequests.map(\.entryDate), ["2026-10-26", nil])
        XCTAssertEqual(server.rowCount, 1)
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAPressSentTheSameDayIsAcceptedWithItsDay() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(tap(day: "2026-10-26"), label: "Вода")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.tapRequests.first?.entryDate, "2026-10-26")
        XCTAssertEqual(server.tapRequests.first?.source, "ios")
        XCTAssertEqual(server.tapRequests.first?.utcOffsetMinutes, 180)
        XCTAssertEqual(server.rowCount, 1)
    }

    func testAPressCarryingItsMomentIsSentWithItAndWithoutADay() async {
        let server = FakeOutboxServer()
        server.today = "2026-10-27"
        let queue = makeQueue()
        let pressed = Date(timeIntervalSince1970: 1_792_890_000) // 2026-10-25 01:00 UTC
        queue.enqueue(momentTap(at: pressed), label: "Вода")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.tapRequests.map(\.occurredAt), ["2026-10-25T01:00:00.000Z"])
        XCTAssertEqual(server.tapRequests.map(\.entryDate), [nil], "the server reads the day off the moment")
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAMomentTheServerWillNotTakeIsNotSentAndCanBeWrittenToToday() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(momentTap(at: Date(timeIntervalSince1970: 1_792_000_000)), label: "Вода")
        server.failures = [APIClientError.unexpectedStatus(422)]
        await queue.flush(using: replay(server))

        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.pressTimeRefusedReason)
        XCTAssertEqual(queue.failed.first?.retryTitle, OutboxWrite.retryTodayTitle)

        await queue.retry(id: queue.failed[0].id)
        await queue.flush(using: replay(server))
        XCTAssertEqual(server.tapRequests.last?.occurredAt, nil, "written to the server's today")
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAPressStoredBeforeTheMomentExistedStillReads() throws {
        let stored = Data(#"{"quickMarkId":3,"categoryId":1,"utcOffsetMinutes":180,"serverDay":"2026-10-26"}"#.utf8)

        let tap = try CacheCoding.decoder().decode(QueuedTap.self, from: stored)

        XCTAssertEqual(tap, QueuedTap(quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 180, serverDay: "2026-10-26"))
        XCTAssertNil(tap.occurredAt)
    }

    // MARK: Stale writes over fresher data

    func testANotebookChangedOnTheServerMeanwhileIsNotOverwritten() async {
        let server = FakeOutboxServer()
        server.notebooks["2026-10-26"] = "из веба"
        let queue = makeQueue()
        queue.enqueue(notebook("с телефона", expected: "утро"), label: "Блокнот")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.notebooks["2026-10-26"], "из веба")
        XCTAssertEqual(server.unopenedFetches, ["2026-10-26"], "the check does not mark the day as opened")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.notebookChangedReason)
        XCTAssertEqual(queue.failed.first?.retryTitle, OutboxWrite.retryOverwriteTitle)

        await queue.retry(id: queue.failed[0].id)
        await queue.flush(using: replay(server))
        XCTAssertEqual(server.notebooks["2026-10-26"], "с телефона", "the person chose to write over it")
    }

    func testANotebookThatAlreadyHoldsTheTextIsAcceptedAgain() async {
        let server = FakeOutboxServer()
        server.notebooks["2026-10-26"] = "с телефона"
        let queue = makeQueue()
        queue.enqueue(notebook("с телефона", expected: "утро"), label: "Блокнот")

        await queue.flush(using: replay(server))

        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAMarkChangedOnTheServerMeanwhileIsNotOverwritten() async {
        let server = FakeOutboxServer()
        server.marks["2026-10-26"] = [DayFixtures.taskID: "failed"]
        let queue = makeQueue()
        let mark = QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: "done", note: nil, expected: "")
        queue.enqueue(.setDayMark(mark), label: "Релиз")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.marks["2026-10-26"]?[DayFixtures.taskID], "failed")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.markChangedReason)
    }

    func testAMarkOverTheStateItWasMadeOnIsSent() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        let mark = QueuedDayMark(date: "2026-10-25", itemID: DayFixtures.taskID, state: "done", note: nil, expected: "")
        queue.enqueue(.setDayMark(mark), label: "Релиз")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.marks["2026-10-25"]?[DayFixtures.taskID], "done")
        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testAPlanFactReplaysUnderItsKeyWithItsBody() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        let body = PlanFactRequestDTO(
            values: [PlanFactValueRequestDTO(fieldId: 70, value: .number(30), unit: "раз")], mark: "done"
        )
        queue.enqueue(.recordPlanFact(QueuedPlanFact(date: "2026-10-25", itemID: DayFixtures.pushupsID, body: body)), key: "fact-1", label: "Отжимания")

        await queue.flush(using: replay(server))

        XCTAssertEqual(server.requests.map(\.key), ["fact-1"])
        XCTAssertEqual(server.factBodies, [body])
    }

    // MARK: Round 2: counters, checks, retry, key

    func testADeadNetworkBetweenServerErrorsStartsTheCountAgain() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        let blackouts = OutboxQueue.maxServerErrorAttempts - 1
        server.failures = Array(repeating: APIClientError.unexpectedStatus(502), count: blackouts)
            + [APIClientError.timeout]
            + Array(repeating: APIClientError.unexpectedStatus(502), count: blackouts)

        for _ in 0..<(2 * blackouts + 1) {
            await queue.flush(using: replay(server))
        }

        XCTAssertEqual(queue.pendingCount, 1, "never five 5xx in a row: the write keeps waiting")
        XCTAssertEqual(queue.pending.first?.serverErrors, blackouts)
    }

    func testManyNetworkDropsThenOneServerErrorKeepTheWriteWaiting() async {
        let server = FakeOutboxServer()
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")
        server.failures = Array(repeating: APIClientError.timeout, count: OutboxQueue.maxServerErrorAttempts)
            + [APIClientError.unexpectedStatus(502)]

        for _ in 0...OutboxQueue.maxServerErrorAttempts {
            await queue.flush(using: replay(server))
        }

        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertEqual(queue.failedCount, 0)
    }

    func testAnUnreadableNotebookCheckRefusesTheReplayInsteadOfDroppingIt() async {
        let server = FakeOutboxServer()
        server.dayFetchError = APIClientError.invalidResponse
        let queue = makeQueue()
        queue.enqueue(notebook("с телефона", expected: "утро"), label: "Блокнот")

        await queue.flush(using: replay(server))

        XCTAssertNil(server.notebooks["2026-10-26"], "nothing was written")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.checkFailedReason)
        XCTAssertEqual(queue.failed.first?.retryTitle, OutboxWrite.retryOverwriteTitle)
    }

    func testAnUnreadableMarkCheckRefusesTheReplayInsteadOfDroppingIt() async {
        let server = FakeOutboxServer()
        server.dayFetchError = APIClientError.invalidResponse
        let queue = makeQueue()
        let mark = QueuedDayMark(date: "2026-10-26", itemID: DayFixtures.taskID, state: "done", note: nil, expected: "")
        queue.enqueue(.setDayMark(mark), label: "Релиз")

        await queue.flush(using: replay(server))

        XCTAssertNil(server.marks["2026-10-26"])
        XCTAssertEqual(queue.failed.map(\.label), ["Релиз"])
    }

    func testANetworkDropDuringTheCheckKeepsTheWriteWaiting() async {
        let server = FakeOutboxServer()
        server.dayFetchError = APIClientError.timeout
        let queue = makeQueue()
        queue.enqueue(notebook("с телефона", expected: "утро"), label: "Блокнот")

        await queue.flush(using: replay(server))

        XCTAssertEqual(queue.pendingCount, 1)
    }

    func testAnUnreadableAnswerOfTheWriteItselfCountsAsDelivered() async {
        let server = FakeOutboxServer()
        server.failures = [APIClientError.invalidResponse]
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")

        await queue.flush(using: replay(server))

        XCTAssertTrue(queue.writes.isEmpty)
    }

    func testARefusedPressWithoutADayIsNotCalledADayTurn() async {
        let server = FakeOutboxServer()
        server.failures = [APIClientError.unexpectedStatus(409)]
        let queue = makeQueue()
        queue.enqueue(tap(day: nil), label: "Вода")

        await queue.flush(using: replay(server))

        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.tapRefusedReason)
        XCTAssertEqual(queue.failed.first?.retryTitle, OutboxWrite.retryTitle)
    }

    func testRetrySendsAtOnce() async {
        let server = FakeOutboxServer()
        server.failures = [APIClientError.unexpectedStatus(422)]
        let queue = makeQueue(server: server)
        queue.enqueue(entry("1"), label: "a")
        await queue.flush()

        await queue.retry(id: queue.failed[0].id)

        XCTAssertTrue(queue.writes.isEmpty)
        XCTAssertEqual(server.rowCount, 1)
    }

    func testARefusedKeyIsSaidUntilAWriteGoesThrough() async {
        let server = FakeOutboxServer()
        server.failures = [APIClientError.unauthorized]
        let queue = makeQueue()
        queue.enqueue(entry("1"), label: "a")

        await queue.flush(using: replay(server))
        XCTAssertTrue(queue.waitsForKey)
        XCTAssertTrue(
            OutboxQueueBar.caption(pending: 1, failed: 0, waitsForKey: true).contains(OutboxQueueBar.keyRefusedCaption)
        )

        await queue.flush(using: replay(server))
        XCTAssertFalse(queue.waitsForKey)
    }

    func testTheOldQueuesAreImportedOnlyOnce() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("legacy-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let suite = "outbox-import-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let tapFile = directory.appendingPathComponent(OutboxLegacyImport.tapFileName)
        let legacy = Data(#"[{"id":"\#(UUID().uuidString)","quickMarkId":3,"categoryId":1,"createdAt":10,"utcOffsetMinutes":0,"attempts":0}]"#.utf8)
        let emptyStore = { () throws -> ModelContext in
            ModelContext(try ModelContainer(for: PendingEntryRecord.self, configurations: ModelConfiguration(isStoredInMemoryOnly: true)))
        }
        let queue = makeQueue()

        try legacy.write(to: tapFile)
        OutboxLegacyImport.runOnce(directory: directory, into: queue, defaults: defaults, oldEntries: emptyStore)
        try legacy.write(to: tapFile)
        OutboxLegacyImport.runOnce(directory: directory, into: queue, defaults: defaults, oldEntries: emptyStore)

        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: tapFile.path), "the second run does not touch the files")
    }

    // MARK: Old queues

    func testTheOldTapFileIsImportedOnceUnderTheTapsOwnKeys() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("taps-\(UUID().uuidString).json")
        let key = UUID()
        let legacy = """
        [{"id":"\(key.uuidString)","quickMarkId":3,"categoryId":1,"createdAt":10,"utcOffsetMinutes":180,"attempts":1}]
        """
        try Data(legacy.utf8).write(to: url)
        let queue = makeQueue()

        OutboxLegacyImport.importTaps(from: url, into: queue)

        XCTAssertEqual(queue.pending.map(\.key), [key.uuidString])
        XCTAssertEqual(
            queue.pending.first?.action,
            .tapQuickMark(QueuedTap(quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 180, serverDay: nil))
        )
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path), "imported once")
    }

    func testTheOldEntryQueueIsImportedUnderItsOwnKeys() throws {
        let container = try ModelContainer(
            for: PendingEntryRecord.self, configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let context = ModelContext(container)
        let id = UUID()
        let payload = EntryCreateDTO(categoryId: 1, entryDate: "2026-10-20", notes: nil, values: [])
        context.insert(
            PendingEntryRecord(
                id: id, payload: try CacheCoding.encoder().encode(payload), createdAt: Date(timeIntervalSince1970: 5),
                attempts: 2, statusRaw: "pending"
            )
        )
        try context.save()
        let queue = makeQueue()

        OutboxLegacyImport.importEntries(from: context, into: queue)

        XCTAssertEqual(queue.pending.map(\.key), [id.uuidString])
        XCTAssertEqual(queue.pending.first?.action, .createEntry(payload))
        XCTAssertTrue(try context.fetch(FetchDescriptor<PendingEntryRecord>()).isEmpty)
    }

    private static func removeStore(at url: URL) {
        for suffix in ["", "-shm", "-wal"] {
            try? FileManager.default.removeItem(at: URL(fileURLWithPath: url.path + suffix))
        }
    }
}
