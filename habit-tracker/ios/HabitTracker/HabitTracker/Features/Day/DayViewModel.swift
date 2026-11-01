// [review:need-review] PHASE-01/274
// [review:need-review] PHASE-01/270 — show(date:)
// [review:need-review] PHASE-01/211, PHASE-03/226, PHASE-03/225, PHASE-03/231, PHASE-03/242, PHASE-03/248, PHASE-03/256, PHASE-03/263
// summary: PHASE-03/263 — a queued notebook save counts as delivered by its own write id (a refused older write of the same day does not hide it); `newestCached` never evicts the key just written
// summary: PHASE-03/248, 256 — a save that ended on another day rebases the draft typed over its base (no false conflict on coming back); an older answer is swapped for the saved text only when it holds the base or that text, a third text is a conflict beside the saved one; the cache keeps the newest read of each key; a direct mark refused with 502/504 is queued as one that may have landed (no read, no apology)
// summary: PHASE-03/248, 256 round 2 — a third text stays a conflict until the person picks a side (typed over the base, not over itself); a queued save the server did not take is not remembered as written; a direct mark refused with 502/504 is queued as one that may have landed; the cache copy put back keeps the stamp of its read, and `newestCached` holds at most 8 days
// [review:need-review] PHASE-03/240 — only the new OutboxAction case named in one switch (markSupplementTaken)
// summary: PHASE-03/242 — the cached-day notice names the day from the cache instead of saying today is missing (wrong between midnight and 04:00); the load reads alongside the queue's send, and a day write delivered during a load reads the day again: reads are numbered, an answer older than the one shown is dropped and does not stay in the cache, a failed re-read leaves the load's day; a direct mark or notebook that lost its answer is queued as one that may have landed
// summary: Day screen state — loads GET /day for the server's today or a stepped date through the read cache (opens offline from the last copy and says when that copy is not today), optimistic mark cycle with rollback; without a network a mark, a new fact and the notebook go to the shared outbox and stay on screen through re-reads until delivered, and a mark or notebook whose older write still waits goes through the queue too (closing and fact corrections say they need the server), category-linked facts (record/correct/remove with the done/unmark rule and a retry-safe Idempotency-Key), notebook and closing fields kept per day across stepping (a notebook draft remembers the server text it was typed on; a changed server text raises a conflict instead of being overwritten; so do the closing fields), a late re-read never rolls back a notebook save (the saved text is remembered per day, so it holds after stepping away and back; the note that a save replaced the server text stays until dismissed), two-touch closing (review 15:40, final evening); silent re-read after each write, on return from the background, at midnight and on a time zone change (pull-to-refresh alone reports a failure)
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — a step with nothing cached shows the day it goes to (`steppingTo`) while the shown day stays; the next step counts from the day asked for; a step that fails names that day and points the screen back at the day shown; an appearance after midnight reads again whatever the age of the copy; the cache takes no answer of a server the address moved away from
// summary: PHASE-03/310 — the day opens from its cached copy (the cached «today» only when it is today), an appearance reads again only when the copy is not recent, a loaded day stays on screen through a step or a re-read (no loader), and a failed re-read is a line, not a replaced screen
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 round 2 — a delivered mark is laid over every read of the day sent before its delivery, so a re-read started before the second of two marks landed does not roll the tick back; the first attempt of a mark is a bare PUT (the queue checks the state it was made over only on a retry)
// summary: PHASE-03/316 — a mark goes into the outbox and the line stays free (no wait for the PUT nor the re-read): a second tap while the first is on its way is queued behind it, not dropped; the marks shown are the server's with the queued ones on top, a delivered mark takes the server's answer in the same turn and a refused one falls back and says why; re-reads after deliveries are merged into one at a time; «ждёт отправки» shows only writes that wait
import Combine
import Foundation

@MainActor
final class DayViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    /// Server values of the closing fields that changed under unsent text (nil: that field did not).
    struct ClosingConflict: Equatable {
        let body: String?
        let minutes: String?
    }

    /// What the person typed into a fact card.
    enum FactInput: Equatable {
        case text(String)
        case flag(Bool)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var detail: DayDetailDTO?
    @Published private(set) var marks: [UUID: DayMarkDTO] = [:]
    @Published private(set) var facts: [UUID: PlanItemFactsDTO] = [:]
    @Published private(set) var summary: DaySummaryDTO?
    @Published private(set) var counts: TaskCountsDTO?
    /// Lines with a write in flight; the view disables their controls.
    @Published private(set) var busyItems: Set<UUID> = []
    @Published private(set) var isSavingNotebook = false
    @Published private(set) var isClosing = false
    @Published var notebook = ""
    /// The notebook text as the server holds it; `notebook` differing from it is unsaved work.
    @Published private(set) var savedNotebook = ""
    /// The server's notebook text when it moved on while unsaved text sits on the screen;
    /// nil when there is no disagreement. Saving waits until the person picks a side.
    @Published private(set) var notebookConflict: String?
    /// True when the person's save already replaced the server text shown in `notebookConflict`.
    @Published private(set) var notebookConflictOverwritten = false
    /// Closing fields whose server value moved on while unsent text sits in them; nil when no disagreement.
    @Published private(set) var closingConflict: ClosingConflict?
    @Published var closingBody = ""
    @Published var closingMinutes = ""
    /// The zone plan windows are read in; follows the device when it changes.
    @Published private(set) var timeZone: TimeZone
    @Published var actionError: String?
    /// Non-nil while the day shown is the cached copy; the moment it was cached.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last read of a loaded screen failed; the day on screen stays.
    @Published private(set) var refreshError: String?
    /// The day being opened while another stays on screen (a step with nothing cached); nil otherwise.
    @Published private(set) var steppingTo: String?
    /// Lines of the shown day with a mark or a fact written on the phone that waits for the server — failed
    /// once, or on its way past the quiet period.
    @Published private(set) var queuedItems: Set<UUID> = []
    /// The notebook of the shown day waits in the queue.
    @Published private(set) var isNotebookQueued = false

    /// Opened offline on "today", the cache may hold an older day (the last one read): name the day shown.
    /// Not "today is missing": the phone's calendar turns at midnight and the server's day at its own
    /// boundary (04:00), so between the two the cached day is the server's today.
    var cachedDayNotice: String? {
        guard offlineAsOf != nil, requestedDate == nil, let shown = shownDate, shown != localToday else { return nil }
        return "Показан день из кэша: \(DayFormat.title(of: shown))."
    }

    private var localToday: String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: now())
    }

    static let notConfiguredMessage = "Укажите адрес сервера в настройках"
    static let unreadableValueMessage = "Введите число: «300», «3,5» или «1:30» для времени"
    static let unreadableMinutesMessage = "Минуты работы — целое число"
    static let markFailedMessage = "Отметка не сохранилась"
    static let factFailedMessage = "Факт не сохранился"
    static let closingFailedMessage = "День не закрылся"
    static let refreshFailedMessage = "День не обновился"
    static let openFailedPrefix = "Не удалось открыть"
    static let closingNeedsServerMessage =
        "Нет сети. Закрыть день можно только со связью: вердикт считает сервер. Поля остались на экране."
    static let factNeedsServerMessage = "Нет сети. Исправить или удалить факт можно только со связью."

    /// `nil` asks the server for its today.
    private(set) var requestedDate: String?
    /// The date the screen currently shows (what the server answered with).
    var shownDate: String? { detail?.day.date }
    /// The `requestedDate` whose answer is on screen: a step that fails points the screen back at it.
    private var shownRequest: String?

    private let apiProvider: () -> DayAPI?
    private let timeZoneProvider: () -> TimeZone
    private let outbox: OutboxQueue?
    private let cache: ReadThroughCache
    private let now: () -> Date
    private var cancellables: Set<AnyCancellable> = []
    /// The marks of the shown day as the server holds them; `marks` is them with the queued ones on top.
    private var serverMarks: [UUID: DayMarkDTO] = [:]
    /// Marks the server took from the queue, with their day and the newest read sent before each delivery:
    /// a read up to that number may hold an older state, so the mark is laid over its answer.
    private var deliveredMarks: [(afterRead: Int, date: String, mark: DayMarkDTO)] = []
    /// A re-read after a delivery is running, and another delivery came during it: one more follows.
    private var isRereadingAfterDelivery = false
    private var rereadsAfterDelivery = false
    private var loadedDate: String?
    /// Bumped by every load (`showFailure`): an answer of a read sent before it is for what the screen
    /// asked earlier (another day) and is dropped.
    private var loadGeneration = 0
    /// The load in flight and the day it reads, so a second ask for the same day does not read again.
    private var runningLoad: (date: String?, task: Task<Void, Never>)?
    /// Reads of the day, numbered as they are sent, and the newest one shown. A load reads alongside
    /// the queue's send, so its answer may come back after the re-read a delivery started: an answer
    /// older than the one on screen is dropped, and a failed re-read leaves the load's answer in place.
    private var readsSent = 0
    private var readShown = 0
    /// Unsaved notebook text of days the person stepped away from, by `yyyy-MM-dd`, with the
    /// server text it was typed on. In memory only: it survives stepping, not a relaunch.
    private var notebookDrafts: [String: Typed] = [:]
    /// The same for the closing fields (minutes, what happened).
    private var closingDrafts: [String: ClosingEdit] = [:]
    /// What the server holds for the closing fields; typed values differing from it are unsent work.
    private var savedClosingBody = ""
    private var savedClosingMinutes = ""
    /// Keys of writes that have not been answered yet: a retry of the same body goes
    /// under the same key, so a lost answer cannot record a fact or a touch twice.
    private var factKeys: [UUID: (body: PlanFactRequestDTO, key: String)] = [:]
    private var closingKeys: [String: (body: DayClosingRequestDTO, key: String)] = [:]
    /// Bumped when a notebook save starts and when it ends. A re-read that was sent before
    /// either must not bring its notebook text: it may predate the save.
    private var notebookSaveEpoch = 0
    /// The last text a save of each day put on the server, the text it was typed over and the save's start
    /// epoch. A re-read of that day sent no later than that epoch is older than the save, whatever day is
    /// on screen now.
    private var savedNotebooks: [String: (text: String, base: String, epoch: Int)] = [:]
    /// The newest read whose answer went into the read cache, per key, with that answer. A load writes the
    /// cache itself when its answer arrives, so an older load answering late puts this copy back.
    private var newestCached: [String: (read: Int, day: DayDetailDTO, at: Date)] = [:]
    /// Days kept in `newestCached`: the screen steps through days one at a time, and only the ones it
    /// has just left can still have a load in flight.
    private static let newestCachedLimit = 8

    /// Text typed over a server value, with the server value it was typed on.
    private struct Typed: Equatable {
        let text: String
        let base: String
    }

    /// A field the person touched; nil is untouched and follows the server.
    private struct ClosingEdit: Equatable {
        let body: Typed?
        let minutes: Typed?
    }

    /// Without an `outbox` an offline write fails as any other error; the screen gets one from `live()`.
    init(
        apiProvider: @escaping () -> DayAPI?,
        timeZoneProvider: @escaping () -> TimeZone = { .current },
        outbox: OutboxQueue? = nil,
        cacheStore: CacheStore = InMemoryCacheStore(),
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.timeZoneProvider = timeZoneProvider
        self.timeZone = timeZoneProvider()
        self.outbox = outbox
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.now = now
        bindOutbox()
    }

    convenience init(api: DayAPI) {
        self.init(apiProvider: { api })
    }

    static func live() -> DayViewModel {
        DayViewModel(apiProvider: { APIClient.live() }, outbox: OutboxLive.shared, cacheStore: ReadCacheLive.shared)
    }

    // MARK: Offline queue

    /// The queued signs follow the queue; a delivered write of the shown day reads the day again. So does
    /// any delivered day write while a load is running: the load's read may have left before the
    /// delivery (the queue sends alongside it), and nothing is shown yet, or it is another day, to
    /// match against. The re-read is newer, so the load's answer is dropped if it comes back later.
    private func bindOutbox() {
        guard let outbox else { return }
        outbox.$writes
            .sink { [weak self] writes in
                MainActor.assumeIsolated { self?.redrawQueued(writes) }
            }
            .store(in: &cancellables)
        outbox.delivered
            .sink { [weak self] delivery in
                MainActor.assumeIsolated { self?.settle(delivery) }
            }
            .store(in: &cancellables)
        outbox.refused
            .sink { [weak self] write in
                MainActor.assumeIsolated {
                    guard let self, let date = self.shownDate, write.action.isDayWrite(of: date) else { return }
                    self.actionError = "\(write.label): \(write.failure ?? Self.markFailedMessage)"
                }
            }
            .store(in: &cancellables)
    }

    /// A delivered mark of the shown day takes the server's answer in the same turn as the queue dropped
    /// it, so the tick does not fall back for a frame; the day is then read again behind the screen.
    private func settle(_ delivery: OutboxDelivery) {
        let action = delivery.write.action
        if case .setDayMark(let mark) = action, mark.date == shownDate, case .dayMark(let stored)? = delivery.reply {
            serverMarks[mark.itemID] = stored
            showMarks(outbox?.writes ?? [])
        }
        if case .setDayMark(let mark) = action, case .dayMark(let stored)? = delivery.reply {
            deliveredMarks.append((afterRead: readsSent, date: mark.date, mark: stored))
        }
        let ofShownDay = shownDate.map { action.isDayWrite(of: $0) } ?? false
        let duringLoad = runningLoad != nil && action.writesADay
        guard ofShownDay || duringLoad else { return }
        Task { await rereadAfterDelivery() }
    }

    /// One re-read at a time for deliveries: a burst of them reads the day twice, not once per write.
    private func rereadAfterDelivery() async {
        guard !isRereadingAfterDelivery else {
            rereadsAfterDelivery = true
            return
        }
        isRereadingAfterDelivery = true
        defer { isRereadingAfterDelivery = false }
        repeat {
            rereadsAfterDelivery = false
            await reloadSilently()
        } while rereadsAfterDelivery
    }

    private func redrawQueued(_ writes: [OutboxWrite]) {
        showMarks(writes)
        let pending = writes.filter { $0.status == .pending }
        guard let date = shownDate else {
            queuedItems = []
            isNotebookQueued = false
            return
        }
        let moment = now()
        queuedItems = Set(pending.filter { $0.isOverdue(at: moment) }.compactMap { $0.action.queuedItem(of: date) })
        isNotebookQueued = pending.contains { $0.action.queuedNotebook(of: date) != nil }
    }

    /// The server's marks of the shown day with the queued ones on top: a queued mark is not on the server yet.
    private func showMarks(_ writes: [OutboxWrite]) {
        var shown = serverMarks
        for write in writes where write.status == .pending {
            guard case .setDayMark(let mark) = write.action, mark.date == shownDate else { continue }
            shown[mark.itemID] = DayMarkDTO(itemId: mark.itemID, state: mark.state, note: mark.note)
        }
        if shown != marks { marks = shown }
    }

    /// The title of a plan line, for the list of waiting writes.
    private func itemTitle(_ itemID: UUID) -> String {
        func find(_ items: [DayPlanItemDTO]) -> DayPlanItemDTO? {
            for item in items {
                if item.id == itemID { return item }
                if let child = find(item.children) { return child }
            }
            return nil
        }
        return find(detail?.plan?.sections.flatMap(\.items) ?? [])?.textPlain ?? "пункт плана"
    }

    private static func isOffline(_ error: Error) -> Bool {
        (error as? APIClientError)?.isConnectivity == true
    }

    // MARK: Loading

    /// The read-cache key of the day asked for.
    private var cacheKey: String { "day.\(requestedDate ?? "today")" }

    /// The tab came on: the cached copy of the day goes on screen at once, and the server is asked only
    /// when that copy is not recent.
    func appear() async {
        showCached()
        // Past midnight the server's today has moved: a recent copy of yesterday is not today.
        let showsAskedDay = requestedDate != nil || shownDate == localToday
        if state == .loaded, showsAskedDay, cache.isRecent(key: cacheKey) { return }
        await load()
    }

    /// Puts the cached copy of the day asked for on screen, without the network, unless that day is shown
    /// already. The cached «today» of another day is not today: the screen waits for the server then.
    func showCached() {
        guard let cached = cache.peek(DayDetailDTO.self, key: cacheKey) else { return }
        let date = cached.value.day.date
        if requestedDate == nil, date != localToday { return }
        guard state != .loaded || date != shownDate else { return }
        offlineAsOf = nil
        // A save made in this run may be newer than the copy: its text outranks the copy's.
        apply(cached.value, read: nil, keepingNotebook: false, savedSince: savedNotebooks[date])
        shownRequest = requestedDate
        state = .loaded
    }

    /// Waiting writes go out alongside the read, so a reload is also a retry of the queue; a slow send
    /// does not hold the day back (waiting writes are laid over it, a delivery reads it again).
    /// A loaded day stays on screen while another is read: no loader on a step.
    func load() async {
        // The same day already being read: join that read, one GET and one spinner.
        if let running = runningLoad, running.date == requestedDate {
            await running.task.value
            return
        }
        showCached()
        if state != .loaded { state = .loading }
        // Another day stays on screen until this one comes: the header names where the step goes.
        let target = requestedDate ?? localToday
        steppingTo = state == .loaded && target != shownDate ? target : nil
        let task = Task { [self] in
            let flushing = Task { await outbox?.flush() }
            await fetch(showFailure: true)
            await flushing.value
        }
        let mine = (date: requestedDate, task: task)
        runningLoad = mine
        await task.value
        if runningLoad?.task == mine.task {
            runningLoad = nil
            steppingTo = nil
        }
    }

    /// Re-read after a write: counts and the verdict are the server's to recount.
    /// Silent — a failure leaves the screen as it is.
    private func reloadSilently(reportingFailure: Bool = false) async {
        await fetch(showFailure: false, reportingFailure: reportingFailure)
    }

    /// `showFailure` turns the screen into the error state; `reportingFailure` only raises `actionError`
    /// for a read the person asked for, and leaves the screen as it is.
    private func fetch(showFailure: Bool, reportingFailure: Bool = false) async {
        guard let api = apiProvider() else {
            if showFailure { state = .failure(Self.notConfiguredMessage) }
            return
        }
        if showFailure { loadGeneration += 1 }
        let generation = loadGeneration
        readsSent += 1
        let read = readsSent
        let epochAtSend = notebookSaveEpoch
        let requested = requestedDate
        let sentUnder = cache.scope
        do {
            let key = cacheKey
            let outcome: CacheOutcome<DayDetailDTO>
            if showFailure {
                outcome = try await cache.load(key: key) { try await api.fetchDay(date: requested) }
            } else {
                // A silent re-read that fails leaves the screen as it is: the cached copy is older
                // than what the screen shows after a write.
                outcome = .fresh(try await api.fetchDay(date: requested))
            }
            // Before the checks below: the cache must end up with the newest answer of the key even when
            // this answer is dropped for the screen (the person stepped to another day meanwhile).
            if case .fresh(let day) = outcome {
                settleCache(key: key, read: read, day: day, loadWroteIt: showFailure, sentUnder: sentUnder)
            }
            // A newer load (stepped to another day) has taken over: drop this answer.
            guard generation == loadGeneration, read > readShown else { return }
            readShown = read
            let fetched: DayDetailDTO
            switch outcome {
            case .fresh(let day):
                offlineAsOf = nil
                fetched = day
            case .stale(let day, let updatedAt):
                offlineAsOf = updatedAt
                fetched = day
            }
            // A notebook save that ran or is running since the request left makes this answer's
            // notebook stale for the day on screen; everything else in it is still current.
            let notebookIsStale = isSavingNotebook || notebookSaveEpoch != epochAtSend
            // Another day on screen cannot keep its notebook, but the text its save wrote outranks an older answer.
            let savedSince = savedNotebooks[fetched.day.date].flatMap { epochAtSend <= $0.epoch ? $0 : nil }
            apply(
                fetched, read: read, keepingNotebook: notebookIsStale && fetched.day.date == loadedDate, savedSince: savedSince
            )
            shownRequest = requested
            refreshError = nil
            state = .loaded
        } catch {
            // A newer answer is on screen, or the screen asked for another day since: nothing to say.
            guard generation == loadGeneration, read > readShown else { return }
            if showFailure, state == .loaded, detail != nil, requested != shownRequest {
                // A step that did not open: say which day, and point the screen back at the day it shows.
                refreshError = Self.failure("\(Self.openFailedPrefix) \(DayFormat.title(of: requested ?? localToday))", error)
                requestedDate = shownRequest
            } else if showFailure, state == .loaded, detail != nil {
                refreshError = Self.failure(Self.refreshFailedMessage, error)
            } else if showFailure {
                state = .failure(Self.message(for: error))
            } else if reportingFailure, !Task.isCancelled {
                actionError = Self.failure(Self.refreshFailedMessage, error)
            }
        }
    }

    /// Keeps the read cache at the answer of the newest read of `key`. A read that is not the newest
    /// writes nothing; a load that is not the newest put its answer there itself, so the newest comes back.
    private func settleCache(key: String, read: Int, day: DayDetailDTO, loadWroteIt: Bool, sentUnder: String) {
        if let newest = newestCached[key], newest.read > read {
            // The copy keeps the stamp of the read it came from, not the moment it is put back.
            if loadWroteIt { cache.save(newest.day, forKey: key, updatedAt: newest.at, sentUnder: sentUnder) }
            return
        }
        let at = cache.now()
        newestCached[key] = (read, day, at)
        // The key just written is never the one evicted: it is the answer the cache holds right now.
        if newestCached.count > Self.newestCachedLimit,
           let oldest = newestCached.filter({ $0.key != key }).min(by: { $0.value.read < $1.value.read })?.key {
            newestCached[oldest] = nil
        }
        if !loadWroteIt { cache.save(day, forKey: key, updatedAt: at, sentUnder: sentUnder) }
    }

    /// Writes still in the queue are not on the server yet: their marks and notebook are laid on top.
    /// `savedSince` is the save of this day that an older answer predates: the answer's notebook text is
    /// swapped for the saved one when it is what the save was typed over or the saved text itself.
    private func apply(
        _ fetched: DayDetailDTO, read: Int?, keepingNotebook: Bool, savedSince: (text: String, base: String, epoch: Int)?
    ) {
        detail = fetched
        serverMarks = Dictionary(fetched.marks.map { ($0.itemId, $0) }, uniquingKeysWith: { _, last in last })
        // A read sent after a delivery holds that mark; an older one (or the cached copy, `read` nil) gets it
        // laid over, in the order they landed.
        if let read { deliveredMarks.removeAll { $0.afterRead < read } }
        for delivered in deliveredMarks where delivered.date == fetched.day.date {
            serverMarks[delivered.mark.itemId] = delivered.mark
        }
        showMarks(outbox?.writes ?? [])
        facts = Dictionary(fetched.planFacts.map { ($0.itemId, $0) }, uniquingKeysWith: { _, last in last })
        summary = fetched.summary
        counts = fetched.taskCounts
        let date = fetched.day.date
        var notebookEdit = unsavedNotebook
        var closingEdit = unsentClosing
        // The note "your save replaced the server text" belongs to the day it was raised on.
        let replacedNote = loadedDate == date && notebookConflictOverwritten ? notebookConflict : nil
        if loadedDate != date {
            // Leaving a day keeps what was typed and not yet saved as that day's draft;
            // coming back restores it over the server's text.
            if let leaving = loadedDate {
                notebookDrafts[leaving] = notebookEdit
                closingDrafts[leaving] = closingEdit
            }
            loadedDate = date
            notebookEdit = notebookDrafts.removeValue(forKey: date)
            closingEdit = closingDrafts.removeValue(forKey: date)
            factKeys = [:]
            closingKeys = [:]
        }
        let queuedNotebook = (outbox?.pending ?? []).compactMap { $0.action.queuedNotebook(of: date) }.last
        if !keepingNotebook {
            var server = queuedNotebook ?? fetched.notebook ?? ""
            if queuedNotebook == nil, let saved = savedSince {
                if server == saved.base || server == saved.text {
                    server = saved.text
                } else if notebookEdit == nil {
                    // A third text: somebody wrote it elsewhere. The saved text stays on screen beside it.
                    // Typed over the base, so the next re-read hands over the same text and finds the conflict
                    // still there: it ends when the person picks a side, not when the server repeats itself.
                    notebookEdit = Typed(text: saved.text, base: saved.base)
                }
            }
            seedNotebook(server: server, unsaved: notebookEdit)
            if let replacedNote, replacedNote != server, notebookConflict == nil {
                // Only "Понятно" takes the note away, not the next re-read.
                notebookConflict = replacedNote
                notebookConflictOverwritten = true
            }
        }
        seedClosing(from: fetched.summary, unsent: closingEdit)
        redrawQueued(outbox?.writes ?? [])
    }

    /// A re-read of the same day brings the server's text unless something is typed and
    /// unsaved: that stays, and a server text that moved since is shown beside it as a conflict.
    private func seedNotebook(server: String, unsaved: Typed?) {
        notebookConflictOverwritten = false
        guard let unsaved, unsaved.text != server else {
            notebook = server
            savedNotebook = server
            notebookConflict = nil
            return
        }
        notebook = unsaved.text
        savedNotebook = unsaved.base
        notebookConflict = server == unsaved.base ? nil : server
    }

    /// The same rule per closing field: typed text stays, an untouched field follows the server,
    /// and a field whose server value moved under typed text is reported in `closingConflict`.
    private func seedClosing(from summary: DaySummaryDTO, unsent: ClosingEdit?) {
        let serverMinutes = summary.workMinutes.map(String.init) ?? ""
        let body = Self.seeded(server: summary.bodyMd, typed: unsent?.body)
        let minutes = Self.seeded(server: serverMinutes, typed: unsent?.minutes)
        closingBody = body.shown
        savedClosingBody = body.base
        closingMinutes = minutes.shown
        savedClosingMinutes = minutes.base
        closingConflict = body.moved == nil && minutes.moved == nil
            ? nil : ClosingConflict(body: body.moved, minutes: minutes.moved)
    }

    private static func seeded(server: String, typed: Typed?) -> (shown: String, base: String, moved: String?) {
        guard let typed, typed.text != server else { return (server, server, nil) }
        return (typed.text, typed.base, server == typed.base ? nil : server)
    }

    private var unsavedNotebook: Typed? {
        isNotebookDirty ? Typed(text: notebook, base: savedNotebook) : nil
    }

    private var unsentClosing: ClosingEdit? {
        let edit = ClosingEdit(
            body: closingBody == savedClosingBody ? nil : Typed(text: closingBody, base: savedClosingBody),
            minutes: closingMinutes == savedClosingMinutes ? nil : Typed(text: closingMinutes, base: savedClosingMinutes)
        )
        return edit == ClosingEdit(body: nil, minutes: nil) ? nil : edit
    }

    func showPreviousDay() async { await step(by: -1) }
    func showNextDay() async { await step(by: 1) }

    /// A jump from another screen: the day asked for, `yyyy-MM-dd`. Anything else is ignored.
    func show(date: String) async {
        guard select(date: date) else { return }
        await load()
    }

    /// Points the screen at a day without reading it: the jump sets the date at once, so the read the
    /// tab's own appearance starts and the one `show(date:)` starts are the same read.
    @discardableResult
    func select(date: String) -> Bool {
        guard DayFormat.isDay(date) else { return false }
        requestedDate = date
        return true
    }

    func showToday() async {
        requestedDate = nil
        await load()
    }

    /// Back from the background or past midnight: the server's today may have turned over and
    /// the web may have edited the day. Silent, no loader; a screen that is not loaded is left alone.
    /// `reportingFailure` is for pull-to-refresh, where the person is waiting for an answer and a
    /// failure says so; the other callers stay quiet.
    func rereadInPlace(reportingFailure: Bool = false) async {
        let zone = timeZoneProvider()
        if zone != timeZone { timeZone = zone }
        guard state == .loaded else { return }
        await outbox?.flush()
        await reloadSilently(reportingFailure: reportingFailure)
    }

    /// The device moved to another zone: plan windows are read on the new wall clock.
    func systemTimeZoneDidChange() async {
        NSTimeZone.resetSystemTimeZone()
        await rereadInPlace()
    }

    /// Counts from the day asked for, not the one still on screen: two quick taps are two days.
    private func step(by days: Int) async {
        guard let current = requestedDate ?? steppingTo ?? shownDate, let moved = DayFormat.shift(current, by: days) else { return }
        requestedDate = moved
        await load()
    }

    // MARK: Marks

    func state(of itemID: UUID) -> String? { marks[itemID]?.state }

    func cycleMark(_ itemID: UUID) async {
        await setMark(itemID, state: DayFormat.nextMark(after: marks[itemID]?.state))
    }

    /// Optimistic: the tick follows the finger at once. With the outbox the mark is queued with the state
    /// it was made over and sent behind the caller; the line stays free, so a second tap while the first
    /// is on its way is queued behind it (a newer mark of a line replaces a waiting one, never the one
    /// being sent). The server's answer replaces the tick when it lands, a refusal rolls it back.
    /// Without the outbox the PUT is direct and only it holds the line; the re-read runs behind.
    func setMark(_ itemID: UUID, state newState: String?) async {
        guard let api = apiProvider() else { actionError = Self.notConfiguredMessage; return }
        guard let date = shownDate, !busyItems.contains(itemID) else { return }
        let previous = marks[itemID]
        if let outbox {
            let queued = QueuedDayMark(
                date: date, itemID: itemID, state: newState, note: previous?.note, expected: previous?.state ?? ""
            )
            outbox.enqueue(.setDayMark(queued), label: "Отметка «\(itemTitle(itemID))»", uncheckedFirstAttempt: true)
            outbox.send()
            return
        }
        marks[itemID] = DayMarkDTO(itemId: itemID, state: newState, note: previous?.note)
        busyItems.insert(itemID)
        do {
            let stored = try await api.setMark(
                date: date, itemID: itemID, DayMarkRequestDTO(state: newState, note: previous?.note)
            )
            busyItems.remove(itemID)
            serverMarks[itemID] = stored
            showMarks([])
            Task { await reloadSilently() }
        } catch {
            busyItems.remove(itemID)
            showMarks([])
            actionError = Self.message(for: error, fallback: Self.markFailedMessage)
        }
    }

    // MARK: Facts

    /// Records a new fact, or corrects `entryID`. Returns true when the server took it,
    /// so the card can clear its input.
    @discardableResult
    func saveFact(_ itemID: UUID, input: FactInput, correcting entryID: Int? = nil) async -> Bool {
        guard let api = apiProvider() else { actionError = Self.notConfiguredMessage; return false }
        guard let date = shownDate, let itemFacts = facts[itemID], !busyItems.contains(itemID) else { return false }
        guard let value = factValue(of: input, in: itemFacts), let fieldID = itemFacts.link.fieldId else {
            actionError = Self.unreadableValueMessage
            return false
        }
        let mark = entryID.map { PlanFactLogic.markAfterCorrect(itemFacts, entryID: $0, value: value) }
            ?? PlanFactLogic.markAfterRecord(itemFacts, value: value)
        let body = PlanFactRequestDTO(
            values: [PlanFactValueRequestDTO(fieldId: fieldID, value: value, unit: unit(of: itemFacts.link))],
            mark: mark
        )
        busyItems.insert(itemID)
        defer { busyItems.remove(itemID) }
        // The key of a new fact's attempt; nil for a correction, which has no key and is not queued.
        var recordKey: String?
        do {
            let written: PlanFactWriteDTO
            if let entryID {
                written = try await api.correctFact(date: date, itemID: itemID, entryID: entryID, body)
            } else {
                let key = factKey(for: itemID, body: body)
                recordKey = key
                written = try await api.recordFact(date: date, itemID: itemID, body, idempotencyKey: key)
                factKeys[itemID] = nil
            }
            applyWrite(written, itemID: itemID)
            await reloadSilently()
            return true
        } catch {
            if Self.isOffline(error), outbox != nil {
                guard let key = recordKey else {
                    actionError = Self.factNeedsServerMessage
                    return false
                }
                // A new fact waits under the key of this attempt: one that landed and lost its answer is not doubled.
                outbox?.enqueue(
                    .recordPlanFact(QueuedPlanFact(date: date, itemID: itemID, body: body)),
                    key: key, label: "Факт «\(itemTitle(itemID))»", attemptFailed: true
                )
                factKeys[itemID] = nil
                return true
            }
            actionError = Self.message(for: error, fallback: Self.factFailedMessage)
            return false
        }
    }

    func removeFact(_ itemID: UUID, entryID: Int) async {
        guard let api = apiProvider() else { actionError = Self.notConfiguredMessage; return }
        guard let date = shownDate, let itemFacts = facts[itemID], !busyItems.contains(itemID) else { return }
        let unmark = PlanFactLogic.markAfterRemove(itemFacts, entryID: entryID) == PlanFactLogic.markUnmark
        busyItems.insert(itemID)
        defer { busyItems.remove(itemID) }
        do {
            let written = try await api.removeFact(date: date, itemID: itemID, entryID: entryID, unmark: unmark)
            applyWrite(written, itemID: itemID)
            await reloadSilently()
        } catch {
            actionError = Self.isOffline(error) && outbox != nil
                ? Self.factNeedsServerMessage : Self.message(for: error, fallback: Self.factFailedMessage)
        }
    }

    private func applyWrite(_ written: PlanFactWriteDTO, itemID: UUID) {
        facts[itemID] = written.facts
        serverMarks[itemID] = written.mark
        showMarks(outbox?.writes ?? [])
    }

    private func factValue(of input: FactInput, in itemFacts: PlanItemFactsDTO) -> PlanFactValue? {
        switch input {
        case .flag(let flag):
            return .flag(flag)
        case .text(let text):
            return PlanFactLogic.parseInput(fieldType: itemFacts.link.fieldType ?? "number", text)
                .map(PlanFactValue.number)
        }
    }

    /// A duration travels in seconds, a number in the field's own unit, a box with none.
    private func unit(of link: PlanLinkDTO) -> String? {
        switch link.fieldType {
        case "duration": return PlanFactLogic.durationUnit
        case "number": return link.unit
        default: return nil
        }
    }

    private func factKey(for itemID: UUID, body: PlanFactRequestDTO) -> String {
        if let pending = factKeys[itemID], pending.body == body { return pending.key }
        let key = "fact-\(UUID().uuidString.lowercased())"
        factKeys[itemID] = (body, key)
        return key
    }

    // MARK: Notebook

    var isNotebookDirty: Bool { notebook != savedNotebook }

    func saveNotebook() async {
        guard let api = apiProvider() else { actionError = Self.notConfiguredMessage; return }
        guard let date = shownDate, !isSavingNotebook, !isNotebookSaveBlocked else { return }
        isSavingNotebook = true
        notebookSaveEpoch += 1
        let startEpoch = notebookSaveEpoch
        defer {
            isSavingNotebook = false
            notebookSaveEpoch += 1
        }
        let text = notebook
        let base = savedNotebook
        let queued = OutboxAction.saveNotebook(QueuedNotebook(date: date, content: text, expected: base))
        let label = "Блокнот за \(DayFormat.title(of: date))"
        do {
            var reachedServer = true
            if let outbox, outbox.hasPending(sameTargetAs: queued) {
                // An older save of this day still waits: the new one replaces it and goes out now if it can.
                let queuedID = outbox.enqueue(queued, label: label)
                await outbox.flush()
                // This very write still waits, or was refused and listed as not sent: the server did not take
                // this text. Another refused write of the same notebook says nothing about it.
                reachedServer = !outbox.writes.contains { $0.id == queuedID }
            } else {
                do {
                    try await api.saveNotebook(date: date, content: text)
                } catch let error where Self.isOffline(error) && outbox != nil {
                    // Kept on the phone as saved; the replay checks the server still holds what it was typed over
                    // (or this text, when the attempt may have landed and a later save replaces it).
                    outbox?.enqueue(
                        queued, label: label, mayHaveLanded: OutboxQueue.mayHaveLanded(after: error), attemptFailed: true
                    )
                    reachedServer = false
                }
            }
            // Only a text the server took is remembered against older answers; a queued one is laid over them by the queue.
            if reachedServer { savedNotebooks[date] = (text, base, startEpoch) }
            // The person may have stepped to another day while this was in flight.
            if shownDate == date {
                savedNotebook = text
                if notebookConflict == text {
                    notebookConflict = nil
                } else if notebookConflict != nil {
                    // The save replaced a server text the person was still weighing: keep it in view.
                    notebookConflictOverwritten = true
                }
            } else if let draft = notebookDrafts[date] {
                // The save ended while another day was on screen. A draft of the same text is saved; one typed
                // on the same base with more text is now typed over the saved text, which is not another person's.
                if draft.text == text {
                    notebookDrafts[date] = nil
                } else if draft.base == base {
                    notebookDrafts[date] = Typed(text: draft.text, base: text)
                }
            }
        } catch {
            actionError = Self.failure("Блокнот за \(DayFormat.title(of: date)) не сохранился", error)
        }
    }

    /// The Save button waits while a server text the person has not seen sits beside theirs.
    var isNotebookSaveBlocked: Bool { notebookConflict != nil && !notebookConflictOverwritten }

    /// The note that the server text was replaced by the save has been read.
    func dismissNotebookConflict() {
        notebookConflict = nil
        notebookConflictOverwritten = false
    }

    /// Conflict: keep the typed text. The server text is taken as the new base, so the next save is a deliberate overwrite.
    func keepMyNotebook() {
        guard let server = notebookConflict else { return }
        savedNotebook = server
        notebookConflict = nil
    }

    /// Conflict: drop the typed text for the server's.
    func useServerNotebook() {
        guard let server = notebookConflict else { return }
        notebook = server
        savedNotebook = server
        notebookConflict = nil
    }

    // MARK: Closing

    /// Touch around 15:40: records the work, rules nothing.
    func review() async { await close(touch: "review") }

    /// Evening touch: closes the day and the server rules the verdict.
    func closeDay() async { await close(touch: "final") }

    private func close(touch: String) async {
        guard let api = apiProvider() else { actionError = Self.notConfiguredMessage; return }
        guard let date = shownDate, !isClosing, closingConflict == nil else { return }
        let trimmedMinutes = closingMinutes.trimmingCharacters(in: .whitespaces)
        var minutes: Int?
        if !trimmedMinutes.isEmpty {
            guard let parsed = Int(trimmedMinutes), parsed >= 0 else {
                actionError = Self.unreadableMinutesMessage
                return
            }
            minutes = parsed
        }
        let trimmedBody = closingBody.trimmingCharacters(in: .whitespacesAndNewlines)
        let body = DayClosingRequestDTO(workMinutes: minutes, bodyMd: trimmedBody.isEmpty ? nil : trimmedBody)
        let key: String
        if let pending = closingKeys[touch], pending.body == body {
            key = pending.key
        } else {
            key = "close-\(touch)-\(UUID().uuidString.lowercased())"
            closingKeys[touch] = (body, key)
        }
        isClosing = true
        defer { isClosing = false }
        do {
            let answer = touch == "review"
                ? try await api.reviewDay(date: date, body, idempotencyKey: key)
                : try await api.closeDay(date: date, body, idempotencyKey: key)
            summary = answer
            adoptSentClosing(answer, submitted: body)
            closingKeys[touch] = nil
            await reloadSilently()
        } catch {
            // Not queued: the verdict is the server's at the moment of closing, and the fields are
            // checked against what the server holds. The key stays for the retry.
            actionError = Self.isOffline(error) && outbox != nil
                ? Self.closingNeedsServerMessage : Self.message(for: error, fallback: Self.closingFailedMessage)
        }
    }

    /// What was sent is what the server holds now, even if the re-read after it fails.
    /// A field that still shows what was sent snaps to the server's spelling (trimmed).
    private func adoptSentClosing(_ answer: DaySummaryDTO, submitted: DayClosingRequestDTO) {
        savedClosingBody = answer.bodyMd
        savedClosingMinutes = answer.workMinutes.map(String.init) ?? ""
        // A conflict raised by a re-read while the closing was in flight compared against the old base.
        closingConflict = nil
        if submitted.bodyMd != nil, closingBody.trimmingCharacters(in: .whitespacesAndNewlines) == answer.bodyMd {
            closingBody = savedClosingBody
        }
        if submitted.workMinutes != nil, closingMinutes.trimmingCharacters(in: .whitespaces) == savedClosingMinutes {
            closingMinutes = savedClosingMinutes
        }
    }

    /// Closing conflict: keep the typed fields; the server values become the base of the next send.
    func keepMyClosing() {
        guard let conflict = closingConflict else { return }
        if let body = conflict.body { savedClosingBody = body }
        if let minutes = conflict.minutes { savedClosingMinutes = minutes }
        closingConflict = nil
    }

    /// Closing conflict: drop the typed values of the moved fields for the server's.
    func useServerClosing() {
        guard let conflict = closingConflict else { return }
        if let body = conflict.body { savedClosingBody = body; closingBody = body }
        if let minutes = conflict.minutes { savedClosingMinutes = minutes; closingMinutes = minutes }
        closingConflict = nil
    }

    // MARK: Errors

    /// "<what failed>: <why>", or the plain sentence when the reason is no more than that.
    private static func failure(_ failed: String, _ error: Error) -> String {
        let reason = message(for: error, fallback: failed)
        return reason == failed ? failed : "\(failed): \(reason)"
    }

    private static func message(for error: Error, fallback: String? = nil) -> String {
        if let apiError = error as? APIClientError {
            if case .unexpectedStatus = apiError, let fallback { return fallback }
            return apiError.userMessage
        }
        return fallback ?? "Unexpected error"
    }
}

private extension OutboxAction {
    /// A plan line of `date` with a waiting mark or fact.
    func queuedItem(of date: String) -> UUID? {
        switch self {
        case .setDayMark(let mark) where mark.date == date: return mark.itemID
        case .recordPlanFact(let fact) where fact.date == date: return fact.itemID
        default: return nil
        }
    }

    func queuedNotebook(of date: String) -> String? {
        if case .saveNotebook(let notebook) = self, notebook.date == date { return notebook.content }
        return nil
    }

    func isDayWrite(of date: String) -> Bool {
        queuedItem(of: date) != nil || queuedNotebook(of: date) != nil
    }

    /// A mark, a fact or a notebook of any day.
    var writesADay: Bool {
        switch self {
        case .setDayMark, .recordPlanFact, .saveNotebook: return true
        case .createEntry, .upsertChecklist, .tapQuickMark, .markSupplementTaken: return false
        }
    }
}
