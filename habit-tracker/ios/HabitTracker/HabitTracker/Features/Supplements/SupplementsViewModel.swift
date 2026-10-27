// [review:need-review] PHASE-03/240
// summary: state of the Supplements screen — the list through the read cache (a cached list from another day does not claim «принял сегодня»; reads are numbered and an answer older than the one on screen is dropped), «принял» as one POST under an Idempotency-Key that an offline press queues in the shared outbox under the same key with the day of the press and shows at once, rows redrawn whenever the queue changes, a delivered press re-reads the list, and adding a supplement (needs the network); no name or dose is ever logged
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
        let isWaiting: Bool

        var id: Int { supplement.id }
    }

    /// What the read cache keeps: the list and the day it was read for. `takenToday` of another day is not today's.
    struct Snapshot: Codable, Equatable {
        let day: String
        let items: [SupplementDTO]
    }

    static let cacheKey = "supplements.list"

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var rows: [Row] = []
    /// Non-nil while the list shown is the cached one; the moment it was cached.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last press or add was refused, in words; the screen shows it above the list.
    @Published var errorMessage: String?
    @Published private(set) var isSaving = false

    private let apiProvider: () -> SupplementsAPI?
    private let cache: ReadThroughCache
    private let outbox: OutboxQueue
    private let timeZone: TimeZone
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
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.outbox = outbox ?? OutboxQueue(store: InMemoryOutboxStore())
        self.timeZone = timeZone
        self.now = now
        bindOutbox()
    }

    convenience init(
        api: SupplementsAPI,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, outbox: outbox, timeZone: timeZone, now: now)
    }

    static func live() -> SupplementsViewModel {
        SupplementsViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared,
            outbox: OutboxLive.shared
        )
    }

    // MARK: Loading

    func load() async {
        // A list already on screen stays while it is read again: pull to refresh must not cancel itself.
        if state != .loaded { state = .loading }
        guard let api = apiProvider() else {
            state = .failure(SupplementsFormat.notConfiguredMessage)
            return
        }
        // The waiting presses go out alongside the read, not before it: a dead network must not hold
        // the list back. A delivery reads the list again.
        let flushing = Task { await outbox.flush() }
        let read = nextRead()
        let today = today()
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                Snapshot(day: today, items: try await api.fetchSupplements())
            }
            if isNewest(read) {
                switch outcome {
                case .fresh(let snapshot):
                    offlineAsOf = nil
                    show(snapshot.items)
                case .stale(let snapshot, let updatedAt):
                    offlineAsOf = updatedAt
                    show(snapshot.day == today ? snapshot.items : snapshot.items.map { $0.taken(false) })
                }
            }
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
        await flushing.value
    }

    /// A delivered press changed what the server holds: read the list again, quietly.
    private func reconcileAfterFlush() async {
        guard let api = apiProvider() else { return }
        let read = nextRead()
        let today = today()
        if let items = try? await api.fetchSupplements(), isNewest(read) {
            offlineAsOf = nil
            show(items)
            cache.store.save(Snapshot(day: today, items: items), forKey: Self.cacheKey, updatedAt: now())
        }
    }

    private func bindOutbox() {
        outbox.$writes
            .sink { [weak self] writes in
                MainActor.assumeIsolated { self?.redraw(writes) }
            }
            .store(in: &cancellables)
        outbox.delivered
            .sink { [weak self] writes in
                guard writes.contains(where: { $0.supplementID != nil }) else { return }
                Task { await self?.reconcileAfterFlush() }
            }
            .store(in: &cancellables)
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
        SupplementsFormat.logicalDay(of: now(), timeZone: timeZone)
    }

    private func show(_ items: [SupplementDTO]) {
        serverItems = items
        redraw(outbox.writes)
    }

    /// A press still waiting counts as taken. One in the "not sent" list does not: it has not landed.
    private func redraw(_ writes: [OutboxWrite]) {
        let waiting = Set(writes.filter { $0.status == .pending }.compactMap(\.supplementID))
        rows = serverItems.map { item in
            let isWaiting = waiting.contains(item.id) && !item.takenToday
            return Row(supplement: item, isTaken: item.takenToday || isWaiting, isWaiting: isWaiting)
        }
    }

    // MARK: Taking

    /// «Принял сегодня». One POST; the server decides the day. Without a network the press is queued
    /// under the key of this attempt with the day of the press, and shown at once.
    func markTaken(_ supplement: SupplementDTO) async {
        errorMessage = nil
        guard rows.first(where: { $0.id == supplement.id })?.isTaken != true else { return }
        guard let api = apiProvider() else {
            errorMessage = SupplementsFormat.notConfiguredMessage
            return
        }
        let key = UUID().uuidString
        let pressed = now()
        do {
            _ = try await api.markIntake(supplementID: supplement.id, intakeDate: nil, idempotencyKey: key)
            replace(supplement.id) { $0.taken(true) }
            cache.store.save(Snapshot(day: today(), items: serverItems), forKey: Self.cacheKey, updatedAt: now())
        } catch let error as APIClientError where error.isConnectivity {
            queue(supplement, key: key, pressed: pressed, mayHaveLanded: OutboxQueue.mayHaveLanded(after: error))
        } catch let error as APIClientError {
            errorMessage = SupplementsFormat.message(forMark: error)
        } catch {
            errorMessage = SupplementsFormat.markFailedMessage
        }
    }

    private func queue(_ supplement: SupplementDTO, key: String, pressed: Date, mayHaveLanded: Bool) {
        outbox.enqueue(
            .markSupplementTaken(
                QueuedSupplementIntake(
                    supplementId: supplement.id,
                    intakeDate: SupplementsFormat.logicalDay(of: pressed, timeZone: timeZone),
                    pressedAt: pressed
                )
            ),
            key: key, label: SupplementsFormat.queueLabel(supplement), mayHaveLanded: mayHaveLanded
        )
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
        do {
            let created = try await api.createSupplement(payload)
            serverItems.append(created)
            redraw(outbox.writes)
            cache.store.save(Snapshot(day: today(), items: serverItems), forKey: Self.cacheKey, updatedAt: now())
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
