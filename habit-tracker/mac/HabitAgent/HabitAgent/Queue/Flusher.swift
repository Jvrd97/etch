// [review:need-review] PHASE-03/163
// summary: sends the disk queue to the server one batch at a time — on start, on a timer, when an interval closes and when the network comes back; backs off while the server is down, drops by retention, and narrows a refused batch down to the one refused interval
import Foundation
import Network
import os

struct FlushSummary: Equatable {
    var sent = 0
    var droppedBundles: [String] = []
    var droppedInvalid = 0
    var expired = 0
    var failed = false
    /// The server refused single intervals in a row, so the queue was left alone and the pass ended.
    var serverRefuses = false
}

/// The server turned down `Flusher.maxLoneRefusals` single intervals without taking anything between them.
private struct RefusalStreak: Error {}

@MainActor
final class Flusher {
    typealias Sender = @MainActor ([ActivityInterval]) async throws -> Void

    /// How often a pending queue is tried again when no interval closes and the network does not change.
    static let timerInterval: TimeInterval = 30
    /// Single intervals the server may refuse in a row, with no send accepted between them, before the
    /// pass stops. One bad line is dropped; a server that refuses everything (versions out of step)
    /// must not eat the queue, so it costs fewer than this many intervals until a send is accepted.
    static let maxLoneRefusals = 3

    private static let logger = Logger(subsystem: AgentPaths.identifier, category: "Flusher")

    private let store: OutboxStore
    /// Nil while the agent has no server address or key: the queue then only grows.
    private let sender: @MainActor () -> Sender?
    private let onFlush: @MainActor (FlushSummary) -> Void
    private var backoff = Backoff()
    private var loneRefusals = 0
    private var networkAvailable = true
    private var inFlight: Task<FlushSummary, Never>?
    private var timer: Task<Void, Never>?
    private var monitor: NWPathMonitor?

    /// The earliest moment a regular flush may try again after a failure.
    private(set) var retryNotBefore = Date.distantPast

    init(
        store: OutboxStore,
        sender: @escaping @MainActor () -> Sender?,
        onFlush: @escaping @MainActor (FlushSummary) -> Void = { _ in }
    ) {
        self.store = store
        self.sender = sender
        self.onFlush = onFlush
    }

    /// Flushes now, then on a timer and whenever the network path comes back.
    func start() {
        guard timer == nil else { return }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { [weak self] path in
            let available = path.status == .satisfied
            Task { @MainActor in await self?.networkChanged(available: available) }
        }
        monitor.start(queue: DispatchQueue(label: "\(AgentPaths.identifier).network"))
        self.monitor = monitor
        timer = Task { [weak self] in
            while !Task.isCancelled {
                await self?.flush()
                try? await Task.sleep(for: .seconds(Self.timerInterval))
            }
        }
    }

    func stop() {
        timer?.cancel()
        timer = nil
        monitor?.cancel()
        monitor = nil
    }

    /// An interval was closed and queued: try to send it, unless the backoff says to wait.
    func intervalClosed() {
        Task { await flush() }
    }

    /// A network that returns says the server may be reachable again, so the wait is cancelled.
    func networkChanged(available: Bool) async {
        let restored = available && !networkAvailable
        networkAvailable = available
        guard restored else { return }
        Self.logger.info("Network is back, flushing without waiting")
        backoff.reset()
        retryNotBefore = .distantPast
        await flush(force: true)
    }

    /// Sends the queue, never two requests at once.
    ///
    /// A regular flush (`force == false`) runs only past the backoff and gives way
    /// to a send already in flight. A forced flush waits for that send and then
    /// tries regardless of the backoff. Neither tries while the network is down.
    /// Returns nil when nothing was attempted and nothing was dropped.
    @discardableResult
    func flush(force: Bool = false, now: Date = Date()) async -> FlushSummary? {
        if force {
            while let running = inFlight { _ = await running.value }
        } else if inFlight != nil {
            return nil
        }
        let expired = store.dropExpired(now: now)
        var summary = FlushSummary(expired: expired)
        if let send = attemptableSender(force: force, now: now) {
            let task = Task { await drain(send: send, now: now, expired: expired) }
            inFlight = task
            summary = await task.value
        }
        guard summary != FlushSummary() else { return nil }
        onFlush(summary)
        return summary
    }

    private func attemptableSender(force: Bool, now: Date) -> Sender? {
        guard networkAvailable, force || now >= retryNotBefore, store.count > 0 else { return nil }
        return sender()
    }

    private func drain(send: Sender, now: Date, expired: Int) async -> FlushSummary {
        defer { inFlight = nil }
        var summary = FlushSummary(expired: expired)
        // Only this task removes from the queue, so the batch read is still the head when the answer comes back.
        while let batch = store.nextBatch() {
            do {
                try await deliver(batch, send: send, now: now, summary: &summary)
            } catch AgentAPIError.unknownApp(let bundleID) {
                store.drop(bundleID: bundleID, at: now)
                summary.droppedBundles.append(bundleID)
            } catch {
                let delay = backoff.recordFailure()
                retryNotBefore = now.addingTimeInterval(delay)
                summary.failed = true
                summary.serverRefuses = error is RefusalStreak
                Self.logger.notice(
                    "Send failed (\(Self.describe(error), privacy: .public)), \(self.store.count) queued, next try in \(Int(delay)) s"
                )
                return summary
            }
        }
        return summary
    }

    /// Sends `batch` and removes it once the server took it.
    ///
    /// The server takes a batch whole or refuses it whole, so one bad interval would
    /// block the other 499. A refused batch is halved until the refused interval
    /// stands alone; only that interval is dropped.
    private func deliver(_ batch: OutboxStore.Batch, send: Sender, now: Date, summary: inout FlushSummary) async throws {
        do {
            try await send(batch.intervals)
        } catch AgentAPIError.invalidBatch {
            guard batch.ids.count > 1 else {
                loneRefusals += 1
                guard loneRefusals < Self.maxLoneRefusals else { throw RefusalStreak() }
                store.drop(batch, at: now)
                summary.droppedInvalid += 1
                return
            }
            let (head, tail) = batch.halves
            try await deliver(head, send: send, now: now, summary: &summary)
            try await deliver(tail, send: send, now: now, summary: &summary)
            return
        }
        store.remove(batch)
        summary.sent += batch.intervals.count
        backoff.reset()
        loneRefusals = 0
    }

    private static func describe(_ error: Error) -> String {
        if let urlError = error as? URLError { return "URLError \(urlError.code.rawValue)" }
        if case AgentAPIError.http(let status) = error { return "HTTP \(status)" }
        if error is RefusalStreak { return "server refuses single intervals" }
        return String(describing: type(of: error))
    }
}
