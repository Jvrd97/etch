// [review:need-review] PHASE-03/240, PHASE-03/258
// summary: the server's day rule (zone + day-start hour, read with the list and kept in the cache; the day is cut by wall clock), a waiting press of another day does not count as taken today, a press in flight disables its button, a dropped old answer does not stay in the cache, the moment the day turns; state of the Supplements screen — the list through the read cache (a cached list from another day does not claim «принял сегодня»; reads are numbered and an answer older than the one on screen is dropped), «принял» as one POST under an Idempotency-Key that an offline press queues in the shared outbox under the same key with the day of the press and shows at once, rows redrawn whenever the queue changes, a delivered press re-reads the list, and adding a supplement (needs the network); no name or dose is ever logged
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — the cache takes no answer of a server the address moved away from
// summary: PHASE-03/310 — the list opens from its cached copy (a copy of another day without «принял»), an appearance reads again only when the copy is not recent, a re-read of a shown list says its failure as a line
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 — «принял» is queued under its own key with the day of the press and shows as taken at once, the send runs behind; «ждёт отправки» shows only a press that waits; a delivery of today's intake marks the row from the answer without a re-read, a refusal takes the mark away and says why
import Combine
import Foundation

@MainActor
final class SupplementsViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    /// One line of the list: the supplement, whether it counts as taken today, and whether that press
    /// still waits in the queue for the network.
    struct Row: Identifiable, Equatable {
        let supplement: SupplementDTO
        let isTaken: Bool
        /// When the press that waits in the queue was made — it failed once or has been on its way past
        /// the quiet period; nil when nothing waits.
        let waitingSince: Date?

        var isWaiting: Bool { waitingSince != nil }

        var id: Int { supplement.id }
    }

    /// What the read cache keeps: the list and the day it was read for. `takenToday` of another day is not today's.
    struct Snapshot: Codable, Equatable {
        let day: String
        let items: [SupplementDTO]
        /// The rule the day was cut by; absent in a snapshot written before the rule was kept.
        var rule: ServerDayRule?
    }

    static let cacheKey = "supplements.list"

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var rows: [Row] = []
    /// Non-nil while the list shown is the cached one; the moment it was cached.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last press or add was refused, in words; the screen shows it above the list.
    @Published var errorMessage: String?
    @Published private(set) var isSaving = false
    /// The server's day rule: from its answer, else from the cache, else the phone's zone with the 04:00 default.
    @Published private(set) var rule: ServerDayRule

    private let apiProvider: () -> SupplementsAPI?
    private let cache: ReadThroughCache
    private let outbox: OutboxQueue
    private let now: () -> Date
    private var cancellables: Set<AnyCancellable> = []
    /// The list as the server (or the cache) gave it; `rows` is it with the waiting presses on top.
    private var serverItems: [SupplementDTO] = []
    /// Reads, numbered as they are sent, and the newest one shown: a load reads alongside the queue's
    /// send, so its answer may come after the re-read a delivery started.
    private var readsSent = 0
    private var readShown = 0

    init(
        apiProvider: @escaping () -> SupplementsAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        rule: ServerDayRule = .phone,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.outbox = outbox ?? OutboxQueue(store: InMemoryOutboxStore())
        self.rule = rule
        self.now = now
        bindOutbox()
    }

    convenience init(
        api: SupplementsAPI,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        rule: ServerDayRule = .phone,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, outbox: outbox, rule: rule, now: now)
    }

    static func live() -> SupplementsViewModel {
        SupplementsViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared,
            outbox: OutboxLive.shared
        )
    }

    // MARK: Loading

    /// The screen came on: the cached list goes on screen at once, the server is asked only when it is not recent.
    func appear() async {
        showCached()
        if state == .loaded, cache.isRecent(key: Self.cacheKey) { return }
        await load()
    }

    /// Puts the cached list on screen while nothing is shown, without the network. A list of another day
    /// does not claim «принял сегодня».
    func showCached() {
        guard state != .loaded, let cached = cache.peek(Snapshot.self, key: Self.cacheKey) else { return }
        adopt(cached.value.rule)
        show(cached.value.day == today() ? cached.value.items : cached.value.items.map { $0.taken(false) })
        state = .loaded
    }

    func load() async {
        // A list already on screen stays while it is read again: pull to refresh must not cancel itself.
        let showsData = state == .loaded
        if !showsData { state = .loading }
        guard let api = apiProvider() else {
            fail(SupplementsFormat.notConfiguredMessage, showsData: showsData)
            return
        }
        // The waiting presses go out alongside the read, not before it: a dead network must not hold
        // the list back. A delivery reads the list again.
        let flushing = Task { await outbox.flush() }
        let read = nextRead()
        let sentUnder = cache.scope
        let known = rule
        let clock = now
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                // The rule rides along with the list; a rule that cannot be read leaves the known one.
                async let fetched = try? api.fetchDayRule()
                let items = try await api.fetchSupplements()
                let ruleNow = await fetched ?? known
                return Snapshot(
                    day: SupplementsFormat.logicalDay(of: clock(), rule: ruleNow), items: items, rule: ruleNow
                )
            }
            if isNewest(read) {
                switch outcome {
                case .fresh(let snapshot):
                    offlineAsOf = nil
                    adopt(snapshot.rule)
                    show(snapshot.items)
                case .stale(let snapshot, let updatedAt):
                    offlineAsOf = updatedAt
                    adopt(snapshot.rule)
                    show(snapshot.day == today() ? snapshot.items : snapshot.items.map { $0.taken(false) })
                }
            } else if case .fresh = outcome {
                // The cache took an answer older than the one on screen: put the shown list back.
                saveShown(sentUnder: sentUnder)
            }
            state = .loaded
            if let line = refreshFailureLine, errorMessage == line { errorMessage = nil }
            refreshFailureLine = nil
        } catch let error as APIClientError {
            fail(error.userMessage, showsData: showsData)
        } catch {
            fail("Unexpected error", showsData: showsData)
        }
        await flushing.value
    }

    /// The line a failed re-read wrote, so the next re-read that works takes back that line and no other.
    private var refreshFailureLine: String?

    private func fail(_ message: String, showsData: Bool) {
        guard showsData else {
            state = .failure(message)
            return
        }
        errorMessage = message
        refreshFailureLine = message
    }

    /// A delivered press changed what the server holds: read the list again, quietly.
    private func reconcileAfterFlush() async {
        guard let api = apiProvider() else { return }
        let read = nextRead()
        let sentUnder = cache.scope
        if let items = try? await api.fetchSupplements(), isNewest(read) {
            offlineAsOf = nil
            show(items)
            saveShown(sentUnder: sentUnder)
        }
    }

    private func bindOutbox() {
        outbox.$writes
            .sink { [weak self] writes in
                MainActor.assumeIsolated { self?.redraw(writes) }
            }
            .store(in: &cancellables)
        outbox.delivered
            .sink { [weak self] delivery in
                MainActor.assumeIsolated { self?.settle(delivery) }
            }
            .store(in: &cancellables)
        outbox.refused
            .sink { [weak self] write in
                guard write.supplementID != nil else { return }
                MainActor.assumeIsolated { self?.errorMessage = write.failure ?? SupplementsFormat.markFailedMessage }
            }
            .store(in: &cancellables)
    }

    /// The server took a press: an intake of today marks its row from the answer, in the same turn as the
    /// queue dropped the press, and a read already on its way predates it and is not shown. An intake of
    /// another day, or an answer this app could not read, reads the list again.
    private func settle(_ delivery: OutboxDelivery) {
        guard let id = delivery.write.supplementID else { return }
        guard case .supplementIntake(let intake)? = delivery.reply, intake.intakeDate == today() else {
            Task { await reconcileAfterFlush() }
            return
        }
        readShown = readsSent
        replace(id) { $0.taken(true) }
        saveShown(sentUnder: cache.scope)
    }

    private func nextRead() -> Int {
        readsSent += 1
        return readsSent
    }

    private func isNewest(_ read: Int) -> Bool {
        guard read > readShown else { return false }
        readShown = read
        return true
    }

    private func today() -> String {
        SupplementsFormat.logicalDay(of: now(), rule: rule)
    }

    private func adopt(_ learned: ServerDayRule?) {
        if let learned, learned != rule { rule = learned }
    }

    private func saveShown(sentUnder: String) {
        cache.save(
            Snapshot(day: today(), items: serverItems, rule: rule), forKey: Self.cacheKey, updatedAt: now(), sentUnder: sentUnder
        )
    }

    /// Seconds until the server's day turns, for the timer that re-reads the screen; nil if it cannot be told.
    func secondsUntilDayTurn() -> TimeInterval? {
        let moment = now()
        return SupplementsFormat.nextDayTurn(after: moment, rule: rule).map { $0.timeIntervalSince(moment) }
    }

    /// The form closed or the screen moved on: an old refusal must not greet the next visit.
    func clearError() {
        errorMessage = nil
    }

    private func show(_ items: [SupplementDTO]) {
        serverItems = items
        redraw(outbox.writes)
    }

    /// A press still queued counts as taken today when it is for today (or for no day: the server decides).
    /// A press of another day does not, and neither does one in the "not sent" list: it has not landed.
    /// Only a press that waits says «ждёт отправки»; one merely on its way is shown as taken.
    private func redraw(_ writes: [OutboxWrite]) {
        let today = today()
        let moment = now()
        var queued: Set<Int> = []
        var waiting: [Int: Date] = [:]
        for write in writes where write.status == .pending {
            guard case .markSupplementTaken(let intake) = write.action,
                  intake.intakeDate == nil || intake.intakeDate == today
            else { continue }
            queued.insert(intake.supplementId)
            guard write.isOverdue(at: moment) else { continue }
            waiting[intake.supplementId] = min(waiting[intake.supplementId] ?? intake.pressedAt, intake.pressedAt)
        }
        rows = serverItems.map { item in
            Row(
                supplement: item, isTaken: item.takenToday || queued.contains(item.id),
                waitingSince: item.takenToday ? nil : waiting[item.id]
            )
        }
    }

    // MARK: Taking

    /// «Принял сегодня». Queued under a key of its own with the day of the press (a clock check: a server
    /// on another day refuses instead of writing the wrong day), shown as taken at once, and sent behind
    /// the caller.
    func markTaken(_ supplement: SupplementDTO) async {
        errorMessage = nil
        guard let current = rows.first(where: { $0.id == supplement.id }), !current.isTaken else { return }
        guard apiProvider() != nil else {
            errorMessage = SupplementsFormat.notConfiguredMessage
            return
        }
        let pressed = now()
        outbox.enqueue(
            .markSupplementTaken(
                QueuedSupplementIntake(
                    supplementId: supplement.id,
                    intakeDate: SupplementsFormat.logicalDay(of: pressed, rule: rule),
                    pressedAt: pressed
                )
            ),
            label: SupplementsFormat.queueLabel(supplement)
        )
        outbox.send()
    }

    private func replace(_ id: Int, _ transform: (SupplementDTO) -> SupplementDTO) {
        guard let index = serverItems.firstIndex(where: { $0.id == id }) else { return }
        serverItems[index] = transform(serverItems[index])
        redraw(outbox.writes)
    }

    // MARK: Adding

    /// Adds a supplement. Returns true once the server has it, for the form that asked to close.
    /// The reason it did not is in `errorMessage`.
    func add(_ draft: SupplementDraft) async -> Bool {
        errorMessage = nil
        let payload: SupplementCreateDTO
        switch SupplementsFormat.payload(from: draft) {
        case .success(let valid): payload = valid
        case .failure(let invalid):
            errorMessage = invalid.message
            return false
        }
        guard let api = apiProvider() else {
            errorMessage = SupplementsFormat.notConfiguredMessage
            return false
        }
        isSaving = true
        defer { isSaving = false }
        let sentUnder = cache.scope
        do {
            let created = try await api.createSupplement(payload)
            serverItems.append(created)
            redraw(outbox.writes)
            saveShown(sentUnder: sentUnder)
            return true
        } catch let error as APIClientError where error.isConnectivity {
            errorMessage = SupplementsFormat.addNeedsNetworkMessage
        } catch let error as APIClientError {
            errorMessage = error.userMessage
        } catch {
            errorMessage = SupplementsFormat.addFailedMessage
        }
        return false
    }
}

extension SupplementDTO {
    fileprivate func taken(_ taken: Bool) -> SupplementDTO {
        var copy = self
        copy.takenToday = taken
        return copy
    }
}

private extension OutboxWrite {
    var supplementID: Int? {
        if case .markSupplementTaken(let intake) = action { return intake.supplementId }
        return nil
    }
}
