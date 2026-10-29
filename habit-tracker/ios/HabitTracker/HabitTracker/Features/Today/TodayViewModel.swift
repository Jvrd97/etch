// [review:need-review] PHASE-01/05-ios-today-quick-entry, PHASE-01/38-ios-avoid-streaks, PHASE-01/11-ios-read-cache, PHASE-01/12-ios-offline-queue, PHASE-01/208, PHASE-01/210, PHASE-03/225, PHASE-03/242, PHASE-03/248, PHASE-03/256, PHASE-03/263
// summary: PHASE-03/263 — a late failure of an older load says nothing when a newer read is on screen
// summary: PHASE-03/248 — a second load keeps the loaded screen and reports its failure as a line; PHASE-03/256 — the cache stamp after a re-read of the records stays the age of the categories and streaks it keeps
// summary: PHASE-03/248 round 2 — the line a failed refresh wrote is taken back by the next refresh that works, and only that line
// [review:need-review] PHASE-03/240 — only the new OutboxAction case named in one switch (markSupplementTaken)
// summary: PHASE-03/242 — the load reads alongside the queue's send instead of after it, and its records are dropped when a re-read started by a delivery is already newer on screen (the cache keeps the newer records, no offline label over them); a failed re-read after a background delivery leaves no error
// summary: Today screen state — loads categories + entries + all avoid streaks in one request through the read cache (serves last snapshot + offline flag when the network is down); POST for form under an Idempotency-Key, idempotent checklist PUT; a form or checklist save that fails offline goes to the shared outbox under the key of its attempt and shows as a pending row derived from the queue until delivered, then the day's records are re-read quietly; a checklist save whose day still waits in the queue goes through the queue too; Happened is one server-decided tap (own key kept across a retry) with undo of the relapse this screen wrote and optional details; re-reads the day after a quick-mark tap; deletes an entry of the day
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
    static let refreshFailedMessage = "Экран не обновился"
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
    /// Idempotency-Key of a relapse tap that has not been answered yet, kept across a failed attempt so
    /// the retry is the same request to the server and not a second relapse.
    private var relapseKeys: [Int: String] = [:]
    /// Live subscription to the outbox, so the pending rows follow a background flush.
    private var cancellables: Set<AnyCancellable> = []
    /// Reads of today's records, numbered as they are sent, and the newest one shown. A load reads
    /// alongside the queue's send, so its answer may come back after a re-read a delivery started:
    /// an answer older than the one on screen is dropped.
    private var entriesReadsSent = 0
    private var entriesReadShown = 0
    /// Whole loads (categories, records, streaks) are numbered apart from the record re-reads above.
    private var loadsSent = 0
    private var loadShown = 0

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
        bindOutbox()
    }

    /// Every change of the queue — an offline save, a flush, a retry or discard from the list —
    /// redraws the pending rows; a delivered save of this screen reads the day again, so the
    /// server's row takes the place of the pending one. The outbox publishes on the main actor.
    private func bindOutbox() {
        guard let outbox else { return }
        outbox.$writes
            .sink { [weak self] writes in
                MainActor.assumeIsolated { self?.redrawPending(writes) }
            }
            .store(in: &cancellables)
        outbox.delivered
            .sink { [weak self] writes in
                guard writes.contains(where: { $0.queuedEntry != nil }) else { return }
                // Nobody pressed anything: a failed read leaves the rows as they are, without an error.
                Task { await self?.rereadEntries(reportsFailure: false) }
            }
            .store(in: &cancellables)
    }

    private func redrawPending(_ writes: [OutboxWrite]) {
        todayEntries = withQueuedRows(todayEntries.filter { !$0.isPending }, from: writes)
    }

    /// Saves still waiting in the queue, laid over the server's rows of today as pending rows
    /// (negative ids). A waiting checklist save stands in for the server's row of that category.
    private func withQueuedRows(_ server: [EntryDTO], from writes: [OutboxWrite]? = nil) -> [EntryDTO] {
        let today = todayString
        let queued = (writes ?? outbox?.writes ?? [])
            .filter { $0.status == .pending }
            .compactMap(\.queuedEntry)
            .filter { $0.entry.entryDate == today }
        let replaced = Set(queued.filter(\.replacesDay).map(\.entry.categoryId))
        let rows = queued.enumerated().map { index, queued in
            EntryDTO(
                id: -(index + 1), categoryId: queued.entry.categoryId, entryDate: queued.entry.entryDate,
                notes: queued.entry.notes, values: queued.entry.values
            )
        }
        return server.filter { !replaced.contains($0.categoryId) } + rows
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
    /// Waiting writes go out alongside the read, so a pull-to-refresh is also a retry of the queue; a
    /// slow send does not hold the screen back (waiting rows are drawn from the queue, a delivery
    /// reads the day again).
    /// The loader replaces the screen only while there is nothing to show: a second load (pull-to-refresh,
    /// a closed sheet) keeps the loaded screen and its scroll position, and its failure is a line of text.
    func load() async {
        let showsData = state == .loaded
        if !showsData { state = .loading }
        loadsSent += 1
        let load = loadsSent
        let read = nextEntriesRead()
        guard let api = apiProvider() else {
            failLoad(Self.notConfiguredMessage, showsData: showsData, load: load)
            return
        }
        let flushing = Task { await outbox?.flush() }
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
            let entriesAreNewest = showsEntries(of: read)
            apply(outcome, entriesAreNewest: entriesAreNewest)
            // The cache took this answer; its records are older than the ones a re-read put on screen.
            if !entriesAreNewest, case .fresh = outcome { cacheShownEntries() }
            streaksError = streaksFailed ? Self.streaksFailedMessage : nil
            // The badge tracks the outbox reactively (see `bindOutbox`); no manual
            // snapshot is needed here — a background flush already updated it.
            state = .loaded
            loadShown = max(loadShown, load)
            clearRefreshFailure()
        } catch let error as APIClientError {
            failLoad(error.userMessage, showsData: showsData, load: load)
        } catch {
            failLoad("Unexpected error", showsData: showsData, load: load)
        }
        await flushing.value
    }

    /// The line a failed refresh wrote, so a refresh that works can take back that line and no other.
    private var refreshFailureLine: String?

    /// A load that failed late says nothing when a newer load already reached the screen. A load with no
    /// newer one shown always says so, so a first load never stays on the spinner.
    private func failLoad(_ reason: String, showsData: Bool, load: Int) {
        if load < loadShown { return }
        if showsData {
            let line = "\(Self.refreshFailedMessage): \(reason)"
            saveErrorMessage = line
            refreshFailureLine = line
        } else {
            state = .failure(reason)
        }
    }

    private func clearRefreshFailure() {
        if saveErrorMessage == refreshFailureLine { saveErrorMessage = nil }
        refreshFailureLine = nil
    }

    /// Publishes a snapshot, recording whether it came from the network or the cache. Saves
    /// still in the queue are not on the server (nor in the cache) yet: they are laid on top.
    /// `entriesAreNewest` is false when a newer read of the records is already on screen.
    private func apply(_ outcome: CacheOutcome<TodaySnapshot>, entriesAreNewest: Bool) {
        let value: TodaySnapshot
        switch outcome {
        case .fresh(let fresh):
            offlineAsOf = nil
            value = fresh
        case .stale(let stale, let updatedAt):
            // A newer read of the records already reached the server: the screen is not offline.
            offlineAsOf = entriesAreNewest ? updatedAt : nil
            value = stale
        }
        categories = value.categories
        if entriesAreNewest { todayEntries = withQueuedRows(value.entries) }
        streaks = value.streaks
    }

    /// The cached snapshot gets the server's records now on screen, so an offline start shows them.
    /// Its categories and streaks keep their age, and so does the "data as of" stamp: it must not
    /// claim a moment later than the oldest part of the snapshot.
    private func cacheShownEntries() {
        guard let cached = cache.store.load(TodaySnapshot.self, forKey: Self.cacheKey) else { return }
        let snapshot = TodaySnapshot(
            categories: cached.value.categories, entries: todayEntries.filter { !$0.isPending },
            streaks: cached.value.streaks
        )
        cache.store.save(snapshot, forKey: Self.cacheKey, updatedAt: cached.updatedAt)
    }

    private func nextEntriesRead() -> Int {
        entriesReadsSent += 1
        return entriesReadsSent
    }

    /// Whether the answer of `read` may go on screen: only one newer than what is shown.
    private func showsEntries(of read: Int) -> Bool {
        guard read > entriesReadShown else { return false }
        entriesReadShown = read
        return true
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
    /// streak when the category is an avoid one. Pending rows of the offline outbox stay.
    func reloadAfterMark(categoryID: Int) async {
        guard let api = apiProvider() else { return }
        await rereadEntries(reportsFailure: true)
        if categories.first(where: { $0.id == categoryID })?.isAvoid == true {
            await refreshStreak(categoryID: categoryID, api: api)
        }
    }

    /// Reads today's records again without the loader: the screen stays as it is while the read runs.
    /// A failure is reported only when it follows something the person did.
    private func rereadEntries(reportsFailure: Bool) async {
        guard let api = apiProvider() else { return }
        let read = nextEntriesRead()
        let today = todayString
        do {
            let fetched = try await api.fetchEntries(startDate: today, endDate: today)
            if showsEntries(of: read) {
                todayEntries = withQueuedRows(fetched)
                cacheShownEntries()
            }
        } catch {
            if reportsFailure { saveErrorMessage = Self.entriesRefreshFailedMessage }
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
    /// via generic POST under a fresh Idempotency-Key; checklist categories go through the
    /// idempotent `PUT /entries/checklist` upsert (one entry per category+date on the backend).
    /// Without a network the save goes to the outbox — the form under the key of this attempt,
    /// both with today's date — and shows as pending. Returns true on success or when queued.
    func saveEntry(categoryID: Int, values: [Int: String]) async -> Bool {
        saveErrorMessage = nil
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return false
        }
        let category = categories.first { $0.id == categoryID }
        let label = category?.name ?? "Запись"
        do {
            let saved: EntryDTO
            if category?.isChecklist ?? false {
                let payload = ChecklistUpsertDTO(
                    categoryId: categoryID,
                    entryDate: todayString,
                    values: Dictionary(
                        uniqueKeysWithValues: values.map {
                            (String($0.key), $0.value == "true")
                        }
                    )
                )
                if let outbox, outbox.hasPending(sameTargetAs: .upsertChecklist(payload)) {
                    // An older save of this day still waits: a direct one would land first and the old
                    // one over it. The new one replaces it in the queue and goes out now if it can.
                    outbox.enqueue(.upsertChecklist(payload), label: label)
                    await outbox.flush()
                    return true
                }
                do {
                    saved = try await api.upsertChecklistEntry(payload)
                } catch let error as APIClientError where error.isConnectivity && outbox != nil {
                    outbox?.enqueue(.upsertChecklist(payload), label: label)
                    return true
                }
            } else {
                let payload = EntryCreateDTO(
                    categoryId: categoryID,
                    entryDate: todayString,
                    notes: nil,
                    values: values
                        .sorted { $0.key < $1.key }
                        .map { EntryValueDTO(fieldId: $0.key, value: $0.value) }
                )
                let key = UUID().uuidString
                do {
                    saved = try await api.createEntry(payload, idempotencyKey: key)
                } catch let error as APIClientError where error.isConnectivity && outbox != nil {
                    // Offline: don't lose "42 pushups". The replay goes under this attempt's key,
                    // so an attempt that did land and lost its answer is not recorded twice.
                    outbox?.enqueue(.createEntry(payload), key: key, label: label)
                    return true
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
}

private extension OutboxWrite {
    /// The entry a queued Today save will write, and whether it stands for the whole day of its category.
    var queuedEntry: (entry: EntryCreateDTO, replacesDay: Bool)? {
        switch action {
        case .createEntry(let entry):
            return (entry, false)
        case .upsertChecklist(let list):
            let values = list.values
                .sorted { $0.key < $1.key }
                .compactMap { key, ticked in Int(key).map { EntryValueDTO(fieldId: $0, value: ticked ? "true" : "false") } }
            return (EntryCreateDTO(categoryId: list.categoryId, entryDate: list.entryDate, notes: nil, values: values), true)
        case .tapQuickMark, .setDayMark, .recordPlanFact, .saveNotebook, .markSupplementTaken:
            return nil
        }
    }
}
