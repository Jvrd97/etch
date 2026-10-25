// [review:need-review] PHASE-01/210
// summary: state of the quick-mark buttons — the directory through the read cache, one POST per tap that repaints the button from its own answer, an offline tap queued under the same key and shown at once, undo of the last tap or of a named set, and a word to the screen when a day moved
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
    @Published private(set) var pendingTapCount = 0
    @Published var errorMessage: String?

    /// A tap or an undo went through (or a queued tap was delivered): the day of this category
    /// moved. The buttons repaint on their own; the records and streaks beside them are another
    /// screen's state, and a screen that is not told keeps showing the day as it was.
    var onDayChanged: ((Int) -> Void)?

    static let notConfiguredMessage = "Set the server address in Settings"
    static let tapFailedMessage = "Отметку записать не удалось."
    static let undoFailedMessage = "Отменить отметку не удалось."
    static let rejectedTapsMessage = "Сервер не принял часть отметок, сделанных без сети."
    static let cacheKey = "today.quickmarks"

    private let apiProvider: () -> QuickMarksAPI?
    private let cache: ReadThroughCache
    private let queue: QuickMarkTapQueue
    private let timeZone: TimeZone
    private let now: () -> Date
    private var cancellables: Set<AnyCancellable> = []

    init(
        apiProvider: @escaping () -> QuickMarksAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        queue: QuickMarkTapQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        let queue = queue ?? QuickMarkTapQueue(store: InMemoryTapStore())
        self.queue = queue
        self.timeZone = timeZone
        self.now = now
        self.pendingTapCount = queue.pendingCount
        bindQueue()
    }

    convenience init(
        api: QuickMarksAPI,
        cacheStore: CacheStore = InMemoryCacheStore(),
        queue: QuickMarkTapQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(
            apiProvider: { api }, cacheStore: cacheStore, queue: queue, timeZone: timeZone,
            now: now
        )
    }

    static func live() -> QuickMarksViewModel {
        QuickMarksViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared,
            queue: QuickMarkTapLive.shared
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

    private func bindQueue() {
        queue.$pending
            .sink { [weak self] pending in
                MainActor.assumeIsolated { self?.pendingTapCount = pending.count }
            }
            .store(in: &cancellables)
        queue.flushCompleted
            .sink { [weak self] categories in
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
        if queue.pendingCount > 0 {
            await queue.flush(using: api)
        }
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                try await api.fetchQuickMarks()
            }
            switch outcome {
            case .fresh(let directory):
                offlineAsOf = nil
                marks = withQueuedTaps(directory)
            case .stale(let directory, let updatedAt):
                offlineAsOf = updatedAt
                marks = withQueuedTaps(directory)
            }
            if queue.takeRejectedCount() > 0 {
                errorMessage = Self.rejectedTapsMessage
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
            marks = withQueuedTaps(directory)
        }
        if queue.takeRejectedCount() > 0 {
            errorMessage = Self.rejectedTapsMessage
        }
        categoryIDs.forEach { onDayChanged?($0) }
    }

    /// Presses still waiting in the queue are laid over the directory, so a cached or just-read
    /// total does not swallow them.
    private func withQueuedTaps(_ directory: [QuickMarkDTO]) -> [QuickMarkDTO] {
        let waiting = queue.pending
        guard !waiting.isEmpty else { return directory }
        return directory.map { mark in
            waiting.filter { $0.quickMarkId == mark.id }.reduce(mark) { folded, _ in
                folded.afterOfflineTap()
            }
        }
    }

    // MARK: Taps

    /// Records one tap. One network call: the answer carries the new total and `done`, so the
    /// button repaints from it. Without a network the press is queued under the key of this
    /// attempt and shown at once.
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
                    source: QuickMarkTapQueue.tapSource
                ),
                idempotencyKey: key.uuidString
            )
            replace(markID: mark.id) { $0.applying(event) }
            lastEvent = event
            onDayChanged?(mark.categoryId)
        } catch let error as APIClientError where error.isConnectivity {
            queue.enqueue(
                key: key, quickMarkId: mark.id, categoryId: mark.categoryId,
                utcOffsetMinutes: offsetMinutes
            )
            replace(markID: mark.id) { $0.afterOfflineTap() }
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
        guard let index = marks.firstIndex(where: { $0.id == markID }) else { return }
        marks[index] = transform(marks[index])
    }
}
