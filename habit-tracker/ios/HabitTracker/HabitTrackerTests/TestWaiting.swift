// [review:need-review] PHASE-03/242
// summary: one helper for tests that wait on the main actor for a condition another task brings about; a condition that never holds fails the test instead of passing silently
import XCTest

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
