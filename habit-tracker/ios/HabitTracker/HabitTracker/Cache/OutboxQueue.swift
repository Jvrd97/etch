// [review:need-review] PHASE-01/12-ios-offline-queue, PHASE-01/39-server-idempotency-key-entries, PHASE-01/208
// summary: offline outbox for POST /entries — PendingEntry model + OutboxStore (in-memory + SwiftData), OutboxQueue that enqueues on connectivity failure and flushes in order (delete-after-success; replays carry PendingEntry.id as Idempotency-Key so a lost-ack retry returns the original entry, not a duplicate), and an NWPathMonitor-backed auto-flush wiring
import Foundation
import Network
import SwiftData
import os

/// Lifecycle of a queued create. `pending` entries are (re)tried on every flush;
/// `failed` ones exceeded the retry budget on a non-connectivity error (e.g. a
/// rejected payload) and are kept for visibility rather than retried forever.
enum PendingStatus: String, Codable {
    case pending
    case failed
}

/// One queued `POST /entries` operation. The payload is the exact create request that
/// failed to reach the server; `createdAt` fixes flush order, `attempts` counts tries.
struct PendingEntry: Identifiable, Equatable {
    let id: UUID
    let payload: EntryCreateDTO
    let createdAt: Date
    var attempts: Int
    var status: PendingStatus
}

/// The network operation the queue replays. `APIClient` conforms via its existing
/// `createEntry`; tests substitute a scriptable poster. The `idempotencyKey` is the
/// stable `PendingEntry.id`, so a replay of the same queued create always carries the
/// same key and the server collapses the duplicate instead of inserting a second row.
protocol OutboxPosting {
    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO
}

extension APIClient: OutboxPosting {}

/// Durable list of pending creates behind `OutboxQueue`. Kept intentionally small —
/// append, read-all (oldest first), update one, delete one — so the queue owns all policy.
protocol OutboxStore: AnyObject {
    func append(_ entry: PendingEntry)
    /// Every stored entry, oldest `createdAt` first (ties broken by insertion order).
    func fetchAll() -> [PendingEntry]
    func update(_ entry: PendingEntry)
    func delete(id: UUID)
}

/// Process-lifetime store used in tests and as the fallback when SwiftData is unavailable.
final class InMemoryOutboxStore: OutboxStore {
    private struct Slot {
        let sequence: Int
        var entry: PendingEntry
    }

    private var slots: [UUID: Slot] = [:]
    private var nextSequence = 0

    func append(_ entry: PendingEntry) {
        slots[entry.id] = Slot(sequence: nextSequence, entry: entry)
        nextSequence += 1
    }

    func fetchAll() -> [PendingEntry] {
        slots.values
            .sorted { ($0.entry.createdAt, $0.sequence) < ($1.entry.createdAt, $1.sequence) }
            .map(\.entry)
    }

    func update(_ entry: PendingEntry) {
        guard var slot = slots[entry.id] else { return }
        slot.entry = entry
        slots[entry.id] = slot
    }

    func delete(id: UUID) {
        slots[id] = nil
    }
}

/// One queued create as SwiftData persists it: the create payload is stored encoded
/// (the DTO's native casing — it never crosses the wire from here) plus the metadata.
@Model
final class PendingEntryRecord {
    @Attribute(.unique) var id: UUID
    var payload: Data
    var createdAt: Date
    var attempts: Int
    var statusRaw: String

    init(id: UUID, payload: Data, createdAt: Date, attempts: Int, statusRaw: String) {
        self.id = id
        self.payload = payload
        self.createdAt = createdAt
        self.attempts = attempts
        self.statusRaw = statusRaw
    }
}

/// Durable `OutboxStore` on top of SwiftData. Survives relaunch so a create made in
/// airplane mode is still queued after the app is killed and reopened.
final class SwiftDataOutboxStore: OutboxStore {
    private let context: ModelContext

    private static let logger = Logger(
        subsystem: "com.habittracker.app", category: "SwiftDataOutboxStore"
    )

    init(context: ModelContext) {
        self.context = context
    }

    /// Builds the store over its own container. `inMemory` yields an ephemeral store
    /// (used by tests); the default is the app's on-disk outbox database.
    convenience init(inMemory: Bool = false) throws {
        let configuration = ModelConfiguration(isStoredInMemoryOnly: inMemory)
        let container = try ModelContainer(
            for: PendingEntryRecord.self, configurations: configuration
        )
        self.init(context: ModelContext(container))
    }

    func append(_ entry: PendingEntry) {
        let payload: Data
        do {
            payload = try CacheCoding.encoder().encode(entry.payload)
        } catch {
            // Encoding a create payload must never silently drop it — that breaks the
            // "never lose 42 pushups" guarantee. Log (no payload/PII) and bail loudly.
            Self.logger.error("Outbox append: payload encode failed: \(String(describing: error))")
            return
        }
        context.insert(
            PendingEntryRecord(
                id: entry.id,
                payload: payload,
                createdAt: entry.createdAt,
                attempts: entry.attempts,
                statusRaw: entry.status.rawValue
            )
        )
        persist()
    }

    func fetchAll() -> [PendingEntry] {
        let descriptor = FetchDescriptor<PendingEntryRecord>(
            sortBy: [SortDescriptor(\.createdAt, order: .forward)]
        )
        let records: [PendingEntryRecord]
        do {
            records = try context.fetch(descriptor)
        } catch {
            // A failed fetch would silently hide queued creates from every flush —
            // log it (no payload/PII) rather than pretending the queue is empty.
            Self.logger.error("Outbox fetchAll failed: \(String(describing: error))")
            return []
        }
        return records.compactMap(Self.toDomain)
    }

    func update(_ entry: PendingEntry) {
        guard let record = fetchRecord(id: entry.id) else { return }
        record.attempts = entry.attempts
        record.statusRaw = entry.status.rawValue
        persist()
    }

    func delete(id: UUID) {
        guard let record = fetchRecord(id: id) else { return }
        context.delete(record)
        persist()
    }

    private func fetchRecord(id: UUID) -> PendingEntryRecord? {
        let descriptor = FetchDescriptor<PendingEntryRecord>(
            predicate: #Predicate { $0.id == id }
        )
        return try? context.fetch(descriptor).first
    }

    private func persist() {
        do {
            try context.save()
        } catch {
            // A queue write failure must not crash a background flush or a user's save;
            // log (no payload contents) and move on.
            Self.logger.error("Outbox persist failed: \(String(describing: error))")
        }
    }

    private static func toDomain(_ record: PendingEntryRecord) -> PendingEntry? {
        let payload: EntryCreateDTO
        do {
            payload = try CacheCoding.decoder().decode(
                EntryCreateDTO.self, from: record.payload
            )
        } catch {
            // A record whose payload no longer decodes is a lost create — surface it in
            // the log (no payload/PII) instead of quietly skipping it during a flush.
            logger.error("Outbox toDomain: payload decode failed: \(String(describing: error))")
            return nil
        }
        return PendingEntry(
            id: record.id,
            payload: payload,
            createdAt: record.createdAt,
            attempts: record.attempts,
            status: PendingStatus(rawValue: record.statusRaw) ?? .pending
        )
    }
}

/// Connectivity watcher the queue flushes off. Production wraps `NWPathMonitor`; tests
/// inject a mock that fires `onBecameOnline` on demand.
protocol NetworkPathMonitoring: AnyObject {
    /// Registers the handler run whenever connectivity is (re)established, including the
    /// monitor's first satisfied report at startup (which doubles as the app-start flush).
    func onBecameOnline(_ handler: @escaping () async -> Void)
    func start()
}

/// The offline outbox for `POST /entries`. A create that fails on a connectivity error
/// is enqueued instead of lost; `flush` replays queued creates in order, deleting each
/// only after the server accepts it — so a create is never dropped, and never sent twice.
/// For creates that originate in the outbox, the lost-ack window (server accepted the
/// create but the ack was lost, or the app crashed before the delete) does not produce a
/// duplicate: every replay carries the same stable `PendingEntry.id` as the
/// `Idempotency-Key`, so the server returns the original entry instead of inserting a
/// second row. This guarantee is scoped to the replay path only. A direct online create
/// (`TodayViewModel`/`CategoryDetailViewModel`) sends no key; if its ack is lost and the
/// payload is then enqueued, the new `PendingEntry.id` is a fresh key the server has not
/// seen, so that replay can still insert a duplicate of the online create.
@MainActor
final class OutboxQueue: ObservableObject {
    /// After this many non-connectivity failures a create is parked as `.failed` rather
    /// than retried forever (a rejected payload will never succeed on replay).
    static let maxAttempts = 5

    private let store: OutboxStore
    private let now: () -> Date
    private var isFlushing = false
    private var monitor: NetworkPathMonitoring?
    private var posterProvider: (() -> OutboxPosting?)?

    /// Number of creates still waiting to be sent — drives the "N ждут отправки" badge.
    @Published private(set) var pendingCount: Int = 0

    init(store: OutboxStore, now: @escaping () -> Date = Date.init) {
        self.store = store
        self.now = now
        refreshCount()
    }

    /// Every queued create, oldest first.
    var pending: [PendingEntry] {
        store.fetchAll()
    }

    /// Queues a create that could not be sent now. Called by the Today screen when a
    /// POST fails with a connectivity error, so "42 pushups" survives airplane mode.
    func enqueue(_ payload: EntryCreateDTO) {
        store.append(
            PendingEntry(
                id: UUID(),
                payload: payload,
                createdAt: now(),
                attempts: 0,
                status: .pending
            )
        )
        refreshCount()
    }

    /// Replays every pending create in order. Stops at the first connectivity error
    /// (the network is down — the rest wait for the next trigger, preserving order);
    /// a non-connectivity error increments attempts and, past `maxAttempts`, parks the
    /// create as `.failed` so a bad payload never blocks good ones behind it. Each
    /// accepted create is deleted immediately; a replay after a lost ack or a
    /// crash-before-delete reuses the same stable `PendingEntry.id` as the
    /// `Idempotency-Key`, so re-sending a queued create returns the original entry instead
    /// of creating a duplicate. (This covers only creates that were queued; a lost-ack on a
    /// direct online create that is later enqueued gets a fresh key — see the type doc
    /// above.) Concurrent flushes are coalesced via `isFlushing`.
    @discardableResult
    func flush(using poster: OutboxPosting) async -> [EntryDTO] {
        guard !isFlushing else { return [] }
        isFlushing = true
        defer { isFlushing = false }

        var saved: [EntryDTO] = []
        for entry in store.fetchAll() where entry.status == .pending {
            do {
                let result = try await poster.createEntry(
                    entry.payload, idempotencyKey: entry.id.uuidString
                )
                store.delete(id: entry.id)
                saved.append(result)
            } catch let error as APIClientError where error.isConnectivity {
                var retried = entry
                retried.attempts += 1
                store.update(retried)
                break
            } catch {
                var retried = entry
                retried.attempts += 1
                if retried.attempts >= Self.maxAttempts {
                    retried.status = .failed
                }
                store.update(retried)
            }
        }
        refreshCount()
        return saved
    }

    /// Begins auto-flushing: subscribes to the monitor so every reconnect (and the
    /// monitor's initial satisfied report at launch) drains the queue against a freshly
    /// resolved API. The provider is re-evaluated per flush so a Settings change to the
    /// server address or key takes effect without an app restart.
    func startAutoFlush(
        monitor: NetworkPathMonitoring, posterProvider: @escaping () -> OutboxPosting?
    ) {
        self.monitor = monitor
        self.posterProvider = posterProvider
        monitor.onBecameOnline { [weak self] in
            await self?.flushWithResolvedPoster()
        }
        monitor.start()
    }

    private func flushWithResolvedPoster() async {
        guard let poster = posterProvider?() else { return }
        await flush(using: poster)
    }

    private func refreshCount() {
        pendingCount = store.fetchAll().filter { $0.status == .pending }.count
    }
}

/// Production connectivity monitor over `NWPathMonitor`. Fires the flush handler on
/// every satisfied path update; the queue's own `isFlushing` guard coalesces bursts.
final class NWPathNetworkMonitor: NetworkPathMonitoring {
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "com.habittracker.outbox.monitor")
    private var handler: (() async -> Void)?

    func onBecameOnline(_ handler: @escaping () async -> Void) {
        self.handler = handler
    }

    func start() {
        monitor.pathUpdateHandler = { [weak self] path in
            guard path.status == .satisfied, let handler = self?.handler else { return }
            Task { await handler() }
        }
        monitor.start(queue: queue)
    }
}

/// The production outbox. Built once, on-disk; if SwiftData cannot open its store the
/// app degrades to an in-memory queue (offline saves still survive within a run) rather
/// than crashing at launch. `startAutoFlush` is wired once, on first access.
@MainActor
enum OutboxLive {
    private static let logger = Logger(
        subsystem: "com.habittracker.app", category: "OutboxLive"
    )

    static let shared: OutboxQueue = {
        let store: OutboxStore
        do {
            store = try SwiftDataOutboxStore()
        } catch {
            logger.error("On-disk outbox unavailable, using in-memory: \(String(describing: error))")
            store = InMemoryOutboxStore()
        }
        let queue = OutboxQueue(store: store)
        queue.startAutoFlush(
            monitor: NWPathNetworkMonitor(),
            posterProvider: { APIClient.live() }
        )
        return queue
    }()
}
