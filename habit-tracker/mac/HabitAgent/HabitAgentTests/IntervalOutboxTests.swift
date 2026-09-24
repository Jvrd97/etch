// [review:approved] PHASE-03/155
// summary: verifies one send at a time, removal of only confirmed intervals, dropping apps the catalogue refused and backoff while the server is down
import XCTest
@testable import HabitAgent

@MainActor
private final class Gate {
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var isOpen = false

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters = []
    }
}

@MainActor
final class IntervalOutboxTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)

    private func intervals(_ count: Int, bundleID: String = "com.example.editor", from offset: Int = 0) -> [ActivityInterval] {
        (offset..<offset + count).map { index in
            ActivityInterval(
                bundleID: bundleID,
                startedAt: start.addingTimeInterval(TimeInterval(index * 10)),
                endedAt: start.addingTimeInterval(TimeInterval(index * 10 + 5)),
                localDate: "2027-01-15",
                utcOffsetMinutes: 0,
                switchCount: 0
            )
        }
    }

    func testFlushWhileAnotherIsInFlightSendsNothingAndKeepsLaterIntervals() async {
        let outbox = IntervalOutbox(excluding: [])
        let first = intervals(IntervalOutbox.flushThreshold)
        outbox.enqueue(first)
        let gate = Gate()
        var batches: [[ActivityInterval]] = []
        // Only the first send is held open; a second one would return at once
        // and break the assertions instead of hanging the suite.
        let send: IntervalOutbox.Sender = { batch in
            batches.append(batch)
            if batches.count == 1 { await gate.wait() }
        }

        let running = Task { await outbox.flush(force: false, send: send) }
        while batches.isEmpty { await Task.yield() }
        let later = intervals(IntervalOutbox.flushThreshold, from: IntervalOutbox.flushThreshold)
        outbox.enqueue(later)
        let concurrent = await outbox.flush(force: false, send: send)
        XCTAssertNil(concurrent)
        XCTAssertEqual(batches.count, 1)

        gate.open()
        let summary = await running.value
        XCTAssertEqual(batches.first, first)
        // Every interval is either confirmed exactly once or still pending — none lost, none twice.
        XCTAssertEqual(batches.flatMap { $0 } + outbox.pending, first + later)
        XCTAssertEqual(summary?.sent, batches.flatMap { $0 }.count)
    }

    func testForcedFlushWaitsForTheSendInFlightInsteadOfDuplicatingIt() async {
        let outbox = IntervalOutbox(excluding: [])
        outbox.enqueue(intervals(IntervalOutbox.flushThreshold))
        let gate = Gate()
        var batches: [[ActivityInterval]] = []
        // Only the first send is held open; a second one would return at once
        // and break the assertions instead of hanging the suite.
        let send: IntervalOutbox.Sender = { batch in
            batches.append(batch)
            if batches.count == 1 { await gate.wait() }
        }

        let running = Task { await outbox.flush(force: false, send: send) }
        while batches.isEmpty { await Task.yield() }
        outbox.enqueue(intervals(1, from: IntervalOutbox.flushThreshold))
        let forced = Task { await outbox.flush(force: true, send: send) }
        await Task.yield()
        XCTAssertEqual(batches.count, 1)

        gate.open()
        _ = await running.value
        _ = await forced.value
        XCTAssertEqual(batches.map(\.count), [IntervalOutbox.flushThreshold, 1])
        XCTAssertTrue(outbox.pending.isEmpty)
    }

    func testBatchIsCappedAtTheServerLimit() async {
        let outbox = IntervalOutbox(excluding: [])
        outbox.enqueue(intervals(IntervalOutbox.maxBatch + 1))
        var sizes: [Int] = []
        await outbox.flush(force: true) { sizes.append($0.count) }
        XCTAssertEqual(sizes, [IntervalOutbox.maxBatch, 1])
        XCTAssertTrue(outbox.pending.isEmpty)
    }

    func testUnknownAppIsDroppedAndTheRestIsResent() async {
        let outbox = IntervalOutbox(excluding: [])
        let unknown = "com.apple.finder"
        outbox.enqueue(intervals(2) + intervals(1, bundleID: unknown, from: 2))
        var batches: [[ActivityInterval]] = []
        let summary = await outbox.flush(force: true) { batch in
            batches.append(batch)
            if batch.contains(where: { $0.bundleID == unknown }) {
                throw AgentAPIError.unknownApp(bundleID: unknown)
            }
        }
        XCTAssertEqual(summary?.droppedBundles, [unknown])
        XCTAssertEqual(summary?.sent, 2)
        XCTAssertEqual(batches.map(\.count), [3, 2])
        XCTAssertTrue(outbox.pending.isEmpty)

        outbox.enqueue(intervals(1, bundleID: unknown, from: 3))
        XCTAssertTrue(outbox.pending.isEmpty)
    }

    func testExcludedBundleNeverEntersTheQueue() {
        let own = "com.talvior.HabitAgent"
        let outbox = IntervalOutbox(excluding: [own])
        outbox.enqueue(intervals(1, bundleID: own) + intervals(1, from: 1))
        XCTAssertEqual(outbox.pending.map(\.bundleID), ["com.example.editor"])
    }

    func testBatchRefusedWithoutANamedAppIsDroppedInsteadOfRetriedForever() async {
        let outbox = IntervalOutbox(excluding: [])
        outbox.enqueue(intervals(3))
        var calls = 0
        let summary = await outbox.flush(force: true) { _ in
            calls += 1
            throw AgentAPIError.invalidBatch
        }
        XCTAssertEqual(calls, 1)
        XCTAssertEqual(summary?.droppedInvalid, 3)
        XCTAssertTrue(outbox.pending.isEmpty)
    }

    func testUnreachableServerIsRetriedAfterBackoffNotOnEveryTick() async {
        let outbox = IntervalOutbox(excluding: [])
        outbox.enqueue(intervals(IntervalOutbox.flushThreshold))
        var calls = 0
        var reachable = false
        let send: IntervalOutbox.Sender = { _ in
            calls += 1
            if !reachable { throw URLError(.cannotConnectToHost) }
        }

        let failed = await outbox.flush(force: false, now: start, send: send)
        XCTAssertEqual(failed?.failed, true)
        XCTAssertEqual(outbox.pending.count, IntervalOutbox.flushThreshold)

        let nextTick = start.addingTimeInterval(ActivitySampler.samplingInterval)
        let skipped = await outbox.flush(force: false, now: nextTick, send: send)
        XCTAssertNil(skipped)
        XCTAssertEqual(calls, 1)

        reachable = true
        let afterBackoff = start.addingTimeInterval(IntervalOutbox.initialRetryDelay)
        let sent = await outbox.flush(force: false, now: afterBackoff, send: send)
        XCTAssertEqual(sent?.sent, IntervalOutbox.flushThreshold)
        XCTAssertEqual(calls, 2)
        XCTAssertTrue(outbox.pending.isEmpty)
    }
}
