// [review:need-review] PHASE-03/163, PHASE-03/217, PHASE-03/172, PHASE-03/170
// summary: since #170 also the file queue of quick-mark taps (`QuickMarkOutbox`) at the end of the file; SwiftData queue of closed intervals under ~/Library/Application Support/com.talvior.habitagent/ (in memory if the disk refuses) — enqueue, read in batches of 500, delete once the server confirmed, drop after 14 days with the code kept in the agent state — the last one and a tally per code
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

/// What dropped intervals add up to under one code, so the history survives a later drop under another code.
struct QueueErrorTally: Equatable {
    let code: QueueErrorCode
    /// How many times intervals were dropped under this code.
    let events: Int
    /// How many intervals those events took in all.
    let intervals: Int
    let lastAt: Date
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
    /// A default, so a queue written before the field existed opens as is.
    var idleSeconds: Int = 0

    init(_ interval: ActivityInterval) {
        id = UUID()
        bundleID = interval.bundleID
        startedAt = interval.startedAt
        endedAt = interval.endedAt
        localDate = interval.localDate
        utcOffsetMinutes = interval.utcOffsetMinutes
        switchCount = interval.switchCount
        idleSeconds = interval.idleSeconds
    }

    var interval: ActivityInterval {
        ActivityInterval(
            bundleID: bundleID, startedAt: startedAt, endedAt: endedAt,
            localDate: localDate, utcOffsetMinutes: utcOffsetMinutes, switchCount: switchCount,
            idleSeconds: idleSeconds
        )
    }
}

/// The agent's one-row state: the last reason intervals were dropped. `QueueErrorTotal` keeps the rest.
@Model
final class QueueState {
    var lastErrorCode: String?
    var lastErrorCount: Int
    var lastErrorAt: Date?

    init() {
        lastErrorCount = 0
    }
}

/// One row per error code.
@Model
final class QueueErrorTotal {
    @Attribute(.unique) var code: String
    var events: Int
    var intervals: Int
    var lastAt: Date

    init(code: String, at date: Date) {
        self.code = code
        events = 0
        intervals = 0
        lastAt = date
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
        let schema = Schema([QueuedInterval.self, QueueState.self, QueueErrorTotal.self])
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

    /// Every code under which intervals were dropped, with its totals and the date of the last drop.
    var errorHistory: [QueueErrorTally] {
        let rows = fetch(FetchDescriptor<QueueErrorTotal>(sortBy: [SortDescriptor(\.code)])) ?? []
        return rows.compactMap { row in
            QueueErrorCode(rawValue: row.code).map {
                QueueErrorTally(code: $0, events: row.events, intervals: row.intervals, lastAt: row.lastAt)
            }
        }
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
        let raw = code.rawValue
        let total = fetch(FetchDescriptor<QueueErrorTotal>(predicate: #Predicate { $0.code == raw }))?.first ?? {
            let created = QueueErrorTotal(code: raw, at: date)
            context.insert(created)
            return created
        }()
        total.events += 1
        total.intervals += count
        total.lastAt = date
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

/// Taps on quick marks waiting for the server, in a file next to the interval queue.
///
/// A tap is on disk from the moment of the press and goes out oldest first under its own
/// `Idempotency-Key`, so a resend after a lost answer is one event. Failures wait on `Backoff`;
/// a refusal that will repeat (the mark is gone or off, the press is older than the server accepts)
/// drops the tap and is remembered in `lastRejectedAt`.
@MainActor
final class QuickMarkOutbox: ObservableObject {
    typealias Sender = (QuickMarkTap) async throws -> QuickMarkEventResult

    /// First retry after 15 s, then 30 s, then 60 s for good: a network that came back is noticed within a minute.
    static let retryDelays = (first: TimeInterval(15), last: TimeInterval(60))
    private static let log = Logger(subsystem: AgentPaths.identifier, category: "quick-mark-outbox")

    @Published private(set) var pending: [QuickMarkTap]
    private(set) var lastRejectedAt: Date?
    /// Called with the server's answer before the tap leaves `pending`.
    var onConfirmed: (QuickMarkEventResult) -> Void = { _ in }

    private let fileURL: URL
    private let send: Sender
    private let now: () -> Date
    private var backoff = Backoff(initialDelay: retryDelays.first, maxDelay: retryDelays.last)
    private var notBefore = Date.distantPast
    private var flushing = false

    init(fileURL: URL, now: @escaping () -> Date = Date.init, send: @escaping Sender) {
        self.fileURL = fileURL
        self.now = now
        self.send = send
        pending = Self.load(fileURL)
    }

    /// `~/Library/Application Support/com.talvior.habitagent/quick-mark-taps.json`
    static func defaultFileURL() -> URL {
        AgentPaths.directory.appendingPathComponent("quick-mark-taps.json")
    }

    /// True when there is something to send and the backoff has run out.
    var isDue: Bool {
        !pending.isEmpty && !flushing && now() >= notBefore
    }

    /// Writes the tap to disk at once; sending is `flush`.
    func enqueue(_ tap: QuickMarkTap) {
        pending.append(tap)
        persist()
    }

    /// Sends the oldest first, one at a time, until one fails. `force` ignores the backoff.
    func flush(force: Bool = false) async {
        guard !flushing, !pending.isEmpty, force || now() >= notBefore else { return }
        flushing = true
        defer { flushing = false }
        while let head = pending.first {
            do {
                onConfirmed(try await send(head))
                backoff.reset()
                notBefore = .distantPast
            } catch PanelAPIError.rejected(let status) {
                lastRejectedAt = now()
                Self.log.error("quick-mark tap refused with \(status), dropped")
            } catch {
                notBefore = now().addingTimeInterval(backoff.recordFailure())
                return
            }
            pending.removeAll { $0.key == head.key }
            persist()
        }
    }

    private func persist() {
        do {
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                attributes: [.posixPermissions: AgentPaths.directoryPermissions]
            )
            try Self.encoder.encode(pending).write(to: fileURL, options: .atomic)
        } catch {
            Self.log.error("could not write the quick-mark queue: \(error.localizedDescription)")
        }
    }

    private static func load(_ url: URL) -> [QuickMarkTap] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        if let taps = try? decoder.decode([QuickMarkTap].self, from: data) { return taps }
        // Not overwritten by the next write: a person can still read what was in it.
        try? FileManager.default.moveItem(at: url, to: url.appendingPathExtension("unreadable"))
        log.error("quick-mark queue was unreadable and was set aside")
        return []
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}
