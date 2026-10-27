// [review:need-review] PHASE-01/12-ios-offline-queue, PHASE-01/39-server-idempotency-key-entries, PHASE-01/208, PHASE-03/225
// summary: the one offline write queue of the app — every write that can wait for the network (entry create, checklist, quick-mark press, plan mark, plan fact, day notebook) is kept on disk under its own Idempotency-Key with the day it was made and replayed in order when the network returns; a dead network, a wrong key or a 5xx keep it waiting, a refusal moves it to a visible "not sent" list with the reason; a newer "set" of one object replaces the waiting one; retry and discard from the list
import Combine
import Foundation
import Network
import SwiftData
import os

/// Lifecycle of a queued write: `pending` is sent on every flush, `failed` waits in the
/// "not sent" list for the person to retry or discard it.
enum PendingStatus: String, Codable {
    case pending
    case failed
}

/// One write the queue can replay. Case names and fields are stored on disk: never rename them.
enum OutboxAction: Codable, Equatable {
    case createEntry(EntryCreateDTO)
    case upsertChecklist(ChecklistUpsertDTO)
    case tapQuickMark(QueuedTap)
    case setDayMark(QueuedDayMark)
    case recordPlanFact(QueuedPlanFact)
    case saveNotebook(QueuedNotebook)

    /// The object written. Writes of one object replay in the order they were made.
    var target: String {
        switch self {
        case .createEntry(let entry): return "entry:\(entry.categoryId):\(entry.entryDate)"
        case .upsertChecklist(let list): return "checklist:\(list.categoryId):\(list.entryDate)"
        case .tapQuickMark(let tap): return "quick-mark:\(tap.quickMarkId)"
        case .setDayMark(let mark): return "mark:\(mark.date):\(mark.itemID.uuidString)"
        case .recordPlanFact(let fact): return "fact:\(fact.date):\(fact.itemID.uuidString)"
        case .saveNotebook(let notebook): return "notebook:\(notebook.date)"
        }
    }

    /// The day the action belongs to, `yyyy-MM-dd`; nil when the server's today decides.
    var day: String? {
        switch self {
        case .createEntry(let entry): return entry.entryDate
        case .upsertChecklist(let list): return list.entryDate
        case .tapQuickMark(let tap): return tap.serverDay
        case .setDayMark(let mark): return mark.date
        case .recordPlanFact(let fact): return fact.date
        case .saveNotebook(let notebook): return notebook.date
        }
    }

    /// A write of the whole state of its object: a newer one makes a waiting older one pointless.
    /// Additions (an entry, a press, a fact) are never merged — two presses are two presses.
    var replacesOlderOfSameTarget: Bool {
        switch self {
        case .upsertChecklist, .setDayMark, .saveNotebook: return true
        case .createEntry, .tapQuickMark, .recordPlanFact: return false
        }
    }

    /// This write taking the place of a waiting `older` one: it keeps the server state the first
    /// of them was made over, because that is what the server still holds.
    func replacing(_ older: OutboxAction) -> OutboxAction {
        switch (self, older) {
        case (.setDayMark(var mark), .setDayMark(let earlier)):
            mark.expected = earlier.expected
            return .setDayMark(mark)
        case (.saveNotebook(var notebook), .saveNotebook(let earlier)):
            notebook.expected = earlier.expected
            return .saveNotebook(notebook)
        default:
            return self
        }
    }

    /// The write as the person asked to send it again from the "not sent" list: without the check
    /// that refused it (the day of a press, the server state a mark or notebook was made over).
    func forcedRetry() -> OutboxAction {
        switch self {
        case .tapQuickMark(var tap):
            tap.serverDay = nil
            return .tapQuickMark(tap)
        case .setDayMark(var mark):
            mark.expected = nil
            return .setDayMark(mark)
        case .saveNotebook(var notebook):
            notebook.expected = nil
            return .saveNotebook(notebook)
        case .createEntry, .upsertChecklist, .recordPlanFact:
            return self
        }
    }
}

/// A quick-mark press. `serverDay` is the server's day as the button list last said; a replay sends
/// it as `entry_date`, so a press made before midnight is refused (409) instead of written into the
/// next day. Nil sends the press to the server's current day.
struct QueuedTap: Codable, Equatable {
    let quickMarkId: Int
    let categoryId: Int
    let utcOffsetMinutes: Int
    var serverDay: String?
}

/// A plan mark. `expected` is the state the person changed (`""` — no mark); a server holding
/// another one by replay time was changed elsewhere. Nil sends without the check.
struct QueuedDayMark: Codable, Equatable {
    let date: String
    let itemID: UUID
    let state: String?
    let note: String?
    var expected: String?
}

/// A new fact of a plan line, sent under the key of the attempt that failed.
struct QueuedPlanFact: Codable, Equatable {
    let date: String
    let itemID: UUID
    let values: [Value]
    let mark: String?

    struct Value: Codable, Equatable {
        let fieldId: Int
        let number: Double?
        let flag: Bool?
        let unit: String?
    }

    init(date: String, itemID: UUID, body: PlanFactRequestDTO) {
        self.date = date
        self.itemID = itemID
        self.mark = body.mark
        self.values = body.values.map { value in
            switch value.value {
            case .number(let number): return Value(fieldId: value.fieldId, number: number, flag: nil, unit: value.unit)
            case .flag(let flag): return Value(fieldId: value.fieldId, number: nil, flag: flag, unit: value.unit)
            }
        }
    }

    var body: PlanFactRequestDTO {
        PlanFactRequestDTO(
            values: values.map { value in
                PlanFactValueRequestDTO(
                    fieldId: value.fieldId,
                    value: value.flag.map(PlanFactValue.flag) ?? .number(value.number ?? 0),
                    unit: value.unit
                )
            },
            mark: mark
        )
    }
}

/// The notebook of a day. `expected` is the server text it was typed over; nil sends without the check.
struct QueuedNotebook: Codable, Equatable {
    let date: String
    let content: String
    var expected: String?
}

/// One queued write. `key` is the Idempotency-Key of every attempt, the failed direct one included,
/// so a request that reached the server and lost its answer is not recorded twice.
struct OutboxWrite: Identifiable, Equatable {
    static let retryTitle = "Повторить"
    static let retryTodayTitle = "Записать в сегодня"
    static let retryOverwriteTitle = "Записать поверх"

    let id: UUID
    let key: String
    var action: OutboxAction
    /// What the person did, in words, for the list of waiting writes.
    let label: String
    var createdAt: Date
    var attempts: Int
    var status: PendingStatus
    /// Why the write is in the "not sent" list.
    var failure: String?

    /// The retry button of the "not sent" list says what a retry will do.
    var retryTitle: String {
        guard failure == OutboxQueue.dayTurnedReason || failure == OutboxQueue.notebookChangedReason
            || failure == OutboxQueue.markChangedReason else { return Self.retryTitle }
        if case .tapQuickMark = action { return Self.retryTodayTitle }
        return Self.retryOverwriteTitle
    }
}

/// The replay refused a write before sending it: the object moved on the server since it was made.
struct OutboxConflict: Error, Equatable {
    let reason: String
}

/// The network side of the queue. `OutboxReplay` is the production implementation.
protocol OutboxSending {
    func send(_ action: OutboxAction, idempotencyKey: String) async throws
}

/// Durable list behind `OutboxQueue`. Kept small — the queue owns all policy.
protocol OutboxStore: AnyObject {
    func append(_ write: OutboxWrite)
    /// Every stored write, oldest `createdAt` first (ties broken by insertion order).
    func fetchAll() -> [OutboxWrite]
    func update(_ write: OutboxWrite)
    func delete(id: UUID)
}

/// Process-lifetime store used in tests and as the fallback when SwiftData is unavailable.
final class InMemoryOutboxStore: OutboxStore {
    private struct Slot {
        let sequence: Int
        var write: OutboxWrite
    }

    private var slots: [UUID: Slot] = [:]
    private var nextSequence = 0

    func append(_ write: OutboxWrite) {
        slots[write.id] = Slot(sequence: nextSequence, write: write)
        nextSequence += 1
    }

    func fetchAll() -> [OutboxWrite] {
        slots.values
            .sorted { ($0.write.createdAt, $0.sequence) < ($1.write.createdAt, $1.sequence) }
            .map(\.write)
    }

    func update(_ write: OutboxWrite) {
        guard var slot = slots[write.id] else { return }
        slot.write = write
        slots[write.id] = slot
    }

    func delete(id: UUID) {
        slots[id] = nil
    }
}

/// One queued write as SwiftData persists it; the action is stored encoded.
@Model
final class PendingWriteRecord {
    @Attribute(.unique) var id: UUID
    var key: String
    var action: Data
    var label: String
    var createdAt: Date
    var attempts: Int
    var statusRaw: String
    var failure: String?

    init(write: OutboxWrite, action: Data) {
        self.id = write.id
        self.key = write.key
        self.action = action
        self.label = write.label
        self.createdAt = write.createdAt
        self.attempts = write.attempts
        self.statusRaw = write.status.rawValue
        self.failure = write.failure
    }
}

/// Durable `OutboxStore` on SwiftData, in a file of its own: a write made in airplane mode is still
/// queued after the app is killed, and no schema change of the read cache can touch it.
final class SwiftDataOutboxStore: OutboxStore {
    private let context: ModelContext

    private static let logger = Logger(subsystem: "com.habittracker.app", category: "SwiftDataOutboxStore")

    init(context: ModelContext) {
        self.context = context
    }

    convenience init(url: URL) throws {
        let container = try ModelContainer(
            for: PendingWriteRecord.self, configurations: ModelConfiguration(url: url)
        )
        self.init(context: ModelContext(container))
    }

    func append(_ write: OutboxWrite) {
        let action: Data
        do {
            action = try CacheCoding.encoder().encode(write.action)
        } catch {
            // Never silently: a write that cannot be stored is a lost write. No contents in the log.
            Self.logger.error("Outbox append: action encode failed: \(String(describing: error))")
            return
        }
        context.insert(PendingWriteRecord(write: write, action: action))
        persist()
    }

    func fetchAll() -> [OutboxWrite] {
        let descriptor = FetchDescriptor<PendingWriteRecord>(sortBy: [SortDescriptor(\.createdAt, order: .forward)])
        do {
            return try context.fetch(descriptor).compactMap(Self.toDomain)
        } catch {
            // A failed fetch would hide every queued write from the flush — say so.
            Self.logger.error("Outbox fetchAll failed: \(String(describing: error))")
            return []
        }
    }

    func update(_ write: OutboxWrite) {
        guard let record = fetchRecord(id: write.id) else { return }
        do {
            record.action = try CacheCoding.encoder().encode(write.action)
        } catch {
            Self.logger.error("Outbox update: action encode failed: \(String(describing: error))")
            return
        }
        record.createdAt = write.createdAt
        record.attempts = write.attempts
        record.statusRaw = write.status.rawValue
        record.failure = write.failure
        persist()
    }

    func delete(id: UUID) {
        guard let record = fetchRecord(id: id) else { return }
        context.delete(record)
        persist()
    }

    private func fetchRecord(id: UUID) -> PendingWriteRecord? {
        let descriptor = FetchDescriptor<PendingWriteRecord>(predicate: #Predicate { $0.id == id })
        do {
            return try context.fetch(descriptor).first
        } catch {
            Self.logger.error("Outbox fetchRecord failed: \(String(describing: error))")
            return nil
        }
    }

    private func persist() {
        do {
            try context.save()
        } catch {
            // A queue write failure must not crash a background flush or a save; logged without contents.
            Self.logger.error("Outbox persist failed: \(String(describing: error))")
        }
    }

    private static func toDomain(_ record: PendingWriteRecord) -> OutboxWrite? {
        let action: OutboxAction
        do {
            action = try CacheCoding.decoder().decode(OutboxAction.self, from: record.action)
        } catch {
            // A record that no longer decodes is a lost write: say so in the log (no contents).
            logger.error("Outbox toDomain: action decode failed: \(String(describing: error))")
            return nil
        }
        return OutboxWrite(
            id: record.id, key: record.key, action: action, label: record.label, createdAt: record.createdAt,
            attempts: record.attempts, status: PendingStatus(rawValue: record.statusRaw) ?? .pending,
            failure: record.failure
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

/// The offline write queue. A write that cannot reach the server is kept here instead of lost;
/// `flush` replays the queue oldest first and deletes a write only once the server took it.
///
/// - A dead network, a wrong API key (401), 408/429 and a 5xx stop the flush: nothing overtakes the
///   write that failed, so the writes of one object reach the server in the order they were made.
///   A 5xx that repeats `maxServerErrorAttempts` times moves the write to "not sent" — never deleted.
/// - Any other 4xx and a replay check that refuses (`OutboxConflict`) move the write to "not sent"
///   with the reason; the writes behind it go on.
/// - Every attempt carries the write's `key`, so a send cut mid-way is the same write on the server.
@MainActor
final class OutboxQueue: ObservableObject {
    static let maxServerErrorAttempts = 5
    nonisolated static let dayTurnedReason = "День уже сменился: сервер не записывает отметку задним числом."
    nonisolated static let notebookChangedReason = "Блокнот этого дня изменился на сервере, пока телефон был без сети."
    nonisolated static let markChangedReason = "Отметку этого пункта изменили на сервере, пока телефон был без сети."

    /// Every write, oldest first: waiting ones and the "not sent" list.
    @Published private(set) var writes: [OutboxWrite] = []
    /// The writes a flush delivered; announced only when there is at least one.
    let delivered = PassthroughSubject<[OutboxWrite], Never>()

    private let store: OutboxStore
    private let now: () -> Date
    private let senderProvider: () -> OutboxSending?
    private var isFlushing = false
    private var inFlightID: UUID?
    private var monitor: NetworkPathMonitoring?

    /// `sender` is resolved per flush, so a new server address or key applies without a restart.
    init(store: OutboxStore, now: @escaping () -> Date = Date.init, sender: @escaping () -> OutboxSending? = { nil }) {
        self.store = store
        self.now = now
        self.senderProvider = sender
        reload()
    }

    var pending: [OutboxWrite] { writes.filter { $0.status == .pending } }
    var failed: [OutboxWrite] { writes.filter { $0.status == .failed } }
    var pendingCount: Int { pending.count }
    var failedCount: Int { failed.count }

    /// Queues a write that could not be sent now. `key` is the key of the attempt that failed.
    /// A whole-state write replaces a waiting one of the same object (unless that one is in flight).
    func enqueue(_ action: OutboxAction, key: String = UUID().uuidString, label: String) {
        var action = action
        if action.replacesOlderOfSameTarget {
            for older in pending where older.action.target == action.target && older.id != inFlightID {
                action = action.replacing(older.action)
                store.delete(id: older.id)
            }
        }
        store.append(
            OutboxWrite(
                id: UUID(), key: key, action: action, label: label, createdAt: now(), attempts: 0,
                status: .pending, failure: nil
            )
        )
        reload()
    }

    /// Puts back a write carried over from an older queue, with its own key and time.
    func restore(_ action: OutboxAction, key: String, label: String, createdAt: Date) {
        store.append(
            OutboxWrite(
                id: UUID(), key: key, action: action, label: label, createdAt: createdAt, attempts: 0,
                status: .pending, failure: nil
            )
        )
        reload()
    }

    /// Sends a "not sent" write again, as the newest action and without the check that refused it.
    /// The key stays: the server has not recorded it, or a repeat of it is the same write.
    func retry(id: UUID) {
        guard var write = writes.first(where: { $0.id == id && $0.status == .failed }) else { return }
        write.action = write.action.forcedRetry()
        write.status = .pending
        write.failure = nil
        write.attempts = 0
        write.createdAt = now()
        store.update(write)
        reload()
    }

    func discard(id: UUID) {
        store.delete(id: id)
        reload()
    }

    /// Flushes with the sender of the current settings; nothing to do without one.
    func flush() async {
        guard !pending.isEmpty, let sender = senderProvider() else { return }
        await flush(using: sender)
    }

    /// Replays the waiting writes oldest first. A write queued during the flush is picked up by it;
    /// one replaced while waiting is not sent. Concurrent flushes are coalesced.
    func flush(using sender: OutboxSending) async {
        guard !isFlushing else { return }
        isFlushing = true
        defer {
            isFlushing = false
            inFlightID = nil
        }
        var tried: Set<UUID> = []
        var sent: [OutboxWrite] = []
        while let write = store.fetchAll().first(where: { $0.status == .pending && !tried.contains($0.id) }) {
            tried.insert(write.id)
            inFlightID = write.id
            do {
                try await sender.send(write.action, idempotencyKey: write.key)
                store.delete(id: write.id)
                sent.append(write)
            } catch {
                if !settle(write, after: error) { break }
            }
        }
        reload()
        if !sent.isEmpty { delivered.send(sent) }
    }

    /// Starts flushing on every reconnect (and on the monitor's first report at launch).
    func startAutoFlush(monitor: NetworkPathMonitoring) {
        self.monitor = monitor
        monitor.onBecameOnline { [weak self] in
            await self?.flush()
        }
        monitor.start()
    }

    /// Records the failure of `write`. Returns true when the flush may go on to the next write.
    private func settle(_ write: OutboxWrite, after error: Error) -> Bool {
        var settled = write
        settled.attempts += 1
        switch Self.outcome(of: error, for: write.action) {
        case .waitForNetwork:
            store.update(settled)
            return false
        case .serverError(let status):
            if settled.attempts >= Self.maxServerErrorAttempts {
                settled.status = .failed
                settled.failure = "Сервер \(settled.attempts) раз ответил ошибкой \(status)."
                store.update(settled)
                return true
            }
            store.update(settled)
            return false
        case .refused(let reason):
            settled.status = .failed
            settled.failure = reason
            store.update(settled)
            return true
        case .delivered:
            store.delete(id: write.id)
            return true
        }
    }

    private enum Outcome {
        case waitForNetwork
        case serverError(Int)
        case refused(String)
        case delivered
    }

    private static func outcome(of error: Error, for action: OutboxAction) -> Outcome {
        if let conflict = error as? OutboxConflict { return .refused(conflict.reason) }
        guard let apiError = error as? APIClientError else { return .waitForNetwork }
        switch apiError {
        case .timeout, .transport, .unauthorized, .invalidBaseURL:
            return .waitForNetwork
        case .invalidResponse:
            // The server answered 2xx with a body this app could not read: the write is there.
            return .delivered
        case .unexpectedStatus(let status):
            switch status {
            case 408, 429: return .waitForNetwork
            case 500...: return .serverError(status)
            case 409: return .refused(conflictReason(for: action))
            case 404: return .refused("Сервер не нашёл, куда записать (404): объект удалён.")
            case 400, 422: return .refused("Сервер не принял данные (\(status)).")
            default: return .refused("Сервер отказал (\(status)).")
            }
        }
    }

    /// A 409 is a server-side rule saying no: for a press, the day guard (or a button switched off).
    private static func conflictReason(for action: OutboxAction) -> String {
        if case .tapQuickMark = action { return dayTurnedReason }
        return "Сервер отказал (409): запись противоречит тому, что уже есть на сервере."
    }

    private func reload() {
        writes = store.fetchAll()
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

/// The production queue: one SwiftData file under Application Support, the old queues carried over
/// once, flushed off `NWPathMonitor`. Degrades to memory rather than failing at launch.
@MainActor
enum OutboxLive {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "OutboxLive")
    private static let fileName = "outbox.store"

    static let shared: OutboxQueue = {
        let store: OutboxStore
        var directory: URL?
        do {
            let support = try FileManager.default.url(
                for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true
            )
            directory = support
            store = try SwiftDataOutboxStore(url: support.appendingPathComponent(fileName))
        } catch {
            logger.error("On-disk outbox unavailable, using memory: \(String(describing: error))")
            store = InMemoryOutboxStore()
        }
        let queue = OutboxQueue(store: store, sender: { APIClient.liveOutboxSender() })
        if let directory { OutboxLegacyImport.runOnce(directory: directory, into: queue) }
        queue.startAutoFlush(monitor: NWPathNetworkMonitor())
        return queue
    }()
}
