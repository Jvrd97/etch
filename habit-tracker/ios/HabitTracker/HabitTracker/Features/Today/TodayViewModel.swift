// [review:need-review] PHASE-01/05-ios-today-quick-entry, PHASE-01/38-ios-avoid-streaks, PHASE-01/11-ios-read-cache, PHASE-01/12-ios-offline-queue, PHASE-01/208
// summary: Today screen state — loads categories + entries + avoid streaks through the read cache (serves last snapshot + offline flag when the network is down); POST for form, idempotent checklist PUT; a form POST that fails offline is queued to the outbox and shown as a pending entry, with the badge bound reactively to the outbox so a background flush clears it (and its optimistic rows) without a manual refresh; logRelapse posts count + reloads streak
import Combine
import Foundation

/// The categories/entries/streaks a single Today load produced, cached as one unit so
/// airplane mode can restore the whole screen from the last successful fetch.
struct TodaySnapshot: Codable, Equatable {
    let categories: [CategoryDTO]
    let entries: [EntryDTO]
    let streaks: [Int: CategoryStreakDTO]
}

@MainActor
final class TodayViewModel: ObservableObject {
    /// Discriminated load state for the Today list.
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var categories: [CategoryDTO] = []
    @Published private(set) var todayEntries: [EntryDTO] = []
    /// Avoid-streak numbers keyed by category id, populated for avoid categories
    /// during `load()`. A category missing here has no streak to show (either it
    /// is not an avoid category, or its streak request failed and degraded away).
    @Published private(set) var streaks: [Int: CategoryStreakDTO] = [:]
    /// When non-nil the screen is showing cached data because the last load fell back
    /// to the read cache; the value is the timestamp of that cached snapshot.
    @Published private(set) var offlineAsOf: Date?
    /// How many form entries are queued in the outbox waiting to reach the server —
    /// drives the "N записей ждут отправки" badge on Today.
    @Published private(set) var pendingUploadCount: Int = 0
    @Published var saveErrorMessage: String?

    static let notConfiguredMessage = "Set the server address in Settings"
    static let noCountFieldMessage = "This habit has no number field to log"
    /// Read-cache key for the whole Today snapshot.
    static let cacheKey = "today.snapshot"

    private let apiProvider: () -> TodayAPI?
    private let cache: ReadThroughCache
    private let outbox: OutboxQueue?
    private let dateFormatter: DateFormatter
    private let now: () -> Date
    /// Next synthetic id for an optimistic pending entry. Negative and decreasing so
    /// queued rows never collide with server ids (or each other) in the list.
    private var nextPendingEntryID = -1
    /// Live subscription to the outbox depth so the badge (and the optimistic rows it
    /// represents) stay in sync with a background flush without a manual refresh.
    private var cancellables: Set<AnyCancellable> = []

    /// Primary init: the provider is re-evaluated on every load, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(
        apiProvider: @escaping () -> TodayAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.outbox = outbox
        self.now = now
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        self.dateFormatter = formatter
        self.pendingUploadCount = outbox?.pendingCount ?? 0
        bindOutbox()
    }

    /// Subscribes to the outbox's published depth. Every change — an offline enqueue or a
    /// background flush drained by `NWPathMonitor` — flows here, so the badge is never a
    /// one-shot snapshot. When the depth drops (a flush succeeded) the optimistic pending
    /// rows are reconciled away so the list and badge clear together. The outbox publishes
    /// on the main actor (it is `@MainActor`), so the value is delivered there.
    private func bindOutbox() {
        guard let outbox else { return }
        outbox.$pendingCount
            .sink { [weak self] count in
                MainActor.assumeIsolated {
                    self?.reconcilePending(newCount: count)
                }
            }
            .store(in: &cancellables)
    }

    /// Applies a new outbox depth to the badge and, when the queue shrank (a flush sent
    /// queued creates), drops the now-obsolete optimistic rows and reloads so the real
    /// server entries take their place — the badge and the list clear in the same step.
    private func reconcilePending(newCount: Int) {
        let drained = newCount < pendingUploadCount
        pendingUploadCount = newCount
        guard drained else { return }
        todayEntries.removeAll { $0.isPending }
        Task { await load() }
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(
        api: TodayAPI,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(
            apiProvider: { api },
            cacheStore: cacheStore,
            outbox: outbox,
            timeZone: timeZone,
            now: now
        )
    }

    /// Builds the production view model from stored Settings (UserDefaults + Keychain).
    static func live() -> TodayViewModel {
        TodayViewModel(
            apiProvider: { APIClient.live() },
            cacheStore: ReadCacheLive.shared,
            outbox: OutboxLive.shared
        )
    }

    /// Today's date in the backend's `YYYY-MM-DD` format.
    var todayString: String {
        dateFormatter.string(from: now())
    }

    /// Loads active categories, today's entries, and avoid streaks in one pass, through
    /// the read cache: a successful fetch refreshes the screen and the cache; when the
    /// network is down the last cached snapshot is shown with an offline timestamp.
    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        let today = todayString
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                async let categoriesTask = api.fetchCategories()
                async let entriesTask = api.fetchEntries(startDate: today, endDate: today)
                let (fetchedCategories, fetchedEntries) = try await (categoriesTask, entriesTask)
                let active = fetchedCategories.filter(\.isActive)
                let loadedStreaks = await self.loadStreaks(for: active, api: api)
                return TodaySnapshot(
                    categories: active, entries: fetchedEntries, streaks: loadedStreaks
                )
            }
            apply(outcome)
            // The badge tracks the outbox reactively (see `bindOutbox`); no manual
            // snapshot is needed here — a background flush already updated it.
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// Publishes a snapshot, recording whether it came from the network or the cache.
    private func apply(_ outcome: CacheOutcome<TodaySnapshot>) {
        // Optimistic rows for still-queued offline creates. They live only in
        // `todayEntries`, never in the read cache, so a stale snapshot would drop them.
        let pendingRows = todayEntries.filter(\.isPending)
        switch outcome {
        case .fresh(let value):
            offlineAsOf = nil
            categories = value.categories
            // Online: the server is the source of truth. Any optimistic rows are
            // reconciled by `reconcilePending` once the outbox flush deletes them.
            todayEntries = value.entries
            streaks = value.streaks
        case .stale(let value, let updatedAt):
            offlineAsOf = updatedAt
            categories = value.categories
            // Offline: the cached snapshot predates the queued creates, so merge the
            // optimistic pending rows on top — a queued entry stays visible in the list,
            // matching the badge, instead of vanishing until the network returns.
            todayEntries = value.entries + pendingRows
            streaks = value.streaks
        }
    }

    /// Fetches streaks for every avoid category concurrently. A single failed
    /// streak request degrades to "no card" (mirrors the web page) rather than
    /// failing the whole Today load, which already succeeded.
    private func loadStreaks(
        for categories: [CategoryDTO], api: TodayAPI
    ) async -> [Int: CategoryStreakDTO] {
        let avoidCategories = categories.filter(\.isAvoid)
        guard !avoidCategories.isEmpty else { return [:] }
        return await withTaskGroup(of: (Int, CategoryStreakDTO?).self) { group in
            for category in avoidCategories {
                group.addTask {
                    (category.id, try? await api.fetchStreak(categoryId: category.id))
                }
            }
            var result: [Int: CategoryStreakDTO] = [:]
            for await (categoryID, streak) in group {
                if let streak {
                    result[categoryID] = streak
                }
            }
            return result
        }
    }

    /// Today's entries belonging to the given category.
    func entries(forCategory categoryID: Int) -> [EntryDTO] {
        todayEntries.filter { $0.categoryId == categoryID }
    }

    /// Avoid-streak numbers for the category, or nil when there is no card to show.
    func streak(forCategory categoryID: Int) -> CategoryStreakDTO? {
        streaks[categoryID]
    }

    /// Records a relapse ("случилось") for an avoid category: posts an entry whose
    /// primary number field carries `count`, plus optional `notes`, then reloads
    /// that category's streak so the card shows the reset current streak (best is
    /// preserved by the backend). Returns true on success.
    func logRelapse(categoryID: Int, count: String, notes: String?) async -> Bool {
        saveErrorMessage = nil
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return false
        }
        guard let countField = countField(forCategory: categoryID) else {
            saveErrorMessage = Self.noCountFieldMessage
            return false
        }
        do {
            let saved = try await api.createEntry(
                EntryCreateDTO(
                    categoryId: categoryID,
                    entryDate: todayString,
                    notes: notes,
                    values: [EntryValueDTO(fieldId: countField.id, value: count)]
                )
            )
            if let index = todayEntries.firstIndex(where: { $0.id == saved.id }) {
                todayEntries[index] = saved
            } else {
                todayEntries.append(saved)
            }
            if let refreshed = try? await api.fetchStreak(categoryId: categoryID) {
                streaks[categoryID] = refreshed
            }
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    /// The number field a relapse count is written to — the first number field in
    /// display order, matching the "how much" slot on the relapse form.
    func countField(forCategory categoryID: Int) -> FieldDTO? {
        categories
            .first { $0.id == categoryID }?
            .fields
            .sorted { ($0.order, $0.id) < ($1.order, $1.id) }
            .first { $0.fieldType == .number }
    }

    /// Saves today's values for the category. Form categories create a new entry
    /// via generic POST; checklist categories go through the idempotent
    /// `PUT /entries/checklist` upsert (one entry per category+date on the backend).
    /// Returns true on success.
    func saveEntry(categoryID: Int, values: [Int: String]) async -> Bool {
        saveErrorMessage = nil
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return false
        }
        let isChecklist = categories.first { $0.id == categoryID }?.isChecklist ?? false
        do {
            let saved: EntryDTO
            if isChecklist {
                saved = try await api.upsertChecklistEntry(
                    ChecklistUpsertDTO(
                        categoryId: categoryID,
                        entryDate: todayString,
                        values: Dictionary(
                            uniqueKeysWithValues: values.map {
                                (String($0.key), $0.value == "true")
                            }
                        )
                    )
                )
            } else {
                let payload = EntryCreateDTO(
                    categoryId: categoryID,
                    entryDate: todayString,
                    notes: nil,
                    values: values
                        .sorted { $0.key < $1.key }
                        .map { EntryValueDTO(fieldId: $0.key, value: $0.value) }
                )
                do {
                    saved = try await api.createEntry(payload)
                } catch let error as APIClientError where error.isConnectivity {
                    // Offline: don't lose "42 pushups". Queue it and show it optimistically
                    // so the user sees their entry and the pending badge, not an error.
                    if let outbox {
                        return enqueueOffline(payload, outbox: outbox)
                    }
                    throw error
                }
            }
            // The checklist upsert can return an entry we already loaded — replace
            // it in place so the list never shows duplicates.
            if let index = todayEntries.firstIndex(where: { $0.id == saved.id }) {
                todayEntries[index] = saved
            } else {
                todayEntries.append(saved)
            }
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    /// Queues a create that failed offline and mirrors it into the list as a pending
    /// row (synthetic negative id), so the entry is visible immediately and the badge
    /// reflects the outbox depth. Returns true — the save is not lost, just deferred.
    private func enqueueOffline(_ payload: EntryCreateDTO, outbox: OutboxQueue) -> Bool {
        outbox.enqueue(payload)
        todayEntries.append(
            EntryDTO(
                id: nextPendingEntryID,
                categoryId: payload.categoryId,
                entryDate: payload.entryDate,
                notes: payload.notes,
                values: payload.values
            )
        )
        nextPendingEntryID -= 1
        // The badge updates reactively via `bindOutbox` when `enqueue` bumps the depth.
        return true
    }
}
