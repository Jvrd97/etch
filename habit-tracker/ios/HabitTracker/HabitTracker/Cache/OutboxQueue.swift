// [review:need-review] PHASE-01/12-ios-offline-queue, PHASE-01/39-server-idempotency-key-entries, PHASE-01/208, PHASE-03/225, PHASE-03/236, PHASE-03/242, PHASE-03/256, PHASE-03/263
// summary: PHASE-03/263 — `enqueue` returns the id of the queued write, so a caller can tell whether that very write was delivered
// summary: PHASE-03/256 — a failed TLS handshake is "never left", not "may have landed"
// summary: the one offline write queue of the app — every write that can wait for the network (entry create, checklist, quick-mark press, plan mark, plan fact, day notebook) is kept on disk under its own Idempotency-Key with the day it was made and replayed in order when the network returns; a dead network or a wrong key keep it waiting (the key problem is published), a 5xx keeps it waiting until it repeats five times in a row, a refusal moves it to a visible "not sent" list with the reason and its kind; a newer "set" of one object replaces the waiting one; retry (which sends at once) and discard from the list
// summary: PHASE-03/236, 242 — a press carries the moment it was made (a 422 on that moment is "not sent" with "write to today"); a write replacing a waiting one also accepts the states of replaced writes that went out and lost their answer (`mayHaveLanded`, stored), so one that landed is not a conflict and one that never left adds nothing; a direct attempt that lost its answer is queued with the flag set, a proxy's 502/504 sets it in the replay, and a direct Day mark that gets a 502/504 is queued with `mayHaveLanded: true` instead of rolling back blindly; a failed TLS handshake never carried the body; a retry that would write over a newer write of the same object says so
// [review:need-review] PHASE-03/240
// summary: PHASE-03/240 — a new write, markSupplementTaken (the «принял» of a supplement, by id and the press day): its target, day, forced retry without the day, and the 409 reasons
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 — the online path of a press: `send()` flushes without holding the caller; each delivery is announced at once with the server's answer (`OutboxDelivery`), a write moved to "not sent" is announced on `refused`; `attemptFailed` (stored, default false) and `isOverdue` tell a write that waits from one that is merely on its way; `withdraw` takes back a press not yet sent; the production queue tries again after a dead network or a 5xx on a growing delay
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
    case markSupplementTaken(QueuedSupplementIntake)

    /// The object written. Writes of one object replay in the order they were made.
    var target: String {
        switch self {
        case .createEntry(let entry): return "entry:\(entry.categoryId):\(entry.entryDate)"
        case .upsertChecklist(let list): return "checklist:\(list.categoryId):\(list.entryDate)"
        case .tapQuickMark(let tap): return "quick-mark:\(tap.quickMarkId)"
        case .setDayMark(let mark): return "mark:\(mark.date):\(mark.itemID.uuidString)"
        case .recordPlanFact(let fact): return "fact:\(fact.date):\(fact.itemID.uuidString)"
        case .saveNotebook(let notebook): return "notebook:\(notebook.date)"
        case .markSupplementTaken(let intake): return "supplement-intake:\(intake.supplementId)"
        }
    }

    /// The moment of a quick-mark press, when the press carries it.
    var pressMoment: Date? {
        if case .tapQuickMark(let tap) = self { return tap.occurredAt }
        return nil
    }

    /// The day the action belongs to, `yyyy-MM-dd`; nil when the server decides it (a press carrying
    /// its moment, or the server's today).
    var day: String? {
        switch self {
        case .createEntry(let entry): return entry.entryDate
        case .upsertChecklist(let list): return list.entryDate
        case .tapQuickMark(let tap): return tap.serverDay
        case .setDayMark(let mark): return mark.date
        case .recordPlanFact(let fact): return fact.date
        case .saveNotebook(let notebook): return notebook.date
        case .markSupplementTaken(let intake): return intake.intakeDate
        }
    }

    /// A write of the whole state of its object: a newer one makes a waiting older one pointless.
    /// Additions (an entry, a press, a fact) are never merged — two presses are two presses.
    var replacesOlderOfSameTarget: Bool {
        switch self {
        case .upsertChecklist, .setDayMark, .saveNotebook: return true
        case .createEntry, .tapQuickMark, .recordPlanFact, .markSupplementTaken: return false
        }
    }

    /// This write taking the place of a waiting `older` one. It keeps the server state the first of
    /// them was made over. When the older one `mayHaveLanded` (a send that lost its answer), its state
    /// is accepted too: the server holding it is that write, not a change made elsewhere. A write that
    /// never left the phone adds nothing — the same state on the server is somebody else's.
    func replacing(_ older: OutboxAction, mayHaveLanded: Bool) -> OutboxAction {
        switch (self, older) {
        case (.setDayMark(var mark), .setDayMark(let earlier)):
            mark.expected = earlier.expected
            mark.replacedStates = Self.accepted(earlier.replacedStates, plus: earlier.state ?? "", if: mayHaveLanded)
            return .setDayMark(mark)
        case (.saveNotebook(var notebook), .saveNotebook(let earlier)):
            notebook.expected = earlier.expected
            notebook.replacedContents = Self.accepted(earlier.replacedContents, plus: earlier.content, if: mayHaveLanded)
            return .saveNotebook(notebook)
        default:
            return self
        }
    }

    private static func accepted(_ earlier: [String]?, plus state: String, if landed: Bool) -> [String]? {
        guard landed else { return earlier }
        return (earlier ?? []) + [state]
    }

    /// The write as the person asked to send it again from the "not sent" list: without the check
    /// that refused it (the day or the moment of a press, the server state a mark or notebook was
    /// made over). A press then lands on the server's today.
    func forcedRetry() -> OutboxAction {
        switch self {
        case .tapQuickMark(var tap):
            tap.serverDay = nil
            tap.occurredAt = nil
            return .tapQuickMark(tap)
        case .setDayMark(var mark):
            mark.expected = nil
            return .setDayMark(mark)
        case .saveNotebook(var notebook):
            notebook.expected = nil
            return .saveNotebook(notebook)
        case .markSupplementTaken(var intake):
            intake.intakeDate = nil
            return .markSupplementTaken(intake)
        case .createEntry, .upsertChecklist, .recordPlanFact:
            return self
        }
    }
}

/// A quick-mark press. `occurredAt` is the moment of the press; a replay sends it as `occurred_at`,
/// and the server puts the press on the day that moment belongs to by its own day boundary, however
/// late it is delivered. `serverDay` is only on presses queued before the server took the moment:
/// a replay sends it as `entry_date`, and a turned day is refused (409). With neither the press
/// lands on the server's current day.
struct QueuedTap: Codable, Equatable {
    let quickMarkId: Int
    let categoryId: Int
    let utcOffsetMinutes: Int
    var serverDay: String?
    var occurredAt: Date? = nil
}

/// A plan mark. `expected` is the state the person changed (`""` — no mark); a server holding
/// another one by replay time was changed elsewhere. Nil sends without the check. `replacedStates`
/// are the states of waiting marks this one replaced: the server holding one of them is not a change
/// made elsewhere.
struct QueuedDayMark: Codable, Equatable {
    let date: String
    let itemID: UUID
    let state: String?
    let note: String?
    var expected: String?
    var replacedStates: [String]? = nil
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
/// `replacedContents` are the texts of waiting saves this one replaced, accepted on the server as well.
struct QueuedNotebook: Codable, Equatable {
    let date: String
    let content: String
    var expected: String?
    var replacedContents: [String]? = nil
}

/// The mark «принял» of a supplement. `intakeDate` is the day of the press by the phone's clock; a replay
/// sends it as a clock check, and a server on another day refuses (409) instead of writing the mark to
/// the wrong day. Nil lands on the server's current day. Only the id is stored: the name stays in the label.
struct QueuedSupplementIntake: Codable, Equatable {
    let supplementId: Int
    var intakeDate: String?
    let pressedAt: Date
}

/// Why a write sits in the "not sent" list; decides what a retry from the list does. Stored on disk.
enum OutboxFailureKind: String, Codable {
    /// The server said no for good (4xx); a retry sends the same write again.
    case refused
    /// The server failed `OutboxQueue.maxServerErrorAttempts` times in a row (5xx).
    case serverErrors
    /// A press carrying its day was refused with 409 (the day turned, or the button is off), or one
    /// carrying its moment was refused with 422 (older than the server's window, or a clock ahead).
    /// A retry sends it to the server's today.
    case dayTurned
    /// The replay check found the object changed on the server, or could not read it.
    case changedOnServer
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
    /// 5xx answers in a row; a dead network in between starts the count again.
    var serverErrors: Int
    var status: PendingStatus
    /// Why the write is in the "not sent" list, in words, and what kind of reason it is.
    var failure: String?
    var failureKind: OutboxFailureKind?
    /// An attempt went out and its answer was lost (a timeout, a dropped connection): the server may
    /// hold this write. A dead network before sending does not count. A replacing write accepts its state.
    var mayHaveLanded = false
    /// An attempt to send this write failed. A write that is merely on its way (queued a moment ago,
    /// its first send not answered yet) is not shown as waiting.
    var attemptFailed = false

    /// Whether the write is shown as waiting or not sent: it failed once, or it has been on its way
    /// longer than `OutboxQueue.quietPeriod`. A press sent at once and answered is never shown.
    func isOverdue(at moment: Date) -> Bool {
        status == .failed || attemptFailed || moment.timeIntervalSince(createdAt) >= OutboxQueue.quietPeriod
    }

    /// The retry button of the "not sent" list says what a retry will do.
    var retryTitle: String {
        switch failureKind {
        case .dayTurned: return Self.retryTodayTitle
        case .changedOnServer: return Self.retryOverwriteTitle
        case .refused, .serverErrors, nil: return Self.retryTitle
        }
    }
}

/// The replay refused a write before sending it: the object moved on the server since it was made,
/// or the check could not read the server's state.
struct OutboxConflict: Error, Equatable {
    let reason: String
}

/// What the server answered to a delivered write, for the screen that shows it.
enum OutboxReply {
    case entry(EntryDTO)
    case quickMarkEvent(QuickMarkEventDTO)
    case dayMark(DayMarkDTO)
    case planFact(PlanFactWriteDTO)
    case supplementIntake(SupplementIntakeDTO)
}

/// One write the server took, with its answer; the answer is nil when the write returns nothing the
/// app reads (a notebook) or a 2xx body this app could not read.
struct OutboxDelivery {
    let write: OutboxWrite
    let reply: OutboxReply?
}

/// The network side of the queue. `OutboxReplay` is the production implementation.
protocol OutboxSending {
    func send(_ action: OutboxAction, idempotencyKey: String) async throws -> OutboxReply?
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
    var serverErrors: Int = 0
    var statusRaw: String
    var failure: String?
    var failureKindRaw: String?
    var mayHaveLanded: Bool = false
    var attemptFailed: Bool = false

    init(write: OutboxWrite, action: Data) {
        self.id = write.id
        self.key = write.key
        self.action = action
        self.label = write.label
        self.createdAt = write.createdAt
        self.serverErrors = write.serverErrors
        self.statusRaw = write.status.rawValue
        self.failure = write.failure
        self.failureKindRaw = write.failureKind?.rawValue
        self.mayHaveLanded = write.mayHaveLanded
        self.attemptFailed = write.attemptFailed
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
        record.serverErrors = write.serverErrors
        record.statusRaw = write.status.rawValue
        record.failure = write.failure
        record.failureKindRaw = write.failureKind?.rawValue
        record.mayHaveLanded = write.mayHaveLanded
        record.attemptFailed = write.attemptFailed
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
            serverErrors: record.serverErrors, status: PendingStatus(rawValue: record.statusRaw) ?? .pending,
            failure: record.failure, failureKind: record.failureKindRaw.flatMap(OutboxFailureKind.init(rawValue:)),
            mayHaveLanded: record.mayHaveLanded, attemptFailed: record.attemptFailed
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
///   A 5xx that repeats `maxServerErrorAttempts` times in a row moves the write to "not sent" —
///   never deleted. A 2xx whose body this app cannot read counts as delivered.
/// - Any other 4xx and a replay check that refuses (`OutboxConflict`) move the write to "not sent"
///   with the reason; the writes behind it go on.
/// - Every attempt carries the write's `key`, so a send cut mid-way is the same write on the server.
@MainActor
final class OutboxQueue: ObservableObject {
    static let maxServerErrorAttempts = 5
    /// How long a write may be on its way before the screens and the strip show it as waiting.
    nonisolated static let quietPeriod: TimeInterval = 3
    /// The pauses before the production queue tries again after a flush stopped on a dead network or a
    /// 5xx; the last one repeats. A reconnect or the next press sends sooner.
    static let retryDelays: [Duration] = [.seconds(2), .seconds(5), .seconds(15), .seconds(30)]
    nonisolated static let dayTurnedReason =
        "Сервер не принял отметку (409): день уже сменился, или кнопка выключена."
    nonisolated static let tapRefusedReason = "Сервер не принял отметку (409): кнопка выключена."
    nonisolated static let pressTimeRefusedReason =
        "Сервер не принял время нажатия (422): нажатию больше семи дней, часы телефона спешат, или сервер ещё не обновлён и времени нажатия не знает."
    nonisolated static let supplementDayTurnedReason =
        "Сервер не принял отметку (409): день уже сменился, или добавка в архиве."
    nonisolated static let supplementArchivedReason = "Сервер не принял отметку (409): добавка в архиве."
    nonisolated static let notebookChangedReason = "Блокнот этого дня изменился на сервере, пока телефон был без сети."
    nonisolated static let markChangedReason = "Отметку этого пункта изменили на сервере, пока телефон был без сети."
    nonisolated static let checkFailedReason =
        "Не удалось сверить с сервером, что там сейчас: ответ на проверку не прочитан. Запись не отправлена."

    /// Every write, oldest first: waiting ones and the "not sent" list.
    @Published private(set) var writes: [OutboxWrite] = []
    /// The last flush stopped on a refused API key (401): the queue waits for Settings, not for the network.
    @Published private(set) var waitsForKey = false
    /// Each write the server took, announced as soon as it did, after `writes` dropped it: a screen
    /// replaces its waiting sign with the answer in the same turn, so nothing blinks.
    let delivered = PassthroughSubject<OutboxDelivery, Never>()
    /// Each write moved to the "not sent" list by a flush, with its reason in `failure`.
    let refused = PassthroughSubject<OutboxWrite, Never>()

    private let store: OutboxStore
    private let now: () -> Date
    private let senderProvider: () -> OutboxSending?
    private var isFlushing = false
    private var inFlightID: UUID?
    private var monitor: NetworkPathMonitoring?
    /// Pauses of the retry after a failed flush; empty (no retry) until `startAutoFlush`.
    private var retryDelays: [Duration] = []
    private var retryRound = 0
    private var retryTask: Task<Void, Never>?

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

    /// Whether a write of `action`'s object still waits. A direct write of that object would overtake
    /// it, and the older one would then land over the newer: such a write goes through the queue.
    func hasPending(sameTargetAs action: OutboxAction) -> Bool {
        pending.contains { $0.action.target == action.target }
    }

    /// Queues a write that could not be sent now. `key` is the key of the attempt that failed.
    /// A whole-state write replaces a waiting one of the same object (unless that one is in flight).
    /// `mayHaveLanded` says the failed direct attempt went out and lost its answer
    /// (`mayHaveLanded(after:)` of its error): a later write replacing this one accepts its state.
    /// `attemptFailed` says a direct attempt already failed: the write is shown as waiting at once.
    /// Returns the id of the queued write, so a caller can tell later whether that very write was delivered.
    @discardableResult
    func enqueue(
        _ action: OutboxAction, key: String = UUID().uuidString, label: String, mayHaveLanded: Bool = false,
        attemptFailed: Bool = false
    ) -> UUID {
        var action = action
        if action.replacesOlderOfSameTarget {
            for older in pending where older.action.target == action.target && older.id != inFlightID {
                action = action.replacing(older.action, mayHaveLanded: older.mayHaveLanded)
                store.delete(id: older.id)
            }
        }
        return append(
            action, key: key, label: label, createdAt: now(), mayHaveLanded: mayHaveLanded,
            attemptFailed: attemptFailed || mayHaveLanded
        )
    }

    /// Puts back a write carried over from an older queue, with its own key and time.
    func restore(_ action: OutboxAction, key: String, label: String, createdAt: Date) {
        append(action, key: key, label: label, createdAt: createdAt)
    }

    @discardableResult
    private func append(
        _ action: OutboxAction, key: String, label: String, createdAt: Date, mayHaveLanded: Bool = false,
        attemptFailed: Bool = false
    ) -> UUID {
        let id = UUID()
        store.append(
            OutboxWrite(
                id: id, key: key, action: action, label: label, createdAt: createdAt, serverErrors: 0,
                status: .pending, failure: nil, failureKind: nil, mayHaveLanded: mayHaveLanded,
                attemptFailed: attemptFailed
            )
        )
        reload()
        return id
    }

    /// Sends a "not sent" write again at once, as the newest action and without the check that refused
    /// it. The key stays: the server has not recorded it, or a repeat of it is the same write.
    func retry(id: UUID) async {
        guard var write = writes.first(where: { $0.id == id && $0.status == .failed }) else { return }
        write.action = write.action.forcedRetry()
        write.status = .pending
        write.failure = nil
        write.failureKind = nil
        write.serverErrors = 0
        write.attemptFailed = false
        write.createdAt = now()
        store.update(write)
        reload()
        await flush()
    }

    func discard(id: UUID) {
        store.delete(id: id)
        reload()
    }

    /// Takes back a write that has not left the phone: deleted, and nothing is sent. False when it is
    /// being sent right now or is no longer waiting — the server may get it, the caller undoes it there.
    @discardableResult
    func withdraw(id: UUID) -> Bool {
        guard id != inFlightID, pending.contains(where: { $0.id == id }) else { return false }
        discard(id: id)
        return true
    }

    /// Sends the waiting writes without holding the caller: a press is on screen once it is queued.
    func send() {
        Task { await flush() }
    }

    /// What a retry of a "not sent" write would write over: a later write of the same whole-state
    /// object still in the queue. The retry becomes the newest action and lands after it.
    func retryWarning(for write: OutboxWrite) -> String? {
        guard write.action.replacesOlderOfSameTarget,
              let newer = writes.last(where: {
                  $0.id != write.id && $0.action.target == write.action.target && $0.createdAt > write.createdAt
              })
        else { return nil }
        return "Повтор запишет это поверх более новой записи «\(newer.label)»."
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
        var stopped = false
        while let write = store.fetchAll().first(where: { $0.status == .pending && !tried.contains($0.id) }) {
            tried.insert(write.id)
            inFlightID = write.id
            do {
                let reply = try await sender.send(write.action, idempotencyKey: write.key)
                waitsForKey = false
                deliver(write, reply: reply)
            } catch {
                if !settle(write, after: error) {
                    stopped = true
                    break
                }
            }
        }
        reload()
        scheduleRetry(after: stopped)
    }

    private func deliver(_ write: OutboxWrite, reply: OutboxReply?) {
        store.delete(id: write.id)
        reload()
        delivered.send(OutboxDelivery(write: write, reply: reply))
    }

    /// A flush that stopped on a dead network or a 5xx is tried again on a growing pause; one that
    /// emptied the queue resets the pause. A refused key waits for Settings, not for the clock.
    private func scheduleRetry(after stopped: Bool) {
        retryTask?.cancel()
        retryTask = nil
        guard stopped, !waitsForKey, !retryDelays.isEmpty else {
            if !stopped { retryRound = 0 }
            return
        }
        let delay = retryDelays[min(retryRound, retryDelays.count - 1)]
        retryRound += 1
        retryTask = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await self?.flush()
        }
    }

    /// Starts flushing on every reconnect (and on the monitor's first report at launch), and again after
    /// a flush that stopped, on the pauses of `retryDelays`.
    func startAutoFlush(monitor: NetworkPathMonitoring, retryDelays: [Duration] = OutboxQueue.retryDelays) {
        self.monitor = monitor
        self.retryDelays = retryDelays
        monitor.onBecameOnline { [weak self] in
            await self?.flush()
        }
        monitor.start()
    }

    /// Records the failure of `write`. Returns true when the flush may go on to the next write.
    private func settle(_ write: OutboxWrite, after error: Error) -> Bool {
        var settled = write
        settled.attemptFailed = true
        switch Self.outcome(of: error, for: write.action) {
        case .waitForNetwork:
            settled.serverErrors = 0
            settled.mayHaveLanded = settled.mayHaveLanded || Self.mayHaveLanded(after: error)
            store.update(settled)
            return false
        case .waitForKey:
            waitsForKey = true
            settled.serverErrors = 0
            store.update(settled)
            return false
        case .serverError(let status):
            settled.serverErrors += 1
            settled.mayHaveLanded = settled.mayHaveLanded || Self.mayHaveLanded(after: error)
            if settled.serverErrors >= Self.maxServerErrorAttempts {
                settled.status = .failed
                settled.failure = "Сервер \(settled.serverErrors) раз подряд ответил ошибкой \(status)."
                settled.failureKind = .serverErrors
                refuse(settled)
                return true
            }
            store.update(settled)
            return false
        case .refused(let reason, let kind):
            settled.status = .failed
            settled.failure = reason
            settled.failureKind = kind
            refuse(settled)
            return true
        case .delivered:
            deliver(write, reply: nil)
            return true
        }
    }

    private func refuse(_ write: OutboxWrite) {
        store.update(write)
        reload()
        refused.send(write)
    }

    private enum Outcome {
        case waitForNetwork
        case waitForKey
        case serverError(Int)
        case refused(String, OutboxFailureKind)
        case delivered
    }

    /// Whether a failed attempt may still have reached the server: its answer was lost on the way
    /// (a timeout, a dropped connection, a proxy's 502 or 504 in front of a backend that may have
    /// written), rather than the request never leaving (no connection, no host, a failed TLS handshake).
    nonisolated static func mayHaveLanded(after error: Error) -> Bool {
        switch error as? APIClientError {
        case .timeout?:
            return true
        case .transport(let code)?:
            return !neverLeftCodes.contains(code)
        case .unexpectedStatus(let status)?:
            return proxyStatuses.contains(status)
        default:
            return false
        }
    }

    /// A proxy's answers when the backend behind it did not answer in time: the write may be there.
    nonisolated private static let proxyStatuses: Set<Int> = [502, 504]

    nonisolated private static let neverLeftCodes: Set<Int> = [
        URLError.notConnectedToInternet.rawValue, URLError.cannotConnectToHost.rawValue,
        URLError.cannotFindHost.rawValue, URLError.dnsLookupFailed.rawValue,
        // The handshake failed: no request body is sent before it completes.
        URLError.secureConnectionFailed.rawValue,
    ]

    private static func outcome(of error: Error, for action: OutboxAction) -> Outcome {
        if let conflict = error as? OutboxConflict { return .refused(conflict.reason, .changedOnServer) }
        guard let apiError = error as? APIClientError else { return .waitForNetwork }
        switch apiError {
        case .timeout, .transport, .invalidBaseURL:
            return .waitForNetwork
        case .unauthorized:
            return .waitForKey
        case .invalidResponse:
            // The write request answered 2xx with a body this app could not read: the write is there.
            // (A replay check that cannot read the server's state throws `OutboxConflict` instead.)
            return .delivered
        case .unexpectedStatus(let status):
            switch status {
            case 408, 429: return .waitForNetwork
            case 500...: return .serverError(status)
            case 409: return conflict(for: action)
            case 422 where action.pressMoment != nil: return .refused(pressTimeRefusedReason, .dayTurned)
            case 404: return .refused("Сервер не нашёл, куда записать (404): объект удалён.", .refused)
            case 400, 422: return .refused("Сервер не принял данные (\(status)).", .refused)
            default: return .refused("Сервер отказал (\(status)).", .refused)
            }
        }
    }

    /// A 409 is a server-side rule saying no. A press that carried its day: the day turned or the button
    /// is off (the status alone does not tell). A press without a day: the button is off.
    private static func conflict(for action: OutboxAction) -> Outcome {
        if case .markSupplementTaken(let intake) = action {
            return intake.intakeDate == nil
                ? .refused(supplementArchivedReason, .refused) : .refused(supplementDayTurnedReason, .dayTurned)
        }
        guard case .tapQuickMark(let tap) = action else {
            return .refused("Сервер отказал (409): запись противоречит тому, что уже есть на сервере.", .refused)
        }
        return tap.serverDay == nil ? .refused(tapRefusedReason, .refused) : .refused(dayTurnedReason, .dayTurned)
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
        // Set only once the on-disk store opened: importing the old queues into memory would lose them.
        var directory: URL?
        do {
            let support = try FileManager.default.url(
                for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true
            )
            store = try SwiftDataOutboxStore(url: support.appendingPathComponent(fileName))
            directory = support
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
