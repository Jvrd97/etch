// [review:need-review] PHASE-01/210, PHASE-03/225, PHASE-03/236, PHASE-03/242
// summary: state of the quick-mark buttons — the directory through the read cache (read alongside the queue's send, not after it; an answer older than the one on screen is dropped and the cache keeps the newer directory), one POST per tap that repaints the button from its own answer, an offline tap queued in the shared outbox under the same key with the moment of the press and shown at once, the buttons redrawn whenever the queue changes and their waiting presses said to VoiceOver, undo of the last tap or of a named set, and a word to the screen when a day moved
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — an appearance after midnight reads again whatever the age of the directory; the cache takes no answer of a server the address moved away from
// summary: PHASE-03/310 — the buttons open from the cached directory of today (no loader), an appearance reads again only when the directory is not recent, a re-read keeps the buttons and says its failure as a line
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 round 2 — a delivered press is laid over every directory read sent before its delivery (a read in flight is shown, not dropped; the cache keeps what the buttons show, with the stamp of its read) until a read sent after it is shown; an undo asked while the press was on its way withdraws it once it waits again, or takes it back on the server once it lands; VoiceOver counts only presses that wait
// summary: PHASE-03/316 — a press is queued under its own key with its moment and drawn at once, the send runs behind; a delivery repaints the button from the server's answer and arms the undo with its event, a refusal takes the press away and says why; undo of a press not sent yet withdraws it from the queue without a request, of one on its way takes it back once it lands
import Combine
import Foundation

@MainActor
final class QuickMarksViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    /// The directory in the order the server decided: planned buttons first.
    @Published private(set) var marks: [QuickMarkDTO] = []
    /// Non-nil while the directory shown is the cached one; the moment it was cached.
    @Published private(set) var offlineAsOf: Date?
    /// The press the undo chip takes back: still in the queue, or answered by the server.
    enum LastPress: Equatable {
        case queued(writeID: UUID, markID: Int)
        case landed(QuickMarkEventDTO)
    }

    /// The press that can still be taken back, or nil when none can.
    @Published private(set) var lastPress: LastPress?
    /// The server's answer to that press, once it has one.
    var lastEvent: QuickMarkEventDTO? {
        if case .landed(let event)? = lastPress { return event }
        return nil
    }
    @Published var errorMessage: String?

    /// A tap or an undo went through (or a queued tap was delivered): the day of this category
    /// moved. The buttons repaint on their own; the records and streaks beside them are another
    /// screen's state, and a screen that is not told keeps showing the day as it was.
    var onDayChanged: ((Int) -> Void)?

    static let notConfiguredMessage = "Set the server address in Settings"
    static let tapFailedMessage = "Отметку записать не удалось."
    static let undoFailedMessage = "Отменить отметку не удалось."
    static let cacheKey = "today.quickmarks"

    private let apiProvider: () -> QuickMarksAPI?
    private let cache: ReadThroughCache
    private let outbox: OutboxQueue
    private let timeZone: TimeZone
    private let now: () -> Date
    private var cancellables: Set<AnyCancellable> = []
    /// The directory as the server (or the cache) gave it; `marks` is it with the waiting presses on top.
    private var serverMarks: [QuickMarkDTO] = []
    /// Directory reads, numbered as they are sent, and the newest one shown. A load reads alongside the
    /// queue's send, so its answer may come back after the re-read a delivery started: an answer older
    /// than the one on screen is dropped, or a delivered press would vanish from the total.
    private var readsSent = 0
    private var readShown = 0
    /// A press whose undo was asked while it was on its way: withdrawn once it waits again, or taken back
    /// on the server once it lands.
    private var undoOnDelivery: UUID?
    /// Presses the server took, with the newest directory read sent before each delivery: a read up to that
    /// number may not count the press, so its answer gets the press's total laid over it.
    private var deliveredEvents: [(afterRead: Int, event: QuickMarkEventDTO)] = []

    init(
        apiProvider: @escaping () -> QuickMarksAPI?,
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
        api: QuickMarksAPI,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(
            apiProvider: { api }, cacheStore: cacheStore, outbox: outbox, timeZone: timeZone,
            now: now
        )
    }

    static func live() -> QuickMarksViewModel {
        QuickMarksViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared,
            outbox: OutboxLive.shared
        )
    }

    /// The categories a button answers for. The legacy card of such a category is dropped from
    /// Today: two ways to add to the same field on one screen is one too many.
    var coveredCategoryIDs: Set<Int> {
        Set(marks.map(\.categoryId))
    }

    /// What the undo chip says, or nil when there is nothing to take back. Names the button,
    /// because the chip sits under a row of them.
    var undoCaption: String? {
        let markID: Int
        switch lastPress {
        case .queued(_, let id)?: markID = id
        case .landed(let event)?: markID = event.quickMarkId
        case nil: return nil
        }
        guard let mark = marks.first(where: { $0.id == markID }) else { return nil }
        return "Отменить «\(mark.label)»"
    }

    /// What VoiceOver says about presses of the button still waiting in the queue; nil when none wait.
    /// The "+1" on the button is drawn, not spoken, and a waiting press is not yet on the server.
    func waitingCaption(of markID: Int) -> String? {
        let moment = now()
        let waiting = outbox.pending.filter { $0.tapMarkID == markID && $0.isOverdue(at: moment) }.count
        return waiting > 0 ? "ждёт отправки: \(waiting)" : nil
    }

    /// Any change of the queue (a press queued, refused, discarded) redraws the buttons; a delivered
    /// press repaints its button from the server's answer and says which day moved; a refused one says why.
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
                guard write.tapMarkID != nil else { return }
                MainActor.assumeIsolated {
                    // A press the person already undid says nothing about its refusal.
                    guard let self, write.id != self.undoOnDelivery else { return }
                    self.errorMessage = write.failure ?? Self.tapFailedMessage
                    if case .queued(write.id, _)? = self.lastPress { self.lastPress = nil }
                }
            }
            .store(in: &cancellables)
    }

    /// The server took a press: in the same turn as the queue dropped it, the button takes the server's
    /// total (the presses still waiting stay on top), and the undo chip of that press gets its event. A
    /// directory read already on its way may not count the press: the total is laid over its answer. The
    /// cache takes the new total. A button not on screen yet, or an answer this app could not read, reads
    /// the directory instead.
    private func settle(_ delivery: OutboxDelivery) {
        guard let categoryID = delivery.write.tapCategoryID else { return }
        let writeID = delivery.write.id
        var event: QuickMarkEventDTO?
        if case .quickMarkEvent(let answer)? = delivery.reply { event = answer }
        if let event, serverMarks.contains(where: { $0.id == event.quickMarkId }) {
            deliveredEvents.append((afterRead: readsSent, event: event))
            replace(markID: event.quickMarkId) { $0.applying(event) }
            cacheShown(sentUnder: cache.scope)
            onDayChanged?(categoryID)
        } else {
            Task { await reconcileAfterFlush(categoryIDs: [categoryID]) }
        }
        if let event, undoOnDelivery == writeID {
            undoOnDelivery = nil
            Task {
                if let refusal = await undoEvent(event.eventId) { errorMessage = refusal }
            }
        } else if case .queued(writeID, _)? = lastPress {
            lastPress = event.map(LastPress.landed)
        }
    }

    // MARK: Loading

    /// The screen came on: the cached directory goes on screen at once, the server is asked only when it is not recent.
    func appear() async {
        showCached()
        // Past midnight the totals on screen are yesterday's, however recent the read.
        let showsToday = serverMarks.allSatisfy { $0.entryDate == localToday }
        if state == .loaded, showsToday, cache.isRecent(key: Self.cacheKey) { return }
        await load()
    }

    /// Puts the cached directory on screen while nothing is shown, without the network. Totals of another
    /// day are not today's: the buttons wait for the server then.
    func showCached() {
        guard state != .loaded,
              let cached = cache.peek([QuickMarkDTO].self, key: Self.cacheKey),
              cached.value.allSatisfy({ $0.entryDate == localToday }) else { return }
        show(cached.value, read: nil)
        state = .loaded
    }

    private var localToday: String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: now())
    }

    func load() async {
        // Buttons already on screen stay while they are read again.
        let showsData = state == .loaded
        if !showsData { state = .loading }
        guard let api = apiProvider() else {
            fail(Self.notConfiguredMessage, showsData: showsData)
            return
        }
        // The waiting presses go out alongside the read, not before it: a slow or dead network must
        // not hold the buttons back. They are drawn over the directory until delivered, and a delivery
        // reads the directory again (`reconcileAfterFlush`).
        let flushing = Task { await outbox.flush() }
        let read = nextRead()
        let sentUnder = cache.scope
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                try await api.fetchQuickMarks()
            }
            if isNewest(read) {
                switch outcome {
                case .fresh(let directory):
                    offlineAsOf = nil
                    show(directory, read: read)
                    // The cache took the bare answer; the buttons show it with the presses delivered meanwhile.
                    if !deliveredEvents.isEmpty { cacheShown(sentUnder: sentUnder) }
                case .stale(let directory, let updatedAt):
                    offlineAsOf = updatedAt
                    show(directory, read: read)
                }
            } else if case .fresh = outcome {
                // The cache took this older answer: put back the directory a later read put on screen.
                cache.save(serverMarks, forKey: Self.cacheKey, updatedAt: cache.now(), sentUnder: sentUnder)
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

    /// A delivered queue changed the server's totals: read the directory again and tell the screen
    /// which days moved.
    func reconcileAfterFlush(categoryIDs: [Int]) async {
        guard let api = apiProvider() else { return }
        let read = nextRead()
        let sentUnder = cache.scope
        if let directory = try? await api.fetchQuickMarks(), isNewest(read) {
            offlineAsOf = nil
            show(directory, read: read)
            cache.save(serverMarks, forKey: Self.cacheKey, updatedAt: cache.now(), sentUnder: sentUnder)
        }
        categoryIDs.forEach { onDayChanged?($0) }
    }

    private func nextRead() -> Int {
        readsSent += 1
        return readsSent
    }

    /// Whether the answer of `read` may go on screen: only one newer than what is shown.
    private func isNewest(_ read: Int) -> Bool {
        guard read > readShown else { return false }
        readShown = read
        return true
    }

    /// Puts a directory on screen with the presses delivered after its read was sent laid over it, in the
    /// order they landed. A read sent after a delivery counts that press: its overlay is dropped. `read` is
    /// nil for the cached directory, which keeps every overlay.
    private func show(_ directory: [QuickMarkDTO], read: Int?) {
        if let read { deliveredEvents.removeAll { $0.afterRead < read } }
        serverMarks = deliveredEvents.map(\.event).reduce(directory) { marks, event in
            marks.map { $0.id == event.quickMarkId ? $0.applying(event) : $0 }
        }
        redraw(outbox.writes)
    }

    /// The cache gets the buttons as shown, keeping the stamp of the read it holds: laying a delivered press
    /// over it does not make the rest of the directory any younger.
    private func cacheShown(sentUnder: String) {
        let stamp = cache.store.load([QuickMarkDTO].self, forKey: Self.cacheKey)?.updatedAt ?? cache.now()
        cache.save(serverMarks, forKey: Self.cacheKey, updatedAt: stamp, sentUnder: sentUnder)
    }

    /// Presses still waiting in the queue are laid over the directory, so a cached or just-read
    /// total does not swallow them. A press in the "not sent" list is not counted: it has not landed.
    private func redraw(_ writes: [OutboxWrite]) {
        if undoOnDelivery != nil {
            // Not from inside the queue's publication: the withdrawal changes the queue itself.
            Task { self.withdrawUndonePress() }
        }
        let waiting = writes.filter { $0.status == .pending }.compactMap(\.tapMarkID)
        marks = serverMarks.map { mark in
            waiting.filter { $0 == mark.id }.reduce(mark) { folded, _ in
                folded.afterOfflineTap()
            }
        }
    }

    // MARK: Taps

    /// Records one tap: queued under a key of its own with the moment it was made, drawn on the button
    /// at once, and sent behind the caller; the server's answer repaints the button when it comes. The
    /// server puts the press on the day that moment belongs to by its own boundary (04:00), so neither
    /// the list's day nor the phone's calendar has to guess it, however late it is delivered.
    func tap(_ mark: QuickMarkDTO) async {
        errorMessage = nil
        guard apiProvider() != nil else {
            errorMessage = Self.notConfiguredMessage
            return
        }
        let pressed = now()
        let writeID = outbox.enqueue(
            .tapQuickMark(
                QueuedTap(
                    quickMarkId: mark.id, categoryId: mark.categoryId,
                    utcOffsetMinutes: timeZone.secondsFromGMT(for: pressed) / 60,
                    serverDay: nil, occurredAt: pressed
                )
            ),
            label: mark.label
        )
        lastPress = .queued(writeID: writeID, markID: mark.id)
        outbox.send()
    }

    // MARK: Undo

    /// A press whose undo was asked while it was on its way and that waits again (its send failed): it is
    /// withdrawn now. One refused by the server is dropped from the "not sent" list: it was undone.
    private func withdrawUndonePress() {
        guard let writeID = undoOnDelivery else { return }
        if outbox.withdraw(id: writeID) {
            undoOnDelivery = nil
        } else if outbox.failed.contains(where: { $0.id == writeID }) {
            outbox.discard(id: writeID)
            undoOnDelivery = nil
        }
    }

    /// Takes the last tap back: one action, no trip to the entry editor. A press that has not left the
    /// phone is withdrawn from the queue without a request; one on its way is taken back once it lands.
    func undoLast() async {
        switch lastPress {
        case .queued(let writeID, _)?:
            lastPress = nil
            if !outbox.withdraw(id: writeID) { undoOnDelivery = writeID }
        case .landed(let event)?:
            if let refusal = await undoEvent(event.eventId) {
                errorMessage = refusal
            }
        case nil:
            return
        }
    }

    /// Takes one named tap back — a row of the day's list, not necessarily the last tap of the
    /// session. Returns the reason when the server refuses, for the list that asked to show where the
    /// reader is looking; nil once the tap is gone.
    func undoEvent(_ eventID: Int) async -> String? {
        guard let api = apiProvider() else { return Self.notConfiguredMessage }
        defer {
            // The offer is spent for this tap either way: a success took it back, a refusal means it
            // is no longer the last one, and a chip that answers 409 forever is worse than none.
            if lastEvent?.eventId == eventID { lastPress = nil }
        }
        do {
            let undone = try await api.undoQuickMarkEvent(id: eventID)
            // A read older than the undo must not bring the press back.
            deliveredEvents.removeAll { $0.event.eventId == eventID }
            replace(markID: undone.quickMarkId) { $0.applying(undone) }
            if let mark = marks.first(where: { $0.id == undone.quickMarkId }) {
                onDayChanged?(mark.categoryId)
            }
            return nil
        } catch let error as APIClientError {
            return error.userMessage
        } catch {
            return Self.undoFailedMessage
        }
    }

    private func replace(markID: Int, _ transform: (QuickMarkDTO) -> QuickMarkDTO) {
        guard let index = serverMarks.firstIndex(where: { $0.id == markID }) else { return }
        serverMarks[index] = transform(serverMarks[index])
        redraw(outbox.writes)
    }
}

private extension OutboxWrite {
    var tapMarkID: Int? {
        if case .tapQuickMark(let tap) = action { return tap.quickMarkId }
        return nil
    }

    var tapCategoryID: Int? {
        if case .tapQuickMark(let tap) = action { return tap.categoryId }
        return nil
    }
}
