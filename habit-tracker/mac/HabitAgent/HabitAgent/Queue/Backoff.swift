// [review:need-review] PHASE-03/163
// summary: exponential retry delay with a ceiling, so a dead server is asked a few times an hour rather than every second
import Foundation

struct Backoff: Equatable {
    static let initialDelay: TimeInterval = 30
    static let maxDelay: TimeInterval = 600

    private let firstDelay: TimeInterval
    private let ceiling: TimeInterval
    private var failures = 0

    init(initialDelay: TimeInterval = Backoff.initialDelay, maxDelay: TimeInterval = Backoff.maxDelay) {
        precondition(initialDelay > 0 && maxDelay >= initialDelay, "Backoff needs 0 < initialDelay <= maxDelay")
        firstDelay = initialDelay
        ceiling = maxDelay
    }

    /// Counts one more failure in a row and returns how long to wait before the next attempt.
    mutating func recordFailure() -> TimeInterval {
        let delay = min(firstDelay * pow(2, Double(failures)), ceiling)
        failures += 1
        return delay
    }

    mutating func reset() {
        failures = 0
    }
}
