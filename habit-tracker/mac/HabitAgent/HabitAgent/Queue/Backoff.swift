// [review:need-review] PHASE-03/163
// summary: exponential retry delay with a ceiling, so a dead server is asked a few times an hour rather than every second
import Foundation

struct Backoff: Equatable {
    static let initialDelay: TimeInterval = 30
    static let maxDelay: TimeInterval = 600

    private var failures = 0

    /// Counts one more failure in a row and returns how long to wait before the next attempt.
    mutating func recordFailure() -> TimeInterval {
        let delay = min(Self.initialDelay * pow(2, Double(failures)), Self.maxDelay)
        failures += 1
        return delay
    }

    mutating func reset() {
        failures = 0
    }
}
