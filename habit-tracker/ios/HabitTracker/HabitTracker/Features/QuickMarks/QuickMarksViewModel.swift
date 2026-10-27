// [review:need-review] PHASE-01/210, PHASE-03/225
// summary: state of the quick-mark buttons — the directory through the read cache, one POST per tap that repaints the button from its own answer, an offline tap queued in the shared outbox under the same key (pinned to the list's day only when that is the local day of the press) and shown at once, the buttons redrawn whenever the queue changes, undo of the last tap or of a named set, and a word to the screen when a day moved
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
    /// The tap that can still be taken back, or nil when none can.
    @Published private(set) var lastEvent: QuickMarkEventDTO?
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
        guard let lastEvent, let mark = marks.first(where: { $0.id == lastEvent.quickMarkId }) else {
            return nil
        }
        return "Отменить «\(mark.label)»"
    }

    /// Any change of the queue (a press queued, refused, discarded) redraws the buttons; a delivered
    /// press moved the day of its category: read the totals again and say which days moved.
    private func bindOutbox() {
        outbox.$writes
            .sink { [weak self] writes in
                MainActor.assumeIsolated { self?.redraw(writes) }
            }
            .store(in: &cancellables)
        outbox.delivered
            .sink { [weak self] writes in
                let categories = Set(writes.compactMap(\.tapCategoryID)).sorted()
                guard !categories.isEmpty else { return }
                Task { await self?.reconcileAfterFlush(categoryIDs: categories) }
            }
            .store(in: &cancellables)
    }

    // MARK: Loading

    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        await outbox.flush()
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                try await api.fetchQuickMarks()
            }
            switch outcome {
            case .fresh(let directory):
                offlineAsOf = nil
                show(directory)
            case .stale(let directory, let updatedAt):
                offlineAsOf = updatedAt
                show(directory)
            }
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// A delivered queue changed the server's totals: read the directory again and tell the screen
    /// which days moved.
    func reconcileAfterFlush(categoryIDs: [Int]) async {
        guard let api = apiProvider() else { return }
        if let directory = try? await api.fetchQuickMarks() {
            offlineAsOf = nil
            show(directory)
        }
        categoryIDs.forEach { onDayChanged?($0) }
    }

    private func show(_ directory: [QuickMarkDTO]) {
        serverMarks = directory
        redraw(outbox.writes)
    }

    /// Presses still waiting in the queue are laid over the directory, so a cached or just-read
    /// total does not swallow them. A press in the "not sent" list is not counted: it has not landed.
    private func redraw(_ writes: [OutboxWrite]) {
        let waiting = writes.filter { $0.status == .pending }.compactMap(\.tapMarkID)
        marks = serverMarks.map { mark in
            waiting.filter { $0 == mark.id }.reduce(mark) { folded, _ in
                folded.afterOfflineTap()
            }
        }
    }

    /// The local day of a press, `yyyy-MM-dd`. A queued press is pinned (`entry_date` of its replay)
    /// to the list's day only when the two agree: a list read yesterday (a cache, a list from 23:50)
    /// does not know today's server day, and such a press goes to the server's today, as a direct one.
    private func localDayOfPress() -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: now())
    }

    // MARK: Taps

    /// Records one tap. One network call: the answer carries the new total and `done`, so the
    /// button repaints from it. Without a network the press is queued under the key of this
    /// attempt, with the server's day from the button list, and shown at once.
    func tap(_ mark: QuickMarkDTO) async {
        errorMessage = nil
        guard let api = apiProvider() else {
            errorMessage = Self.notConfiguredMessage
            return
        }
        let key = UUID()
        let offsetMinutes = timeZone.secondsFromGMT(for: now()) / 60
        do {
            let event = try await api.tapQuickMark(
                id: mark.id,
                request: QuickMarkEventRequestDTO(
                    value: nil, entryDate: nil, utcOffsetMinutes: offsetMinutes,
                    source: QuickMarkEventRequestDTO.iosSource
                ),
                idempotencyKey: key.uuidString
            )
            replace(markID: mark.id) { $0.applying(event) }
            lastEvent = event
            onDayChanged?(mark.categoryId)
        } catch let error as APIClientError where error.isConnectivity {
            outbox.enqueue(
                .tapQuickMark(
                    QueuedTap(
                        quickMarkId: mark.id, categoryId: mark.categoryId, utcOffsetMinutes: offsetMinutes,
                        serverDay: mark.entryDate == localDayOfPress() ? mark.entryDate : nil
                    )
                ),
                key: key.uuidString, label: mark.label
            )
        } catch let error as APIClientError {
            errorMessage = error.userMessage
        } catch {
            errorMessage = Self.tapFailedMessage
        }
    }

    // MARK: Undo

    /// Takes the last tap back: one action, no trip to the entry editor.
    func undoLast() async {
        guard let event = lastEvent else { return }
        if let refusal = await undoEvent(event.eventId) {
            errorMessage = refusal
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
            if lastEvent?.eventId == eventID { lastEvent = nil }
        }
        do {
            let undone = try await api.undoQuickMarkEvent(id: eventID)
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
