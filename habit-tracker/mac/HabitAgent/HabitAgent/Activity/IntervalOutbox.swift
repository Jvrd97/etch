// [review:approved] PHASE-03/155
// summary: holds closed intervals until the server confirms them; one send at a time, backoff while the server is unreachable, apps the catalogue refused are dropped
import Foundation

struct FlushSummary: Equatable {
    var sent = 0
    var droppedBundles: [String] = []
    var droppedInvalid = 0
    var failed = false
}

@MainActor
final class IntervalOutbox {
    typealias Sender = @MainActor ([ActivityInterval]) async throws -> Void

    /// Closed intervals that trigger a send from the sampling tick.
    static let flushThreshold = 25
    /// The server's cap on one batch (`MAX_BATCH_INTERVALS`).
    static let maxBatch = 500
    static let initialRetryDelay: TimeInterval = 30
    static let maxRetryDelay: TimeInterval = 600

    private(set) var pending: [ActivityInterval] = []
    private var excludedBundles: Set<String>
    private var inFlight: Task<FlushSummary, Never>?
    private var retryDelay = IntervalOutbox.initialRetryDelay
    private var notBefore = Date.distantPast

    init(excluding bundles: Set<String>) {
        excludedBundles = bundles
    }

    func enqueue(_ intervals: [ActivityInterval]) {
        pending += intervals.filter { !excludedBundles.contains($0.bundleID) }
    }

    /// Sends what is pending, never two requests at once.
    ///
    /// A regular flush (`force == false`) runs only past the threshold and the
    /// backoff, and gives way to a send already in flight. A forced flush waits
    /// for that send and then tries everything pending regardless of backoff.
    /// Returns nil when nothing was attempted.
    @discardableResult
    func flush(force: Bool, now: Date = Date(), send: @escaping Sender) async -> FlushSummary? {
        if force {
            while let running = inFlight { _ = await running.value }
        } else if inFlight != nil {
            return nil
        }
        guard !pending.isEmpty else { return nil }
        if !force {
            guard pending.count >= Self.flushThreshold, now >= notBefore else { return nil }
        }
        let task = Task { await drain(force: force, now: now, send: send) }
        inFlight = task
        return await task.value
    }

    private func drain(force: Bool, now: Date, send: Sender) async -> FlushSummary {
        defer { inFlight = nil }
        var summary = FlushSummary()
        while !pending.isEmpty, force || pending.count >= Self.flushThreshold {
            // Only this task removes from the front, so the snapshot is still
            // the head of `pending` when the answer comes back.
            let batch = Array(pending.prefix(Self.maxBatch))
            do {
                try await send(batch)
                pending.removeFirst(batch.count)
                summary.sent += batch.count
                retryDelay = Self.initialRetryDelay
            } catch AgentAPIError.unknownApp(let bundleID) {
                excludedBundles.insert(bundleID)
                pending.removeAll { $0.bundleID == bundleID }
                summary.droppedBundles.append(bundleID)
            } catch AgentAPIError.invalidBatch {
                pending.removeFirst(batch.count)
                summary.droppedInvalid += batch.count
            } catch {
                notBefore = now.addingTimeInterval(retryDelay)
                retryDelay = min(retryDelay * 2, Self.maxRetryDelay)
                summary.failed = true
                return summary
            }
        }
        return summary
    }
}
