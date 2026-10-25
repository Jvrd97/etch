// [review:need-review] PHASE-01/210
// summary: tests for the offline queue of quick-mark taps — durable across a relaunch, replayed in order under the tap's own Idempotency-Key, stops on a dead network or a rejected key, drops a tap the server refuses for good without blocking the ones behind it; also the scriptable QuickMarksAPI double shared with the view model tests
import Combine
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the quick-mark endpoints.
final class MockQuickMarksAPI: QuickMarksAPI {
    var marksResult: Result<[QuickMarkDTO], Error> = .success([])
    /// Consumed one per tap; an empty script answers `invalidResponse`.
    var tapResults: [Result<QuickMarkEventDTO, Error>] = []
    var undoResult: Result<QuickMarkUndoDTO, Error> = .failure(APIClientError.invalidResponse)
    var dayEventsResult: Result<[QuickMarkDayEventDTO], Error> = .success([])
    private(set) var taps: [(id: Int, request: QuickMarkEventRequestDTO, key: String)] = []
    private(set) var undoneIDs: [Int] = []
    private(set) var fetchedDayEventCategories: [Int] = []
    private(set) var directoryFetches = 0

    func fetchQuickMarks() async throws -> [QuickMarkDTO] {
        directoryFetches += 1
        return try marksResult.get()
    }

    func tapQuickMark(
        id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String
    ) async throws -> QuickMarkEventDTO {
        taps.append((id: id, request: request, key: idempotencyKey))
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
final class QuickMarkTapQueueTests: XCTestCase {
    private func makeQueue(store: TapStore = InMemoryTapStore()) -> QuickMarkTapQueue {
        QuickMarkTapQueue(store: store, now: { Date(timeIntervalSince1970: 1_000) })
    }

    func testEnqueueSurvivesARelaunchBecauseTheStoreIsDurable() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("taps-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let key = UUID()

        makeQueue(store: FileTapStore(url: url))
            .enqueue(key: key, quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 180)
        let relaunched = makeQueue(store: FileTapStore(url: url))

        XCTAssertEqual(relaunched.pendingCount, 1)
        XCTAssertEqual(relaunched.pending.first?.id, key)
        XCTAssertEqual(relaunched.pending.first?.quickMarkId, 3)
        XCTAssertEqual(relaunched.pending.first?.utcOffsetMinutes, 180)
    }

    func testFlushReplaysInOrderUnderTheTapsOwnKeyAndEmptiesTheQueue() async {
        let queue = makeQueue()
        let first = UUID()
        let second = UUID()
        queue.enqueue(key: first, quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 0)
        queue.enqueue(key: second, quickMarkId: 4, categoryId: 2, utcOffsetMinutes: 0)
        let api = MockQuickMarksAPI()
        api.tapResults = [
            .success(.stub(eventId: 1, markId: 3, total: 1)),
            .success(.stub(eventId: 2, markId: 4)),
        ]

        let flushed = await queue.flush(using: api)

        XCTAssertEqual(api.taps.map(\.id), [3, 4])
        XCTAssertEqual(api.taps.map(\.key), [first.uuidString, second.uuidString])
        XCTAssertNil(
            api.taps[0].request.entryDate,
            "a replay must not pin the day: it is the server's to decide, and a 409 would lose the tap"
        )
        XCTAssertEqual(api.taps[0].request.source, "ios")
        XCTAssertEqual(flushed.map(\.tap.categoryId), [1, 2])
        XCTAssertEqual(queue.pendingCount, 0)
    }

    func testADeadNetworkStopsTheFlushAndKeepsEveryTap() async {
        let queue = makeQueue()
        queue.enqueue(key: UUID(), quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 0)
        queue.enqueue(key: UUID(), quickMarkId: 4, categoryId: 2, utcOffsetMinutes: 0)
        let api = MockQuickMarksAPI()
        api.tapResults = [.failure(APIClientError.timeout)]

        let flushed = await queue.flush(using: api)

        XCTAssertTrue(flushed.isEmpty)
        XCTAssertEqual(api.taps.count, 1, "order is kept: nothing is sent behind a tap that failed")
        XCTAssertEqual(queue.pendingCount, 2)
    }

    func testARejectedKeyStopsTheFlushAndKeepsTheTaps() async {
        let queue = makeQueue()
        queue.enqueue(key: UUID(), quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 0)
        let api = MockQuickMarksAPI()
        api.tapResults = [.failure(APIClientError.unauthorized)]

        _ = await queue.flush(using: api)

        XCTAssertEqual(queue.pendingCount, 1, "fixing the key in Settings must not cost the taps")
        XCTAssertEqual(queue.rejectedCount, 0)
    }

    func testATapTheServerRefusesForGoodIsDroppedWithoutBlockingTheOnesBehindIt() async {
        let queue = makeQueue()
        queue.enqueue(key: UUID(), quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 0)
        queue.enqueue(key: UUID(), quickMarkId: 4, categoryId: 2, utcOffsetMinutes: 0)
        let api = MockQuickMarksAPI()
        api.tapResults = [
            .failure(APIClientError.unexpectedStatus(409)),
            .success(.stub(eventId: 2, markId: 4)),
        ]

        let flushed = await queue.flush(using: api)

        XCTAssertEqual(flushed.map(\.tap.quickMarkId), [4])
        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(queue.rejectedCount, 1)
    }

    func testAServerErrorIsRetriedUntilTheAttemptBudgetIsSpent() async {
        let queue = makeQueue()
        queue.enqueue(key: UUID(), quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 0)
        let api = MockQuickMarksAPI()
        api.tapResults = Array(
            repeating: .failure(APIClientError.unexpectedStatus(500)),
            count: QuickMarkTapQueue.maxAttempts
        )

        for _ in 0..<(QuickMarkTapQueue.maxAttempts - 1) {
            _ = await queue.flush(using: api)
            XCTAssertEqual(queue.pendingCount, 1)
        }
        _ = await queue.flush(using: api)

        XCTAssertEqual(queue.pendingCount, 0)
        XCTAssertEqual(queue.rejectedCount, 1)
    }

    func testOnlyAFlushThatDeliveredSomethingAnnouncesItself() async {
        let queue = makeQueue()
        var announced: [[Int]] = []
        let subscription = queue.flushCompleted.sink { announced.append($0) }
        queue.enqueue(key: UUID(), quickMarkId: 3, categoryId: 1, utcOffsetMinutes: 0)
        queue.enqueue(key: UUID(), quickMarkId: 4, categoryId: 2, utcOffsetMinutes: 0)
        let api = MockQuickMarksAPI()
        api.tapResults = [.failure(APIClientError.timeout)]
        _ = await queue.flush(using: api)
        XCTAssertTrue(announced.isEmpty)

        api.tapResults = [.success(.stub(markId: 3)), .success(.stub(eventId: 2, markId: 4))]
        _ = await queue.flush(using: api)

        XCTAssertEqual(announced, [[1, 2]])
        subscription.cancel()
    }
}
