// [review:need-review] PHASE-03/241
// summary: one poller for every part of the floating panel that is read from the server — keeps the last good answer through outages, asks with the last ETag, retries on the shared Backoff and says when it has been silent longer than its threshold; since #241 every poll has a number in the order it was started, so a caller can tell whether a poll began after some moment, and an answer that lands after a later poll's answer is not painted over it
import Foundation

enum PollResponse<Value: Equatable>: Equatable {
    case modified(Value, etag: String?)
    /// 304: what the poller already holds is still current.
    case notModified
}

/// Polls one resource and keeps the last answer that arrived.
///
/// A failed poll changes nothing the window shows except `isStale`: the value
/// stays, because for the config silence is cheap (the last task is still
/// probably the task) and for a part that must not lie the caller reads
/// `isStale` and says so. Retries after a failure follow the shared `Backoff`
/// with a lower ceiling than the queue's, so that coming back online is noticed
/// within a minute instead of within ten.
@MainActor
final class ConditionalPoller<Value: Equatable>: ObservableObject {
    typealias Fetch = (_ etag: String?) async throws -> PollResponse<Value>
    typealias Sleep = (TimeInterval) async throws -> Void

    @Published private(set) var value: Value?
    /// The error of the last poll, nil after a success.
    @Published private(set) var lastFailure: Error?
    private(set) var lastSuccessAt: Date?
    /// Polls started so far. A poll numbered above the value read at some moment began after that moment.
    private(set) var pollsStarted = 0
    /// The number of the newest poll that succeeded (a 304 counts), 0 before the first.
    @Published private(set) var lastSuccessfulPoll = 0
    /// How long `run()` waits before the next poll.
    private(set) var nextDelay: TimeInterval

    let interval: TimeInterval
    let staleAfter: TimeInterval

    private var backoff: Backoff
    private var etag: String?
    private let startedAt: Date
    private let now: () -> Date
    private let fetch: Fetch
    private let sleep: Sleep

    init(
        interval: TimeInterval,
        staleAfter: TimeInterval,
        maxRetryDelay: TimeInterval,
        now: @escaping () -> Date = Date.init,
        sleep: @escaping Sleep = { try await Task.sleep(nanoseconds: UInt64($0 * 1_000_000_000)) },
        fetch: @escaping Fetch
    ) {
        self.interval = interval
        self.staleAfter = staleAfter
        self.now = now
        self.sleep = sleep
        self.fetch = fetch
        startedAt = now()
        nextDelay = interval
        // The first retry comes after one regular interval, then it doubles up to the ceiling.
        backoff = Backoff(initialDelay: interval, maxDelay: maxRetryDelay)
    }

    /// True when no poll has succeeded for longer than `staleAfter`. Before the
    /// first success the clock runs from the start of the poller.
    func isStale(at date: Date) -> Bool {
        date.timeIntervalSince(lastSuccessAt ?? startedAt) > staleAfter
    }

    func pollOnce() async {
        pollsStarted += 1
        let number = pollsStarted
        do {
            switch try await fetch(etag) {
            case let .modified(newValue, newEtag):
                // Polls can overlap (the loop and a poll after a write): the older answer must not repaint the newer one.
                if number > lastSuccessfulPoll {
                    value = newValue
                    etag = newEtag
                }
            case .notModified:
                break
            }
            lastSuccessfulPoll = max(lastSuccessfulPoll, number)
            lastSuccessAt = now()
            lastFailure = nil
            backoff.reset()
            nextDelay = interval
        } catch is CancellationError {
            return
        } catch let error as URLError where error.code == .cancelled {
            return
        } catch {
            lastFailure = error
            nextDelay = backoff.recordFailure()
        }
    }

    /// Polls until the task is cancelled.
    func run() async {
        while !Task.isCancelled {
            await pollOnce()
            do {
                try await sleep(nextDelay)
            } catch {
                return
            }
        }
    }
}
