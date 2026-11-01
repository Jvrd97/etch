// [review:need-review] PHASE-01/05-ios-today-quick-entry, PHASE-01/38-ios-avoid-streaks, PHASE-01/11-ios-read-cache, PHASE-01/12-ios-offline-queue, PHASE-01/208, PHASE-01/210, PHASE-03/225, PHASE-03/242, PHASE-03/248, PHASE-03/256, PHASE-03/263, PHASE-03/294
// summary: PHASE-03/294 — the cards are ordered by use (a table read of the last 30 days, kept in the snapshot; the load waits for it at most `usageReadLimit`, a failed or late read takes the usage of the previous snapshot, a late answer is cached for the next load); a plus tap adds the field's step once (one in flight per category, the save goes through the outbox); a relapse is recorded on a chosen day (the key follows the day) and a recorded one moves to another day
// summary: PHASE-03/263 — a late failure of an older load says nothing when a newer read is on screen
// summary: PHASE-03/248 — a second load keeps the loaded screen and reports its failure as a line; PHASE-03/256 — the cache stamp after a re-read of the records stays the age of the categories and streaks it keeps
// summary: PHASE-03/248 round 2 — the line a failed refresh wrote is taken back by the next refresh that works, and only that line
// [review:need-review] PHASE-03/240 — only the new OutboxAction case named in one switch (markSupplementTaken)
// summary: PHASE-03/242 — the load reads alongside the queue's send instead of after it, and its records are dropped when a re-read started by a delivery is already newer on screen (the cache keeps the newer records, no offline label over them); a failed re-read after a background delivery leaves no error
// summary: Today screen state — loads categories + entries + all avoid streaks in one request through the read cache (serves last snapshot + offline flag when the network is down); POST for form under an Idempotency-Key, idempotent checklist PUT; a form or checklist save that fails offline goes to the shared outbox under the key of its attempt and shows as a pending row derived from the queue until delivered, then the day's records are re-read quietly; a checklist save whose day still waits in the queue goes through the queue too; Happened is one server-decided tap (own key kept across a retry) with undo of the relapse this screen wrote and optional details; re-reads the day after a quick-mark tap; deletes an entry of the day
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — an appearance after midnight reads again whatever the age of the snapshot; the cache takes no answer of a server the address moved away from
// summary: PHASE-03/310 — the screen opens on the cached snapshot of today (no loader, no network wait) and reads again only when it is not recent; the snapshot carries its day, and a snapshot of another day neither opens the screen nor shows its records as today's offline; the streak read leaves with the first wave when the known categories have an avoid one, and never waits for the table
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 round 3 — an entry delivered for another day is not kept as an overlay of today's reads
// summary: PHASE-03/316 round 2 — the server's rows are kept apart from the screen (`serverEntries`), so a refused checklist save gives the server's row back; a delivered entry is laid over every read sent before its delivery (a read in flight is shown, not dropped, and the cache gets what the screen shows), until a read sent after it is shown
// summary: PHASE-03/316 — a plus, a typed number, a tick and the form go into the outbox under the key of that press and are on screen at once, the send runs behind; every press counts (no tap is dropped while another is on its way); a delivery puts the server's entry in place of the waiting row in the same turn and reads only the streak of an avoid category; a refusal takes the row away and says why; the «ждёт» tag shows only writes that wait; re-reads after quick-mark deliveries are merged into one
import Combine
import Foundation

/// The categories/entries/streaks a single Today load produced, cached as one unit so
/// airplane mode can restore the whole screen from the last successful fetch.
struct TodaySnapshot: Codable, Equatable {
    let categories: [CategoryDTO]
    let entries: [EntryDTO]
    let streaks: [Int: CategoryStreakDTO]
    /// Entries per category over the last 30 days; nil when the read failed or the snapshot is older than it.
    var usage: [Int: CategoryUsage]? = nil
    /// The day the records are of, `yyyy-MM-dd`; nil in a snapshot written before the day was kept.
    var day: String? = nil
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
    /// Categories with a queued save that waits — failed once or on its way past the quiet period. A save
    /// that is merely on its way is drawn as a row of the day without the tag.
    @Published private(set) var waitingCategoryIDs: Set<Int> = []
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
    static let writeRefusedPrefix = "Не отправлено"
    // Zero of a count or of time spent is what a clean day records: saved over the tap, it would
    // quietly turn the relapse into one.
    static let amountNotPositiveMessage = "Сколько — больше нуля, или оставьте поле пустым"
    /// The longest a load waits for the table that orders the cards: past it the screen is drawn in the
    /// order of the previous snapshot and the late answer is kept for the next load.
    nonisolated static let usageReadLimit: Duration = .milliseconds(1500)
    /// Read-cache key for the whole Today snapshot.
    static let cacheKey = "today.snapshot"

    private let apiProvider: () -> TodayScreenAPI?
    private let cache: ReadThroughCache
    private let outbox: OutboxQueue?
    private let dateFormatter: DateFormatter
    private let now: () -> Date
    /// How long a load waits for the table that orders the cards.
    private let usageReadLimit: Duration
    /// Idempotency-Key of a relapse tap that has not been answered yet, kept across a failed attempt so
    /// the retry is the same request to the server and not a second relapse.
    private var relapseKeys: [Int: (day: String?, key: String)] = [:]
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
    /// The day of the records on screen; past midnight it is not today any more.
    private var shownDay: String?
    /// Today's rows as the server holds them, as far as this screen knows: `todayEntries` is them with the
    /// queued saves on top.
    private var serverEntries: [EntryDTO] = []
    /// Entries the server took from the queue, with the newest read sent before each delivery: a read up to
    /// that number may not hold the entry, so it is laid over that read's answer.
    private var deliveredEntries: [(afterRead: Int, entry: EntryDTO)] = []
    /// Categories whose records a quick-mark delivery moved while a re-read was already running: that
    /// re-read is followed by one more, so a burst of presses reads the day twice, not once per press.
    private var markRereadQueue: Set<Int> = []
    private var isRereadingAfterMark = false

    /// Primary init: the provider is re-evaluated on every load, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(
        apiProvider: @escaping () -> TodayScreenAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        outbox: OutboxQueue? = nil,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init,
        usageReadLimit: Duration = TodayViewModel.usageReadLimit
    ) {
        self.usageReadLimit = usageReadLimit
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

    /// Every change of the queue — a save, a flush, a retry or discard from the list — redraws the
    /// pending rows. A delivered save of this screen puts the server's entry in place of its pending row
    /// in the same turn; a refused one is gone from the rows and said in a line. The outbox publishes
    /// on the main actor.
    private func bindOutbox() {
        guard let outbox else { return }
        outbox.$writes
            .sink { [weak self] writes in
                MainActor.assumeIsolated { self?.redrawPending(writes) }
            }
            .store(in: &cancellables)
        outbox.delivered
            .sink { [weak self] delivery in
                MainActor.assumeIsolated { self?.settle(delivery) }
            }
            .store(in: &cancellables)
        outbox.refused
            .sink { [weak self] write in
                guard write.queuedEntry != nil else { return }
                MainActor.assumeIsolated {
                    self?.saveErrorMessage = "\(Self.writeRefusedPrefix) «\(write.label)»: \(write.failure ?? "")"
                }
            }
            .store(in: &cancellables)
    }

    private func redrawPending(_ writes: [OutboxWrite]? = nil) {
        let writes = writes ?? outbox?.writes ?? []
        todayEntries = withQueuedRows(serverEntries, from: writes)
        let moment = now()
        waitingCategoryIDs = Set(
            writes.filter { $0.status == .pending && $0.isOverdue(at: moment) }
                .compactMap { $0.queuedEntry?.entry.categoryId }
        )
    }

    /// The server took a save of this screen: its entry takes the place of the pending row, and only what
    /// the entry changes is read again — the streak of an avoid category. A read of the records already
    /// on its way may predate the entry: it is shown with the entry laid over it. An answer this app could
    /// not read reads the day.
    private func settle(_ delivery: OutboxDelivery) {
        guard let queued = delivery.write.queuedEntry else { return }
        guard case .entry(let entry)? = delivery.reply else {
            // Nobody pressed anything: a failed read leaves the rows as they are, without an error.
            Task { await rereadEntries(reportsFailure: false) }
            return
        }
        // An entry of another day is not today's: nothing to lay over today's reads.
        if entry.entryDate == todayString { deliveredEntries.append((afterRead: entriesReadsSent, entry: entry)) }
        place(entry)
        cacheShownEntries(sentUnder: cache.scope)
        let categoryID = queued.entry.categoryId
        if categories.first(where: { $0.id == categoryID })?.isAvoid == true, let api = apiProvider() {
            Task { await refreshStreak(categoryID: categoryID, api: api) }
        }
    }

    /// Puts the answer of a read on screen as the server's rows, with the entries delivered after it was
    /// sent laid over it. A read sent after a delivery holds that entry: its overlay is dropped. `read` is
    /// nil for the cached snapshot, which keeps every overlay.
    private func showServerRows(_ rows: [EntryDTO], read: Int?) {
        if let read { deliveredEntries.removeAll { $0.afterRead < read } }
        var shown = rows
        for delivered in deliveredEntries.map(\.entry) where delivered.entryDate == todayString {
            if let index = shown.firstIndex(where: { $0.id == delivered.id }) {
                shown[index] = delivered
            } else {
                shown.append(delivered)
            }
        }
        serverEntries = shown
        redrawPending()
    }

    /// Saves still waiting in the queue, laid over the server's rows of today as pending rows
    /// (negative ids). A waiting checklist save stands in for the server's row of that category; of two,
    /// the newer one.
    private func withQueuedRows(_ server: [EntryDTO], from writes: [OutboxWrite]? = nil) -> [EntryDTO] {
        let today = todayString
        let all = (writes ?? outbox?.writes ?? [])
            .filter { $0.status == .pending }
            .compactMap(\.queuedEntry)
            .filter { $0.entry.entryDate == today }
        // A checklist save being sent and a newer one waiting behind it: the day is the newer one.
        let queued = all.enumerated().filter { index, queued in
            !queued.replacesDay || !all[(index + 1)...].contains { $0.replacesDay && $0.entry.categoryId == queued.entry.categoryId }
        }.map(\.element)
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
        now: @escaping () -> Date = Date.init,
        usageReadLimit: Duration = TodayViewModel.usageReadLimit
    ) {
        self.init(
            apiProvider: { api },
            cacheStore: cacheStore,
            outbox: outbox,
            timeZone: timeZone,
            now: now,
            usageReadLimit: usageReadLimit
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

    /// The screen came on (first time or back on its tab): the cached snapshot of today goes on screen at
    /// once, and the server is asked only when that snapshot is not recent.
    func appear() async {
        showCached()
        if state == .loaded, shownDay == todayString, cache.isRecent(key: Self.cacheKey) { return }
        await load()
    }

    /// Puts the cached snapshot on screen while nothing is shown, without the network. A snapshot of
    /// another day is not today's: the screen waits for the server then.
    func showCached() {
        guard state != .loaded,
              let cached = cache.peek(TodaySnapshot.self, key: Self.cacheKey),
              cached.value.day == todayString else { return }
        categories = TodayOrdering.sorted(cached.value.categories, usage: cached.value.usage)
        showServerRows(cached.value.entries, read: nil)
        streaks = cached.value.streaks
        shownDay = cached.value.day
        state = .loaded
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
        let sentUnder = cache.scope
        let flushing = Task { await outbox?.flush() }
        let today = todayString
        let usageRange = usageWindow()
        var streaksFailed = false
        // Categories already known to have an avoid one (on screen or cached) send the streak read with the
        // first wave; otherwise it waits for the categories, so a screen without avoid cards asks nothing.
        let knownAvoid = (categories.isEmpty ? previousSnapshot()?.categories ?? [] : categories).contains(where: \.isAvoid)
        do {
            let outcome = try await cache.load(key: Self.cacheKey) {
                async let categoriesTask = api.fetchCategories()
                async let entriesTask = api.fetchEntries(startDate: today, endDate: today)
                async let earlyStreaks = Self.readStreaks(api: api, if: knownAvoid)
                // The order of the cards is a nicety: its failure is not the screen's.
                async let usageTask = self.readUsage(api: api, range: usageRange)
                let (fetchedCategories, fetchedEntries) = try await (categoriesTask, entriesTask)
                let active = fetchedCategories.filter(\.isActive)
                let needsStreaks = active.contains(where: \.isAvoid)
                async let lateStreaks = Self.readStreaks(api: api, if: needsStreaks && !knownAvoid)
                let usage = await usageTask
                let (early, late) = await (earlyStreaks, lateStreaks)
                var loadedStreaks: [Int: CategoryStreakDTO] = [:]
                // One request for every avoid category. A failure degrades to "no numbers"
                // (the web page does the same) rather than failing a Today load that succeeded.
                switch needsStreaks ? early ?? late : nil {
                case .success(let read)?:
                    loadedStreaks = Dictionary(read.map { ($0.categoryId, $0) }, uniquingKeysWith: { _, latest in latest })
                case .failure?:
                    streaksFailed = true
                case nil:
                    break
                }
                return TodaySnapshot(
                    categories: active, entries: fetchedEntries, streaks: loadedStreaks, usage: usage, day: today
                )
            }
            let entriesAreNewest = showsEntries(of: read)
            apply(outcome, entriesAreNewest: entriesAreNewest, read: read)
            // The cache took this answer; the screen shows newer records (a later re-read, or entries
            // delivered while it was on its way), and the cache keeps what the screen shows.
            if case .fresh = outcome, !entriesAreNewest || !deliveredEntries.isEmpty { cacheShownEntries(sentUnder: sentUnder) }
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

    /// The bulk streak read, or nil without asking when `ask` is false.
    private nonisolated static func readStreaks(
        api: TodayScreenAPI, if ask: Bool
    ) async -> Result<[CategoryStreakDTO], Error>? {
        guard ask else { return nil }
        do { return .success(try await api.fetchAvoidStreaks()) } catch { return .failure(error) }
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
    private func apply(_ outcome: CacheOutcome<TodaySnapshot>, entriesAreNewest: Bool, read: Int) {
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
        categories = TodayOrdering.sorted(value.categories, usage: value.usage)
        // Records of another day are not today's: an offline start on a new day shows none of them.
        if entriesAreNewest {
            showServerRows(value.day == todayString ? value.entries : [], read: read)
            shownDay = todayString
        }
        streaks = value.streaks
    }

    /// The cached snapshot gets the server's records now on screen, so an offline start shows them.
    /// Its categories and streaks keep their age, and so does the "data as of" stamp: it must not
    /// claim a moment later than the oldest part of the snapshot.
    private func cacheShownEntries(sentUnder: String) {
        guard let cached = cache.store.load(TodaySnapshot.self, forKey: Self.cacheKey) else { return }
        let snapshot = TodaySnapshot(
            categories: cached.value.categories, entries: serverEntries,
            streaks: cached.value.streaks, usage: cached.value.usage, day: todayString
        )
        cache.save(snapshot, forKey: Self.cacheKey, updatedAt: cached.updatedAt, sentUnder: sentUnder)
    }

    private enum UsageRead {
        case answered([Int: CategoryUsage]?)
        case timedOut
    }

    /// The first of two finishers resumes the waiting load; the second finds it gone. Both run on the main actor.
    @MainActor
    private final class UsageRace {
        private var continuation: CheckedContinuation<UsageRead, Never>?

        init(_ continuation: CheckedContinuation<UsageRead, Never>) {
            self.continuation = continuation
        }

        func finish(_ read: UsageRead) {
            continuation?.resume(returning: read)
            continuation = nil
        }
    }

    /// Entries per category over the last `TodayOrdering.windowDays` days, today included. The read
    /// never holds the load past `usageReadLimit`; a failed or late read gives the usage of the previous
    /// snapshot, so the order neither jumps nor is wiped from the cache. An answer that comes late goes
    /// to the cache and orders the next load, not the screen in front of the person.
    private func readUsage(api: TodayScreenAPI, range: (from: String, to: String)) async -> [Int: CategoryUsage]? {
        let sentUnder = cache.scope
        let fetch = Task { () -> [Int: CategoryUsage]? in
            guard let table = try? await api.fetchTable(dateFrom: range.from, dateTo: range.to) else { return nil }
            return TodayOrdering.usage(from: table)
        }
        let limit = usageReadLimit
        // Not a task group: a group waits for its children, and the table read is not cancelled by the timer.
        var timer: Task<Void, Never>?
        let read: UsageRead = await withCheckedContinuation { continuation in
            let race = UsageRace(continuation)
            Task { race.finish(.answered(await fetch.value)) }
            timer = Task {
                try? await Task.sleep(for: limit)
                race.finish(.timedOut)
            }
        }
        timer?.cancel()
        switch read {
        case .answered(let usage):
            return usage ?? previousUsage()
        case .timedOut:
            Task { [weak self] in
                if let usage = await fetch.value { self?.keepUsageForNextLoad(usage, sentUnder: sentUnder) }
            }
            return previousUsage()
        }
    }

    private func previousUsage() -> [Int: CategoryUsage]? {
        previousSnapshot()?.usage
    }

    private func previousSnapshot() -> TodaySnapshot? {
        cache.store.load(TodaySnapshot.self, forKey: Self.cacheKey)?.value
    }

    /// Writes a late answer into the cached snapshot, keeping its age.
    private func keepUsageForNextLoad(_ usage: [Int: CategoryUsage], sentUnder: String) {
        guard let cached = cache.store.load(TodaySnapshot.self, forKey: Self.cacheKey) else { return }
        let snapshot = TodaySnapshot(
            categories: cached.value.categories, entries: cached.value.entries,
            streaks: cached.value.streaks, usage: usage, day: cached.value.day
        )
        cache.save(snapshot, forKey: Self.cacheKey, updatedAt: cached.updatedAt, sentUnder: sentUnder)
    }

    private func usageWindow() -> (from: String, to: String) {
        let to = todayString
        return (DayCalendar.day(to, plusDays: 1 - TodayOrdering.windowDays), to)
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

    /// The records of the category before today, a day at a time, the newest day first: what the card's
    /// sheet shows under today's. Nil when the read fails, so the sheet can say so instead of showing an
    /// empty history.
    func historyDays(forCategory categoryID: Int) async -> [HistoryDay]? {
        guard let api = apiProvider() else { return nil }
        let today = todayString
        do {
            let entries = try await api.fetchEntries(categoryId: categoryID)
            let earlier = entries.filter { $0.categoryId == categoryID && $0.entryDate < today }
            return Dictionary(grouping: earlier, by: \.entryDate)
                .map { HistoryDay(date: $0.key, entries: $0.value.sorted { $0.id > $1.id }) }
                .sorted { $0.date > $1.date }
        } catch {
            return nil
        }
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
    /// `day` is the day it happened on (`yyyy-MM-dd`); nil, or today's date, is the server's today.
    @discardableResult
    func recordRelapse(categoryID: Int, on day: String? = nil) async -> Bool {
        let day = day == todayString ? nil : day
        saveErrorMessage = nil
        switch relapseState(forCategory: categoryID) {
        case .recording, .undoing, .savingDetails:
            return false
        case .idle, .recorded:
            break
        }
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return false
        }
        let previous = relapseState(forCategory: categoryID)
        // A retry of the same day is the same request; another day is another relapse.
        let key = relapseKeys[categoryID].flatMap { $0.day == day ? $0.key : nil } ?? UUID().uuidString
        relapseKeys[categoryID] = (day: day, key: key)
        relapseStates[categoryID] = .recording
        let landed: RelapseRecordedDTO
        do {
            landed = try await api.recordRelapse(
                categoryId: categoryID, entryDate: day, idempotencyKey: key
            )
        } catch let error as APIClientError {
            relapseStates[categoryID] = previous
            saveErrorMessage = error.isConnectivity
                ? "\(Self.relapseFailedMessage): \(error.userMessage)" : error.userMessage
            return false
        } catch {
            relapseStates[categoryID] = previous
            saveErrorMessage = Self.relapseFailedMessage
            return false
        }
        relapseKeys[categoryID] = nil
        // A repeated tap within the minute gets this screen's own relapse back with `created: false`;
        // it is still the relapse this screen wrote, so the undo stays.
        var recorded = landed
        if case .recorded(let before) = previous, before.entry.id == landed.entry.id, before.created {
            recorded = RelapseRecordedDTO(entry: landed.entry, created: true)
        }
        relapseStates[categoryID] = .recorded(recorded)
        place(recorded.entry)
        await refreshStreak(categoryID: categoryID, api: api)
        return true
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
        remove(entryID: recorded.entry.id)
        await refreshStreak(categoryID: categoryID, api: api)
    }

    /// Adds the optional "how much" and a note to the relapse the tap wrote, and moves it to another day
    /// when `day` differs from the one it holds. PATCH replaces the whole value list, so what the
    /// server wrote for the tap goes back along with the amount.
    func saveRelapseDetails(
        categoryID: Int, amount: String, notes: String, day: String? = nil
    ) async -> Bool {
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
        let movedTo = day.flatMap { $0 == recorded.entry.entryDate ? nil : $0 }
        guard values != nil || note != nil || movedTo != nil else { return true }

        relapseStates[categoryID] = .savingDetails(recorded)
        do {
            let updated = try await api.updateEntry(
                id: recorded.entry.id,
                EntryUpdateDTO(entryDate: movedTo, notes: note, values: values)
            )
            relapseStates[categoryID] = .recorded(
                RelapseRecordedDTO(entry: updated, created: recorded.created)
            )
            place(updated)
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

    /// Puts the entry into today's list, or takes it out when it belongs to another day.
    private func place(_ entry: EntryDTO) {
        if entry.entryDate == todayString {
            upsert(entry)
        } else {
            remove(entryID: entry.id)
        }
    }

    /// Replaces the entry in place when the list already holds it, appends it otherwise.
    private func upsert(_ entry: EntryDTO) {
        if let index = serverEntries.firstIndex(where: { $0.id == entry.id }) {
            serverEntries[index] = entry
        } else {
            serverEntries.append(entry)
        }
        redrawPending()
    }

    /// The entry is gone from the server: from the rows and from what is laid over older reads.
    private func remove(entryID: Int) {
        serverEntries.removeAll { $0.id == entryID }
        deliveredEntries.removeAll { $0.entry.id == entryID }
        redrawPending()
    }

    // MARK: Day changes made elsewhere

    /// A quick-mark tap or undo moved the day of this category: read the day's records again, and the
    /// streak when the category is an avoid one. Pending rows of the offline outbox stay. A call while
    /// such a re-read runs is folded into one more after it.
    func reloadAfterMark(categoryID: Int) async {
        guard let api = apiProvider() else { return }
        markRereadQueue.insert(categoryID)
        guard !isRereadingAfterMark else { return }
        isRereadingAfterMark = true
        defer { isRereadingAfterMark = false }
        while !markRereadQueue.isEmpty {
            let moved = markRereadQueue
            markRereadQueue = []
            await rereadEntries(reportsFailure: true)
            for categoryID in moved.sorted() where categories.first(where: { $0.id == categoryID })?.isAvoid == true {
                await refreshStreak(categoryID: categoryID, api: api)
            }
        }
    }

    /// Reads today's records again without the loader: the screen stays as it is while the read runs.
    /// A failure is reported only when it follows something the person did.
    private func rereadEntries(reportsFailure: Bool) async {
        guard let api = apiProvider() else { return }
        let read = nextEntriesRead()
        let today = todayString
        let sentUnder = cache.scope
        do {
            let fetched = try await api.fetchEntries(startDate: today, endDate: today)
            if showsEntries(of: read) {
                showServerRows(fetched, read: read)
                shownDay = today
                cacheShownEntries(sentUnder: sentUnder)
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
        remove(entryID: id)
        if let categoryID, categories.first(where: { $0.id == categoryID })?.isAvoid == true {
            await refreshStreak(categoryID: categoryID, api: api)
        }
        return true
    }

    // MARK: Plus

    /// The plus of a row whose plan is a step or a tick: writes it to today as one entry (a checklist's
    /// idempotent day upsert). Every press is one entry under a key of its own, shown at once; the save
    /// is the form save. True when saved or queued.
    @discardableResult
    func quickAdd(categoryID: Int, amount typed: Double? = nil) async -> Bool {
        guard let category = categories.first(where: { $0.id == categoryID }) else { return false }
        let fieldID: Int
        let value: String
        switch (TodayQuickAdd.plan(for: category), typed) {
        case (.step(let id, _), let amount?), (.amountSheet(let id), let amount?):
            (fieldID, value) = (id, TodayQuickAdd.formatAmount(amount))
        case (.step(let id, let amount), nil):
            (fieldID, value) = (id, TodayQuickAdd.formatAmount(amount))
        case (.check(let id), _):
            // Today already holds the tick (a queued one too): a second tap writes nothing.
            if isTicked(categoryID: categoryID) { return false }
            (fieldID, value) = (id, "true")
        case (.amountSheet, nil), (.textSheet, _), (.fullForm, _):
            return false
        }
        var values = TodayQuickAdd.defaultValues(for: category, except: fieldID)
        values[fieldID] = value
        return await saveEntry(categoryID: categoryID, values: values)
    }

    /// True when the category is a one-tap tick and today already holds it, saved or still queued.
    func isTicked(categoryID: Int) -> Bool {
        guard let category = categories.first(where: { $0.id == categoryID }),
              case .check(let fieldID) = TodayQuickAdd.plan(for: category) else { return false }
        return entries(forCategory: categoryID).contains { entry in
            entry.values.contains { $0.fieldId == fieldID && $0.value == "true" }
        }
    }

    /// Saves today's values for the category. Form categories create a new entry
    /// via generic POST under a fresh Idempotency-Key; checklist categories go through the
    /// idempotent `PUT /entries/checklist` upsert (one entry per category+date on the backend).
    /// With the outbox the save is queued — the form under the key of this press, both with today's
    /// date — drawn at once as a row of the day and sent behind the caller; a refusal comes back as a
    /// line. Without one it is sent directly. Returns true when saved or queued.
    func saveEntry(categoryID: Int, values: [Int: String]) async -> Bool {
        saveErrorMessage = nil
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return false
        }
        let category = categories.first { $0.id == categoryID }
        let label = category?.name ?? "Запись"
        let checklist = category?.isChecklist == true ? ChecklistUpsertDTO(
            categoryId: categoryID,
            entryDate: todayString,
            values: Dictionary(uniqueKeysWithValues: values.map { (String($0.key), $0.value == "true") })
        ) : nil
        let form = EntryCreateDTO(
            categoryId: categoryID,
            entryDate: todayString,
            notes: nil,
            values: values
                .sorted { $0.key < $1.key }
                .map { EntryValueDTO(fieldId: $0.key, value: $0.value) }
        )
        if let outbox {
            // A newer checklist save of the day replaces a waiting one; one already on its way lands first.
            outbox.enqueue(checklist.map(OutboxAction.upsertChecklist) ?? .createEntry(form), label: label)
            outbox.send()
            return true
        }
        do {
            let saved: EntryDTO
            if let payload = checklist {
                saved = try await api.upsertChecklistEntry(payload)
            } else {
                saved = try await api.createEntry(form, idempotencyKey: UUID().uuidString)
            }
            // The checklist upsert can return an entry we already loaded — replace
            // it in place so the list never shows duplicates.
            upsert(saved)
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

/// One day of a category's history.
struct HistoryDay: Identifiable, Equatable {
    let date: String
    let entries: [EntryDTO]

    var id: String { date }
}
