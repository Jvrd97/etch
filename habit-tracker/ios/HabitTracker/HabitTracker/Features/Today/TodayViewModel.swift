// [review:need-review] PHASE-01/05-ios-today-quick-entry, PHASE-01/38-ios-avoid-streaks, PHASE-01/11-ios-read-cache, PHASE-01/12-ios-offline-queue, PHASE-01/208, PHASE-01/210
// summary: Today screen state — loads categories + entries + all avoid streaks in one request through the read cache (serves last snapshot + offline flag when the network is down); POST for form, idempotent checklist PUT; a form POST that fails offline is queued to the outbox and shown as a pending entry, with the badge bound reactively to the outbox; Happened is one server-decided tap (own key kept across a retry) with undo of the relapse this screen wrote and optional details; re-reads the day after a quick-mark tap; deletes an entry of the day
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
    /// is not an avoid category, or the streak read failed and degraded away).
    @Published private(set) var streaks: [Int: CategoryStreakDTO] = [:]
    /// Set when the streak read failed while the rest of the screen loaded: the Streaks section says
    /// the numbers are missing instead of taking a working screen away.
    @Published private(set) var streaksError: String?
    /// Where each avoid card is in its one job: record a relapse, then optionally undo it or add details.
    @Published private(set) var relapseStates: [Int: RelapseState] = [:]
    /// When non-nil the screen is showing cached data because the last load fell back
    /// to the read cache; the value is the timestamp of that cached snapshot.
    @Published private(set) var offlineAsOf: Date?
    /// How many form entries are queued in the outbox waiting to reach the server —
    /// drives the "N записей ждут отправки" badge on Today.
    @Published private(set) var pendingUploadCount: Int = 0
    @Published var saveErrorMessage: String?

    /// Where an avoid card is in recording a relapse. The entry is the one the tap landed on.
    enum RelapseState: Equatable {
        case idle
        case recording
        case recorded(RelapseRecordedDTO)
        case undoing(RelapseRecordedDTO)
        case savingDetails(RelapseRecordedDTO)
    }

    static let notConfiguredMessage = "Set the server address in Settings"
    static let streaksFailedMessage = "Не удалось загрузить серии."
    static let relapseFailedMessage = "Не удалось записать срыв"
    static let undoRelapseFailedMessage = "Не удалось отменить срыв"
    static let relapseDetailsFailedMessage = "Не удалось сохранить подробности"
    static let entriesRefreshFailedMessage = "Список записей не обновился"
    static let deleteEntryFailedMessage = "Не удалось удалить запись"
    // Zero of a count or of time spent is what a clean day records: saved over the tap, it would
    // quietly turn the relapse into one.
    static let amountNotPositiveMessage = "Сколько — больше нуля, или оставьте поле пустым"
    /// Read-cache key for the whole Today snapshot.
    static let cacheKey = "today.snapshot"

    private let apiProvider: () -> TodayScreenAPI?
    private let cache: ReadThroughCache
    private let outbox: OutboxQueue?
    private let dateFormatter: DateFormatter
    private let now: () -> Date
    /// Next synthetic id for an optimistic pending entry. Negative and decreasing so
    /// queued rows never collide with server ids (or each other) in the list.
    private var nextPendingEntryID = -1
    /// Idempotency-Key of a relapse tap that has not been answered yet, kept across a failed attempt so
    /// the retry is the same request to the server and not a second relapse.
    private var relapseKeys: [Int: String] = [:]
    /// Live subscription to the outbox depth so the badge (and the optimistic rows it
    /// represents) stay in sync with a background flush without a manual refresh.
    private var cancellables: Set<AnyCancellable> = []

    /// Primary init: the provider is re-evaluated on every load, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(
        apiProvider: @escaping () -> TodayScreenAPI?,
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
        api: TodayScreenAPI,
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
        var streaksFailed = false
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                async let categoriesTask = api.fetchCategories()
                async let entriesTask = api.fetchEntries(startDate: today, endDate: today)
                let (fetchedCategories, fetchedEntries) = try await (categoriesTask, entriesTask)
                let active = fetchedCategories.filter(\.isActive)
                var loadedStreaks: [Int: CategoryStreakDTO] = [:]
                if active.contains(where: \.isAvoid) {
                    // One request for every avoid category. A failure degrades to "no numbers"
                    // (the web page does the same) rather than failing a Today load that succeeded.
                    do {
                        loadedStreaks = Dictionary(
                            try await api.fetchAvoidStreaks().map { ($0.categoryId, $0) },
                            uniquingKeysWith: { _, latest in latest }
                        )
                    } catch {
                        streaksFailed = true
                    }
                }
                return TodaySnapshot(
                    categories: active, entries: fetchedEntries, streaks: loadedStreaks
                )
            }
            apply(outcome)
            streaksError = streaksFailed ? Self.streaksFailedMessage : nil
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

    /// Today's entries belonging to the given category.
    func entries(forCategory categoryID: Int) -> [EntryDTO] {
        todayEntries.filter { $0.categoryId == categoryID }
    }

    /// Avoid-streak numbers for the category, or nil when there is no card to show.
    func streak(forCategory categoryID: Int) -> CategoryStreakDTO? {
        streaks[categoryID]
    }

    // MARK: Happened

    func relapseState(forCategory categoryID: Int) -> RelapseState {
        relapseStates[categoryID] ?? .idle
    }

    /// Records a relapse of an avoid category in one tap, at any field set: the server picks what to
    /// write (a tick, a 1, or an entry with no values), so the client has no copy of the rule. Then
    /// the streak is read again, so the card shows the reset number straight away.
    func recordRelapse(categoryID: Int) async {
        saveErrorMessage = nil
        switch relapseState(forCategory: categoryID) {
        case .recording, .undoing, .savingDetails:
            return
        case .idle, .recorded:
            break
        }
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return
        }
        let previous = relapseState(forCategory: categoryID)
        let key = relapseKeys[categoryID] ?? UUID().uuidString
        relapseKeys[categoryID] = key
        relapseStates[categoryID] = .recording
        let landed: RelapseRecordedDTO
        do {
            landed = try await api.recordRelapse(categoryId: categoryID, idempotencyKey: key)
        } catch let error as APIClientError {
            relapseStates[categoryID] = previous
            saveErrorMessage = error.isConnectivity
                ? "\(Self.relapseFailedMessage): \(error.userMessage)" : error.userMessage
            return
        } catch {
            relapseStates[categoryID] = previous
            saveErrorMessage = Self.relapseFailedMessage
            return
        }
        relapseKeys[categoryID] = nil
        // A repeated tap within the minute gets this screen's own relapse back with `created: false`;
        // it is still the relapse this screen wrote, so the undo stays.
        var recorded = landed
        if case .recorded(let before) = previous, before.entry.id == landed.entry.id, before.created {
            recorded = RelapseRecordedDTO(entry: landed.entry, created: true)
        }
        relapseStates[categoryID] = .recorded(recorded)
        upsert(recorded.entry)
        await refreshStreak(categoryID: categoryID, api: api)
    }

    /// Takes back the relapse this screen wrote. Never deletes a relapse somebody else recorded.
    func undoRelapse(categoryID: Int) async {
        saveErrorMessage = nil
        guard case .recorded(let recorded) = relapseState(forCategory: categoryID),
              recorded.created, let api = apiProvider() else { return }
        relapseStates[categoryID] = .undoing(recorded)
        do {
            try await api.deleteEntry(id: recorded.entry.id)
        } catch let error as APIClientError {
            relapseStates[categoryID] = .recorded(recorded)
            saveErrorMessage = error.userMessage
            return
        } catch {
            relapseStates[categoryID] = .recorded(recorded)
            saveErrorMessage = Self.undoRelapseFailedMessage
            return
        }
        relapseStates[categoryID] = .idle
        todayEntries.removeAll { $0.id == recorded.entry.id }
        await refreshStreak(categoryID: categoryID, api: api)
    }

    /// Adds the optional "how much" and a note to the relapse the tap wrote. PATCH replaces the
    /// whole value list, so what the server wrote for the tap goes back along with the amount.
    func saveRelapseDetails(categoryID: Int, amount: String, notes: String) async -> Bool {
        saveErrorMessage = nil
        guard case .recorded(let recorded) = relapseState(forCategory: categoryID),
              let api = apiProvider() else { return false }
        let trimmedAmount = amount.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        let field = amountField(forCategory: categoryID)

        var values: [EntryValueDTO]?
        if let field, !trimmedAmount.isEmpty {
            guard let number = Double(trimmedAmount.replacingOccurrences(of: ",", with: ".")),
                  number > 0 else {
                saveErrorMessage = Self.amountNotPositiveMessage
                return false
            }
            values = recorded.entry.values.filter { $0.fieldId != field.id }
                + [EntryValueDTO(fieldId: field.id, value: trimmedAmount)]
        }
        let note = trimmedNotes.isEmpty ? nil : trimmedNotes
        guard values != nil || note != nil else { return true }

        relapseStates[categoryID] = .savingDetails(recorded)
        do {
            let updated = try await api.updateEntry(
                id: recorded.entry.id,
                EntryUpdateDTO(entryDate: nil, notes: note, values: values)
            )
            relapseStates[categoryID] = .recorded(
                RelapseRecordedDTO(entry: updated, created: recorded.created)
            )
            upsert(updated)
            await refreshStreak(categoryID: categoryID, api: api)
            return true
        } catch let error as APIClientError {
            relapseStates[categoryID] = .recorded(recorded)
            saveErrorMessage = error.userMessage
            return false
        } catch {
            relapseStates[categoryID] = .recorded(recorded)
            saveErrorMessage = Self.relapseDetailsFailedMessage
            return false
        }
    }

    /// The field the "how much" of a relapse is written to: the first number field in display order,
    /// else the first duration.
    func amountField(forCategory categoryID: Int) -> FieldDTO? {
        let fields = (categories.first { $0.id == categoryID }?.fields ?? [])
            .sorted { ($0.order, $0.id) < ($1.order, $1.id) }
        return fields.first { $0.fieldType == .number } ?? fields.first { $0.fieldType == .duration }
    }

    private func refreshStreak(categoryID: Int, api: TodayScreenAPI) async {
        if let refreshed = try? await api.fetchStreak(categoryId: categoryID) {
            streaks[categoryID] = refreshed
        }
    }

    /// Replaces the entry in place when the list already holds it, appends it otherwise.
    private func upsert(_ entry: EntryDTO) {
        if let index = todayEntries.firstIndex(where: { $0.id == entry.id }) {
            todayEntries[index] = entry
        } else {
            todayEntries.append(entry)
        }
    }

    // MARK: Day changes made elsewhere

    /// A quick-mark tap or undo moved the day of this category: read the day's records again, and the
    /// streak when the category is an avoid one. Optimistic rows of the offline outbox stay.
    func reloadAfterMark(categoryID: Int) async {
        guard let api = apiProvider() else { return }
        let today = todayString
        do {
            let fetched = try await api.fetchEntries(startDate: today, endDate: today)
            todayEntries = fetched + todayEntries.filter(\.isPending)
        } catch {
            saveErrorMessage = Self.entriesRefreshFailedMessage
        }
        if categories.first(where: { $0.id == categoryID })?.isAvoid == true {
            await refreshStreak(categoryID: categoryID, api: api)
        }
    }

    /// Deletes an entry of the day list. The streak of an avoid category is read again, because the
    /// deleted entry may have been the relapse.
    func deleteEntry(id: Int) async -> Bool {
        saveErrorMessage = nil
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return false
        }
        let categoryID = todayEntries.first { $0.id == id }?.categoryId
        do {
            try await api.deleteEntry(id: id)
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = Self.deleteEntryFailedMessage
            return false
        }
        todayEntries.removeAll { $0.id == id }
        if let categoryID, categories.first(where: { $0.id == categoryID })?.isAvoid == true {
            await refreshStreak(categoryID: categoryID, api: api)
        }
        return true
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
