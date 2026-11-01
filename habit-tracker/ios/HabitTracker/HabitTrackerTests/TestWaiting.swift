// [review:need-review] PHASE-03/242
// summary: one helper for tests that wait on the main actor for a condition another task brings about; a condition that never holds fails the test instead of passing silently
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 — `waitForSend`: waits for the queue's background send to settle every waiting write
import XCTest
@testable import HabitTracker

/// Waits on the main actor until `condition` holds, for at most about two seconds; fails the test when
/// it never does.
@MainActor
func waitUntil(
    _ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line
) async {
    for _ in 0..<200 where !condition() {
        try? await Task.sleep(nanoseconds: 10_000_000)
    }
    if !condition() { XCTFail("the condition did not hold within the wait", file: file, line: line) }
}

/// Waits until the queue's background send has settled every waiting write — delivered, refused, or
/// failed once. A write that waits behind one that failed is never tried, so do not use it then.
@MainActor
func waitForSend(_ queue: OutboxQueue, file: StaticString = #filePath, line: UInt = #line) async {
    await waitUntil({ queue.pending.allSatisfy { $0.attemptFailed } }, file: file, line: line)
}
