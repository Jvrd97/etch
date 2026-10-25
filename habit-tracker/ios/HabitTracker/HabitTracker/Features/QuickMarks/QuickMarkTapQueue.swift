// [review:need-review] PHASE-01/210
// summary: durable offline queue of quick-mark taps — a tap that cannot reach the server is kept with its own Idempotency-Key and replayed in order when the network returns (a lost answer cannot double the day's sum); a tap the server refuses for good is dropped and counted so the screen can say so
import Combine
import Foundation
import os

/// One press waiting for the network. `id` is the Idempotency-Key of every attempt to send it.
struct PendingTap: Codable, Equatable, Identifiable {
    let id: UUID
    let quickMarkId: Int
    let categoryId: Int
    let createdAt: Date
    let utcOffsetMinutes: Int
    var attempts: Int
}

/// Durable list behind `QuickMarkTapQueue`: the whole list is read and written at once,
/// it is a dozen rows at most and the queue owns every policy.
protocol TapStore: AnyObject {
    func loadAll() -> [PendingTap]
    func saveAll(_ taps: [PendingTap])
}

final class InMemoryTapStore: TapStore {
    private var taps: [PendingTap] = []

    func loadAll() -> [PendingTap] { taps }
    func saveAll(_ taps: [PendingTap]) { self.taps = taps }
}

/// JSON file store: a press made in airplane mode is still queued after the app is killed.
final class FileTapStore: TapStore {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "FileTapStore")
    private let url: URL

    init(url: URL) {
        self.url = url
    }

    func loadAll() -> [PendingTap] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        do {
            return try CacheCoding.decoder().decode([PendingTap].self, from: data)
        } catch {
            // A queue that cannot be read is a lost press: say so in the log (no contents).
            Self.logger.error("Tap queue decode failed: \(String(describing: error))")
            return []
        }
    }

    func saveAll(_ taps: [PendingTap]) {
        do {
            try CacheCoding.encoder().encode(taps).write(to: url, options: .atomic)
        } catch {
            Self.logger.error("Tap queue write failed: \(String(describing: error))")
        }
    }
}

/// A queued press the server has accepted.
struct FlushedTap: Equatable {
    let tap: PendingTap
    let event: QuickMarkEventDTO
}

/// The offline outbox for quick-mark taps (the `OutboxQueue` of entry creates is a different
/// operation with a different payload, so taps get their own small queue). A press that fails on a
/// connectivity error is enqueued instead of lost; `flush` replays the queue in order, deleting a tap
/// only after the server accepts it.
///
/// A replay does not send `entry_date`: the day of a tap is the server's call, and a guard that
/// disagrees after midnight would turn a kept press into a 409 and lose it.
@MainActor
final class QuickMarkTapQueue: ObservableObject {
    /// Non-connectivity failures a tap survives before it is dropped as refused.
    static let maxAttempts = 5
    static let tapSource = "ios"

    @Published private(set) var pending: [PendingTap]
    /// Taps the server refused for good since the screen last asked. Read with `takeRejectedCount`.
    private(set) var rejectedCount = 0
    /// Categories whose day moved, announced after a flush that delivered at least one tap.
    let flushCompleted = PassthroughSubject<[Int], Never>()

    private let store: TapStore
    private let now: () -> Date
    private var isFlushing = false
    private var monitor: NetworkPathMonitoring?
    private var apiProvider: (() -> QuickMarksAPI?)?

    init(store: TapStore, now: @escaping () -> Date = Date.init) {
        self.store = store
        self.now = now
        self.pending = store.loadAll()
    }

    var pendingCount: Int { pending.count }

    /// Queues a press that could not be sent. `key` is the key of the attempt that failed, so a
    /// request that did reach the server but lost its answer is not recorded twice on replay.
    func enqueue(key: UUID, quickMarkId: Int, categoryId: Int, utcOffsetMinutes: Int) {
        pending.append(
            PendingTap(
                id: key, quickMarkId: quickMarkId, categoryId: categoryId, createdAt: now(),
                utcOffsetMinutes: utcOffsetMinutes, attempts: 0
            )
        )
        store.saveAll(pending)
    }

    func takeRejectedCount() -> Int {
        defer { rejectedCount = 0 }
        return rejectedCount
    }

    /// Replays the queue in order. Stops at the first connectivity error or a refused key (the
    /// rest wait for the next trigger and keep their order); drops a tap the server refuses for good
    /// (a deleted or switched-off button) so it cannot block the ones behind it. Concurrent flushes
    /// are coalesced.
    @discardableResult
    func flush(using api: QuickMarksAPI) async -> [FlushedTap] {
        guard !isFlushing else { return [] }
        isFlushing = true
        var delivered: [FlushedTap] = []

        for tap in pending {
            do {
                let event = try await api.tapQuickMark(
                    id: tap.quickMarkId,
                    request: QuickMarkEventRequestDTO(
                        value: nil, entryDate: nil, utcOffsetMinutes: tap.utcOffsetMinutes,
                        source: Self.tapSource
                    ),
                    idempotencyKey: tap.id.uuidString
                )
                remove(tap.id)
                delivered.append(FlushedTap(tap: tap, event: event))
            } catch let error as APIClientError where error.isConnectivity || error == .unauthorized {
                break
            } catch let error as APIClientError where Self.isRefusedForGood(error) {
                remove(tap.id)
                rejectedCount += 1
            } catch {
                if recordFailedAttempt(of: tap) { continue }
                break
            }
        }

        isFlushing = false
        if !delivered.isEmpty {
            flushCompleted.send(Array(Set(delivered.map(\.tap.categoryId))).sorted())
        }
        return delivered
    }

    /// Starts flushing on every reconnect (and on the monitor's first report at launch). The
    /// provider is evaluated per flush, so a new server address or key applies without a restart.
    func startAutoFlush(
        monitor: NetworkPathMonitoring, apiProvider: @escaping () -> QuickMarksAPI?
    ) {
        self.monitor = monitor
        self.apiProvider = apiProvider
        monitor.onBecameOnline { [weak self] in
            guard let self, let api = self.apiProvider?() else { return }
            await self.flush(using: api)
        }
        monitor.start()
    }

    /// 4xx other than "try again later" (408, 429) and "wrong key" (401): the button is gone,
    /// switched off, or the request is malformed, and a replay cannot change that.
    private static func isRefusedForGood(_ error: APIClientError) -> Bool {
        guard case .unexpectedStatus(let status) = error else { return false }
        return (400..<500).contains(status) && status != 408 && status != 429
    }

    /// Counts a failed attempt; drops the tap and reports it refused once the budget is spent.
    /// Returns true when the tap was dropped and the flush may go on to the next one.
    private func recordFailedAttempt(of tap: PendingTap) -> Bool {
        guard let index = pending.firstIndex(where: { $0.id == tap.id }) else { return true }
        pending[index].attempts += 1
        if pending[index].attempts >= Self.maxAttempts {
            pending.remove(at: index)
            rejectedCount += 1
            store.saveAll(pending)
            return true
        }
        store.saveAll(pending)
        return false
    }

    private func remove(_ id: UUID) {
        pending.removeAll { $0.id == id }
        store.saveAll(pending)
    }
}

/// The production queue: one file under Application Support, flushed off `NWPathMonitor`.
/// Falls back to memory when the file location is unavailable rather than failing at launch.
@MainActor
enum QuickMarkTapLive {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "QuickMarkTapLive")
    private static let fileName = "quick-mark-taps.json"

    static let shared: QuickMarkTapQueue = {
        let store: TapStore
        do {
            let directory = try FileManager.default.url(
                for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil,
                create: true
            )
            store = FileTapStore(url: directory.appendingPathComponent(fileName))
        } catch {
            logger.error("Tap queue file unavailable, using memory: \(String(describing: error))")
            store = InMemoryTapStore()
        }
        let queue = QuickMarkTapQueue(store: store)
        queue.startAutoFlush(monitor: NWPathNetworkMonitor(), apiProvider: { APIClient.live() })
        return queue
    }()
}
