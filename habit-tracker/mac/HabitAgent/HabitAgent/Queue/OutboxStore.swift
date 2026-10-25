// [review:need-review] PHASE-03/163
// summary: SwiftData queue of closed intervals under ~/Library/Application Support/com.talvior.habitagent/ (in memory if the disk refuses) — enqueue, read in batches of 500, delete once the server confirmed, drop after 14 days with a code kept in the agent state
import Foundation
import SwiftData
import os

/// Where the agent keeps files. ADR-0019: nothing goes to `~/Documents` or the repository.
enum AgentPaths {
    /// Names the data directory, the log subsystem and the network queue.
    static let identifier = "com.talvior.habitagent"
    static let queueStoreName = "queue.store"
    /// The queue says which apps the person used and when; only the owner reads it.
    static let directoryPermissions = 0o700

    static var directory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(identifier, isDirectory: true)
    }

    static var queueStore: URL {
        directory.appendingPathComponent(queueStoreName)
    }
}

/// Why intervals left the queue without reaching the server. The raw value is the code kept in the agent state.
enum QueueErrorCode: String {
    /// Did not reach the server within `OutboxStore.retention`.
    case expired
    /// The catalogue has no such app.
    case unknownApp = "unknown_app"
    /// The server refuses the batch and names no app, so a resend cannot help.
    case invalidBatch = "invalid_batch"
}

struct QueueError: Equatable {
    let code: QueueErrorCode
    /// How many intervals the last such event took.
    let count: Int
    let at: Date
}

@Model
final class QueuedInterval {
    @Attribute(.unique) var id: UUID
    var bundleID: String
    var startedAt: Date
    var endedAt: Date
    var localDate: String
    var utcOffsetMinutes: Int
    var switchCount: Int

    init(_ interval: ActivityInterval) {
        id = UUID()
        bundleID = interval.bundleID
        startedAt = interval.startedAt
        endedAt = interval.endedAt
        localDate = interval.localDate
        utcOffsetMinutes = interval.utcOffsetMinutes
        switchCount = interval.switchCount
    }

    var interval: ActivityInterval {
        ActivityInterval(
            bundleID: bundleID, startedAt: startedAt, endedAt: endedAt,
            localDate: localDate, utcOffsetMinutes: utcOffsetMinutes, switchCount: switchCount
        )
    }
}

/// The agent's one-row state: the last reason intervals were dropped.
@Model
final class QueueState {
    var lastErrorCode: String?
    var lastErrorCount: Int
    var lastErrorAt: Date?

    init() {
        lastErrorCount = 0
    }
}

@MainActor
final class OutboxStore {
    /// One batch holds the oldest intervals; `ids` say which rows to delete once the server confirmed them.
    struct Batch: Equatable {
        let ids: [UUID]
        let intervals: [ActivityInterval]

        /// The first half and the rest, to find the one interval the server refuses.
        var halves: (head: Batch, tail: Batch) {
            let middle = ids.count / 2
            return (
                Batch(ids: Array(ids[..<middle]), intervals: Array(intervals[..<middle])),
                Batch(ids: Array(ids[middle...]), intervals: Array(intervals[middle...]))
            )
        }
    }

    /// The server's cap on one batch (`MAX_BATCH_INTERVALS`).
    static let maxBatch = 500
    /// An interval that did not arrive within two weeks is dropped; a queue that grows forever is not an option.
    static let retention: TimeInterval = 14 * 24 * 60 * 60

    private static let logger = Logger(subsystem: AgentPaths.identifier, category: "OutboxStore")

    private let container: ModelContainer
    private let context: ModelContext
    private var excludedBundles: Set<String>
    /// False for a queue in memory: it does not survive a restart.
    let isOnDisk: Bool

    /// Opens (creates) the queue in `directory`; `nil` keeps it in memory only.
    init(directory: URL? = AgentPaths.directory, excluding bundles: Set<String> = []) throws {
        let schema = Schema([QueuedInterval.self, QueueState.self])
        let configuration: ModelConfiguration
        if let directory {
            try FileManager.default.createDirectory(
                at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: AgentPaths.directoryPermissions]
            )
            configuration = ModelConfiguration(
                schema: schema,
                url: directory.appendingPathComponent(AgentPaths.queueStoreName),
                allowsSave: true,
                cloudKitDatabase: .none
            )
        } else {
            configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)
        }
        container = try ModelContainer(for: schema, configurations: configuration)
        context = ModelContext(container)
        excludedBundles = bundles
        isOnDisk = directory != nil
    }

    /// The queue on disk; if the disk refuses it, a queue in memory, so collection goes on.
    static func openWithFallback(directory: URL = AgentPaths.directory, excluding bundles: Set<String> = []) throws -> OutboxStore {
        do {
            return try OutboxStore(directory: directory, excluding: bundles)
        } catch {
            logger.error("Queue on disk unavailable: \(AgentLog.code(of: error), privacy: .public); \(String(describing: error), privacy: .private)")
            return try OutboxStore(directory: nil, excluding: bundles)
        }
    }

    var count: Int {
        do {
            return try context.fetchCount(FetchDescriptor<QueuedInterval>())
        } catch {
            Self.logger.error("Queue count failed: \(AgentLog.code(of: error), privacy: .public); \(String(describing: error), privacy: .private)")
            return 0
        }
    }

    var lastError: QueueError? {
        guard let state = fetchState(), let raw = state.lastErrorCode,
              let code = QueueErrorCode(rawValue: raw), let at = state.lastErrorAt else { return nil }
        return QueueError(code: code, count: state.lastErrorCount, at: at)
    }

    func enqueue(_ intervals: [ActivityInterval]) {
        for interval in intervals where !excludedBundles.contains(interval.bundleID) {
            context.insert(QueuedInterval(interval))
        }
        save()
    }

    /// The oldest intervals, at most `maxBatch`; nil when the queue is empty.
    func nextBatch() -> Batch? {
        read(newestFirst: false, limit: Self.maxBatch)
    }

    /// The newest interval alone: a probe to learn whether the server takes anything at all.
    func newestBatch() -> Batch? {
        read(newestFirst: true, limit: 1)
    }

    /// Deletes what the server confirmed.
    func remove(_ batch: Batch) {
        delete(ids: batch.ids)
    }

    /// Drops a batch the server will never accept.
    func drop(_ batch: Batch, at date: Date) {
        delete(ids: batch.ids)
        record(.invalidBatch, count: batch.ids.count, at: date)
    }

    /// Drops everything of an app the catalogue refused and stops queueing it.
    func drop(bundleID: String, at date: Date) {
        excludedBundles.insert(bundleID)
        let descriptor = FetchDescriptor<QueuedInterval>(predicate: #Predicate { $0.bundleID == bundleID })
        let rows = fetch(descriptor) ?? []
        rows.forEach(context.delete)
        record(.unknownApp, count: rows.count, at: date)
    }

    /// Drops intervals that ended more than `retention` before `now`; returns how many.
    @discardableResult
    func dropExpired(now: Date) -> Int {
        let limit = now.addingTimeInterval(-Self.retention)
        let rows = fetch(FetchDescriptor<QueuedInterval>(predicate: #Predicate { $0.endedAt < limit })) ?? []
        guard !rows.isEmpty else { return 0 }
        rows.forEach(context.delete)
        record(.expired, count: rows.count, at: now)
        return rows.count
    }

    private func read(newestFirst: Bool, limit: Int) -> Batch? {
        let order: SortOrder = newestFirst ? .reverse : .forward
        var descriptor = FetchDescriptor<QueuedInterval>(
            sortBy: [SortDescriptor(\.startedAt, order: order), SortDescriptor(\.endedAt, order: order)]
        )
        descriptor.fetchLimit = limit
        guard let rows = fetch(descriptor), !rows.isEmpty else { return nil }
        return Batch(ids: rows.map(\.id), intervals: rows.map(\.interval))
    }

    private func delete(ids: [UUID]) {
        let rows = fetch(FetchDescriptor<QueuedInterval>(predicate: #Predicate { ids.contains($0.id) })) ?? []
        rows.forEach(context.delete)
        save()
    }

    private func record(_ code: QueueErrorCode, count: Int, at date: Date) {
        let state = fetchState() ?? {
            let created = QueueState()
            context.insert(created)
            return created
        }()
        state.lastErrorCode = code.rawValue
        state.lastErrorCount = count
        state.lastErrorAt = date
        save()
        // Codes and counts only: what an interval says about the person stays out of the log.
        Self.logger.notice("Dropped \(count) intervals: \(code.rawValue, privacy: .public)")
    }

    private func fetchState() -> QueueState? {
        fetch(FetchDescriptor<QueueState>())?.first
    }

    private func fetch<Model: PersistentModel>(_ descriptor: FetchDescriptor<Model>) -> [Model]? {
        do {
            return try context.fetch(descriptor)
        } catch {
            Self.logger.error("Queue fetch failed: \(AgentLog.code(of: error), privacy: .public); \(String(describing: error), privacy: .private)")
            return nil
        }
    }

    private func save() {
        do {
            try context.save()
        } catch {
            // The changes stay in the context and go out with the next successful save.
            Self.logger.error("Queue save failed: \(AgentLog.code(of: error), privacy: .public); \(String(describing: error), privacy: .private)")
        }
    }
}
