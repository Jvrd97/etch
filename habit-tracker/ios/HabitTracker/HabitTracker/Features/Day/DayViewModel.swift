// [review:need-review] PHASE-01/211, PHASE-03/226
// summary: Day screen state — loads GET /day for the server's today or a stepped date, optimistic mark cycle with rollback, category-linked facts (record/correct/remove with the done/unmark rule and a retry-safe Idempotency-Key), notebook and closing fields kept per day across stepping (a notebook draft remembers the server text it was typed on; a changed server text raises a conflict instead of being overwritten; so do the closing fields), a late re-read never rolls back a notebook save, two-touch closing (review 15:40, final evening); silent re-read after each write, on return from the background, at midnight and on a time zone change
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

    static let notConfiguredMessage = "Укажите адрес сервера в настройках"
    static let unreadableValueMessage = "Введите число: «300», «3,5» или «1:30» для времени"
    static let unreadableMinutesMessage = "Минуты работы — целое число"
    static let markFailedMessage = "Отметка не сохранилась"
    static let factFailedMessage = "Факт не сохранился"
    static let closingFailedMessage = "День не закрылся"

    /// `nil` asks the server for its today.
    private(set) var requestedDate: String?
    /// The date the screen currently shows (what the server answered with).
    var shownDate: String? { detail?.day.date }

    private let apiProvider: () -> DayAPI?
    private let timeZoneProvider: () -> TimeZone
    private var loadedDate: String?
    private var loadGeneration = 0
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

    init(apiProvider: @escaping () -> DayAPI?, timeZoneProvider: @escaping () -> TimeZone = { .current }) {
        self.apiProvider = apiProvider
        self.timeZoneProvider = timeZoneProvider
        self.timeZone = timeZoneProvider()
    }

    convenience init(api: DayAPI) {
        self.init(apiProvider: { api })
    }

    static func live() -> DayViewModel {
        DayViewModel(apiProvider: { APIClient.live() })
    }

    // MARK: Loading

    func load() async {
        state = .loading
        await fetch(showFailure: true)
    }

    /// Re-read after a write: counts and the verdict are the server's to recount.
    /// Silent — a failure leaves the screen as it is.
    private func reloadSilently() async {
        await fetch(showFailure: false)
    }

    private func fetch(showFailure: Bool) async {
        guard let api = apiProvider() else {
            if showFailure { state = .failure(Self.notConfiguredMessage) }
            return
        }
        loadGeneration += 1
        let generation = loadGeneration
        let epochAtSend = notebookSaveEpoch
        do {
            let fetched = try await api.fetchDay(date: requestedDate)
            // A newer load (stepped to another day) has taken over: drop this answer.
            guard generation == loadGeneration else { return }
            // A notebook save that ran or is running since the request left makes this answer's
            // notebook stale for the day on screen; everything else in it is still current.
            let notebookIsStale = isSavingNotebook || notebookSaveEpoch != epochAtSend
            apply(fetched, keepingNotebook: notebookIsStale && fetched.day.date == loadedDate)
            state = .loaded
        } catch {
            guard generation == loadGeneration, showFailure else { return }
            state = .failure(Self.message(for: error))
        }
    }

    private func apply(_ fetched: DayDetailDTO, keepingNotebook: Bool) {
        detail = fetched
        marks = Dictionary(fetched.marks.map { ($0.itemId, $0) }, uniquingKeysWith: { _, last in last })
        facts = Dictionary(fetched.planFacts.map { ($0.itemId, $0) }, uniquingKeysWith: { _, last in last })
        summary = fetched.summary
        counts = fetched.taskCounts
        let date = fetched.day.date
        var notebookEdit = unsavedNotebook
        var closingEdit = unsentClosing
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
        if !keepingNotebook { seedNotebook(server: fetched.notebook ?? "", unsaved: notebookEdit) }
        seedClosing(from: fetched.summary, unsent: closingEdit)
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

    func showToday() async {
        requestedDate = nil
        await load()
    }

    /// Back from the background or past midnight: the server's today may have turned over and
    /// the web may have edited the day. Silent, no loader; a screen that is not loaded is left alone.
    func rereadInPlace() async {
        timeZone = timeZoneProvider()
        guard state == .loaded else { return }
        await reloadSilently()
    }

    /// The device moved to another zone: plan windows are read on the new wall clock.
    func systemTimeZoneDidChange() async {
        NSTimeZone.resetSystemTimeZone()
        await rereadInPlace()
    }

    private func step(by days: Int) async {
        guard let current = shownDate, let moved = DayFormat.shift(current, by: days) else { return }
        requestedDate = moved
        await load()
    }

    // MARK: Marks

    func state(of itemID: UUID) -> String? { marks[itemID]?.state }

    func cycleMark(_ itemID: UUID) async {
        await setMark(itemID, state: DayFormat.nextMark(after: marks[itemID]?.state))
    }

    /// Optimistic: the tick follows the finger, the server answer replaces it, a refusal rolls it back.
    func setMark(_ itemID: UUID, state newState: String?) async {
        guard let api = apiProvider() else { actionError = Self.notConfiguredMessage; return }
        guard let date = shownDate, !busyItems.contains(itemID) else { return }
        let previous = marks[itemID]
        marks[itemID] = DayMarkDTO(itemId: itemID, state: newState, note: previous?.note)
        busyItems.insert(itemID)
        defer { busyItems.remove(itemID) }
        do {
            let stored = try await api.setMark(
                date: date, itemID: itemID, DayMarkRequestDTO(state: newState, note: previous?.note)
            )
            marks[itemID] = stored
            await reloadSilently()
        } catch {
            marks[itemID] = previous
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
        do {
            let written: PlanFactWriteDTO
            if let entryID {
                written = try await api.correctFact(date: date, itemID: itemID, entryID: entryID, body)
            } else {
                written = try await api.recordFact(
                    date: date, itemID: itemID, body, idempotencyKey: factKey(for: itemID, body: body)
                )
                factKeys[itemID] = nil
            }
            applyWrite(written, itemID: itemID)
            await reloadSilently()
            return true
        } catch {
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
            actionError = Self.message(for: error, fallback: Self.factFailedMessage)
        }
    }

    private func applyWrite(_ written: PlanFactWriteDTO, itemID: UUID) {
        facts[itemID] = written.facts
        marks[itemID] = written.mark
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
        defer {
            isSavingNotebook = false
            notebookSaveEpoch += 1
        }
        let text = notebook
        do {
            try await api.saveNotebook(date: date, content: text)
            // The person may have stepped to another day while this was in flight.
            if shownDate == date {
                savedNotebook = text
                if notebookConflict == text {
                    notebookConflict = nil
                } else if notebookConflict != nil {
                    // The save replaced a server text the person was still weighing: keep it in view.
                    notebookConflictOverwritten = true
                }
            } else if notebookDrafts[date]?.text == text {
                notebookDrafts[date] = nil
            }
        } catch {
            let failed = "Блокнот за \(DayFormat.title(of: date)) не сохранился"
            let reason = Self.message(for: error, fallback: failed)
            actionError = reason == failed ? failed : "\(failed): \(reason)"
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
            actionError = Self.message(for: error, fallback: Self.closingFailedMessage)
        }
    }

    /// What was sent is what the server holds now, even if the re-read after it fails.
    /// A field that still shows what was sent snaps to the server's spelling (trimmed).
    private func adoptSentClosing(_ answer: DaySummaryDTO, submitted: DayClosingRequestDTO) {
        savedClosingBody = answer.bodyMd
        savedClosingMinutes = answer.workMinutes.map(String.init) ?? ""
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

    private static func message(for error: Error, fallback: String? = nil) -> String {
        if let apiError = error as? APIClientError {
            if case .unexpectedStatus = apiError, let fallback { return fallback }
            return apiError.userMessage
        }
        return fallback ?? "Unexpected error"
    }
}
