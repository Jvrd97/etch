// [review:need-review] PHASE-01/213, PHASE-03/227, PHASE-03/230, PHASE-03/250
// summary: day-summary flow state — dictation into an editable text (stopped by a call, a route change or the background), the day being told (today by default, a new Idempotency-Key per day), a cancellable draft, per-row opt-in (doubtful rows start off), the day's journal text (append/create by default, replace only on request), one idempotent apply per plan whose plan is frozen after an unanswered write (only a 400/422 proves nothing was written, a 401 changes nothing either way, a 409 ends the write as already applied); the day moved away from a plan drops the plan; closing the sheet over an unconfirmed write asks first; nothing reaches the server except the draft request until the person confirms; DailySummaryRetainer hands a model with an unconfirmed write to the next visit of the More screen (it adopts the model the screen shows and lets it go after an ordinary exit); `mayHaveChangedTheDay` remembers that a write left the model, for whoever must read the day again
import Foundation

@MainActor
final class DailySummaryViewModel: ObservableObject {
    enum DraftState: Equatable {
        case idle
        case loading
        case done(DailySummaryDraftDTO)
        case failure(String)
    }

    enum ApplyState: Equatable {
        case idle
        case applying
        case failure(String)
        case applied
        /// The server met a key it had already applied: the write landed on an earlier attempt.
        case alreadyApplied

        /// The day holds this plan; nothing is left to write or to retry.
        var isWritten: Bool { self == .applied || self == .alreadyApplied }
    }

    static let notConfiguredMessage = "Укажите адрес сервера в Settings"
    /// The LLM can answer for minutes on a long day; the same budget as the period analysis.
    static let draftTimeout: TimeInterval = 120

    /// The retelling. Typed or dictated, always editable: recognition mishears, and a text the
    /// person cannot fix is a day they give up on.
    @Published var transcript = ""
    /// The phrase still forming. Kept apart from `transcript` so the engine rewriting it word by
    /// word does not move the text under a person who is editing the sentence above.
    @Published private(set) var interim = ""
    @Published private(set) var isListening = false
    @Published private(set) var speechMessage: String?
    @Published private(set) var draftState: DraftState = .idle
    @Published private(set) var applyState: ApplyState = .idle
    /// The day the retelling is filed under (`YYYY-MM-DD`), today unless the person moved it.
    @Published private(set) var entryDate: String
    @Published private(set) var metricEnabled: [Bool] = []
    @Published private(set) var checkEnabled: [Bool] = []
    /// The day's text ships by default: appending or creating loses nothing.
    @Published private(set) var journalEnabled = true
    /// Replacing drops the old text, so it is off until the person turns it on.
    @Published private(set) var journalReplace = false
    @Published private(set) var categories: [CategoryDTO] = []
    /// A write got no answer (timeout, dropped connection): it may have landed. The plan stays
    /// exactly as it was sent until a retry under the same key is answered.
    @Published private(set) var applyIsUnconfirmed = false

    /// A write left this model at least once, whatever came back, and a reset does not forget it:
    /// the day may hold something new. A sheet closed without it changed nothing and owes nobody a re-read.
    private(set) var mayHaveChangedTheDay = false

    private let apiProvider: () -> DailySummaryAPI?
    private let speech: SpeechDictating
    private let dateFormatter: DateFormatter
    private let now: () -> Date
    private let onApplied: () -> Void
    private var applyKey = UUID().uuidString
    private var listenTask: Task<Void, Never>?
    private var draftTask: Task<Void, Never>?
    private var isStartingDictation = false
    /// Bumped by every stop, so a start still waiting on the permission prompt knows it was withdrawn.
    private var dictationToken = 0

    init(
        apiProvider: @escaping () -> DailySummaryAPI?,
        speech: SpeechDictating,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init,
        onApplied: @escaping () -> Void = {}
    ) {
        self.apiProvider = apiProvider
        self.speech = speech
        self.now = now
        self.onApplied = onApplied
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        self.dateFormatter = formatter
        self.entryDate = formatter.string(from: now())
    }

    static func live(onApplied: @escaping () -> Void = {}) -> DailySummaryViewModel {
        DailySummaryViewModel(
            apiProvider: { APIClient.live(timeout: draftTimeout) },
            speech: SystemSpeechRecognizer(),
            onApplied: onApplied
        )
    }

    // MARK: - Dictation

    func startDictation() async {
        guard !isListening, !isStartingDictation else { return }
        isStartingDictation = true
        defer { isStartingDictation = false }
        speechMessage = nil
        let token = dictationToken
        let access = await speech.requestAccess()
        // The sheet was closed or the app left while the system prompt was up.
        guard token == dictationToken else { return }
        switch access {
        case .granted:
            break
        case .speechDenied:
            speechMessage = "Нет доступа к распознаванию речи. Включите его в Настройках iPhone или напишите день текстом."
            return
        case .microphoneDenied:
            speechMessage = "Нет доступа к микрофону. Включите его в Настройках iPhone или напишите день текстом."
            return
        case .unavailable:
            speechMessage = "Распознавание речи сейчас недоступно. Напишите день текстом."
            return
        }
        // The previous session may still be delivering its last phrase; let it land first.
        await dictationFinished()
        guard token == dictationToken else { return }
        let stream: AsyncThrowingStream<String, Error>
        do {
            stream = try speech.start()
        } catch {
            speechMessage = "Не удалось включить микрофон. Напишите день текстом."
            return
        }
        isListening = true
        interim = ""
        listenTask = Task { [weak self] in
            do {
                for try await phrase in stream {
                    self?.interim = phrase
                }
            } catch SpeechDictationError.interrupted {
                self?.speechMessage = "Диктовка прервалась: звонок, другое приложение или смена микрофона. Услышанное сохранено. Нажмите «Говорить», чтобы продолжить."
            } catch {
                self?.speechMessage = "Распознавание прервалось. Услышанное сохранено, проверьте текст."
            }
            self?.commitInterim()
            self?.isListening = false
        }
    }

    func stopDictation() {
        dictationToken += 1
        guard isListening else { return }
        speech.stop()
        isListening = false
    }

    /// The app left the foreground: the system takes the microphone, so say why dictation stopped.
    func stopDictationForBackground() {
        // Not listening yet means the permission prompt is up, which also leaves the foreground.
        guard isListening else { return }
        stopDictation()
        speechMessage = "Диктовка остановлена: приложение ушло в фон. Услышанное сохранено."
    }

    /// Resolves once the recognizer has delivered its last phrase into `transcript`.
    func dictationFinished() async {
        await listenTask?.value
    }

    func toggleDictation() async {
        if isListening { stopDictation() } else { await startDictation() }
    }

    private func commitInterim() {
        let phrase = interim.trimmingCharacters(in: .whitespacesAndNewlines)
        interim = ""
        guard !phrase.isEmpty else { return }
        let existing = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        transcript = existing.isEmpty ? phrase : "\(existing) \(phrase)"
    }

    // MARK: - Day

    private var today: String { dateFormatter.string(from: now()) }

    var isToday: Bool { entryDate == today }

    /// Moving the day while a request is in flight or after an unanswered write would file the plan
    /// under a day nobody confirmed.
    var canChangeDay: Bool {
        draftState != .loading && applyState != .applying && !applyIsUnconfirmed && !applyState.isWritten
    }

    var canShowNextDay: Bool { canChangeDay && entryDate < today }

    func showPreviousDay() {
        if let moved = DayFormat.shift(entryDate, by: -1) { setEntryDate(moved) }
    }

    func showNextDay() {
        guard entryDate < today, let moved = DayFormat.shift(entryDate, by: 1) else { return }
        setEntryDate(moved)
    }

    func showToday() {
        setEntryDate(today)
    }

    /// A key belongs to one day: the plan filed under another day is another write.
    private func setEntryDate(_ date: String) {
        guard canChangeDay, date != entryDate, date <= today else { return }
        entryDate = date
        applyKey = UUID().uuidString
        // A plan (or the failure of its draft) belongs to one day; under another it would write what
        // nobody confirmed there.
        dropPlan()
    }

    private func dropPlan() {
        draftState = .idle
        applyState = .idle
        metricEnabled = []
        checkEnabled = []
        journalEnabled = true
        journalReplace = false
    }

    // MARK: - Draft

    var canGenerate: Bool {
        if case .loading = draftState { return false }
        guard applyState != .applying, !applyIsUnconfirmed, !applyState.isWritten else { return false }
        return !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isListening
    }

    func generate() async {
        guard canGenerate else { return }
        // Loading from the first tap: a second tap or an apply during the wait for the last phrase
        // must find the screen busy, and cancel must reach this wait too.
        let previous = draftState
        draftState = .loading
        let task = Task { [weak self] in
            guard let self else { return }
            await self.runDraft(previous: previous)
        }
        draftTask = task
        await task.value
        draftTask = nil
    }

    /// Gives up on the draft in flight. The text stays, and so does the plan that was on screen.
    func cancelDraft() {
        draftTask?.cancel()
    }

    private func restore(_ previous: DraftState) {
        if case .done = previous { draftState = previous } else { draftState = .idle }
    }

    private func runDraft(previous: DraftState) async {
        // A half-said sentence is not a day: finish listening, and let the last phrase land first.
        if isListening {
            stopDictation()
        }
        await dictationFinished()
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !Task.isCancelled, !text.isEmpty else { return restore(previous) }
        guard let api = apiProvider() else {
            draftState = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            let plan = try await api.draftDailySummary(
                DailySummaryDraftRequestDTO(transcript: text, entryDate: entryDate)
            )
            try Task.checkCancellation()
            applyState = .idle
            metricEnabled = plan.metrics.map(\.isTickedByDefault)
            checkEnabled = plan.checklist.map(\.isTickedByDefault)
            // A plan is one intent to write one day; a retry of it keeps the key, a new plan does not.
            applyKey = UUID().uuidString
            journalEnabled = true
            journalReplace = false
            draftState = .done(plan)
        } catch {
            if Self.isCancellation(error) {
                restore(previous)
            } else {
                draftState = .failure(Self.draftMessage(for: error))
            }
        }
    }

    private static func isCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        if let url = error as? URLError, url.code == .cancelled { return true }
        if case .transport(let code)? = error as? APIClientError {
            return code == URLError.cancelled.rawValue
        }
        return false
    }

    // MARK: - Preview

    var plan: DailySummaryDraftDTO? {
        if case .done(let plan) = draftState { return plan }
        return nil
    }

    /// Rows, journal mode and the day can change only while nothing is being written and no write
    /// is waiting for its answer.
    var canEditPlan: Bool {
        plan != nil && applyState != .applying && !applyIsUnconfirmed && !applyState.isWritten
    }

    func setMetric(_ index: Int, enabled: Bool) {
        guard canEditPlan, metricEnabled.indices.contains(index) else { return }
        metricEnabled[index] = enabled
    }

    func setCheck(_ index: Int, enabled: Bool) {
        guard canEditPlan, checkEnabled.indices.contains(index) else { return }
        checkEnabled[index] = enabled
    }

    func setJournalEnabled(_ enabled: Bool) {
        guard canEditPlan else { return }
        journalEnabled = enabled
    }

    func setJournalReplace(_ replace: Bool) {
        guard canEditPlan, canReplaceJournal else { return }
        journalReplace = replace
    }

    var canReplaceJournal: Bool {
        plan?.journal?.existingEntryId != nil
    }

    /// The journal text will overwrite what the day holds, not add to it.
    var isReplacingJournal: Bool {
        journalEnabled && journalReplace && canReplaceJournal
    }

    /// The journal operation as it would be sent, or nil when it is off. A replace the day cannot
    /// honour (nothing to replace) changes nothing.
    private var journalToSend: JournalOpDTO? {
        guard journalEnabled, var journal = plan?.journal else { return nil }
        if isReplacingJournal {
            journal.mode = .replace
        }
        return journal
    }

    /// Everything the confirm would write: numbers, ticks and the day's text.
    var enabledCount: Int {
        metricEnabled.filter { $0 }.count + checkEnabled.filter { $0 }.count
            + (journalToSend == nil ? 0 : 1)
    }

    var canApply: Bool {
        guard !isListening else { return false }
        switch (draftState, applyState) {
        case (.done, .idle), (.done, .failure):
            return enabledCount > 0
        default:
            return false
        }
    }

    /// "Category · Field" for the ids of an operation, ids themselves when the catalogue does not
    /// know them (deleted since the draft, or the catalogue request failed).
    func names(categoryId: Int, fieldId: Int) -> String {
        let category = categories.first { $0.id == categoryId }
        let field = category?.fields.first { $0.id == fieldId }
        return "\(category?.name ?? "категория #\(categoryId)") · \(field?.name ?? "поле #\(fieldId)")"
    }

    /// The catalogue only names things; a failure leaves ids on screen and does not stop the day.
    func loadCategories() async {
        categories = (try? await apiProvider()?.fetchCategories()) ?? categories
    }

    // MARK: - Apply

    func apply() async {
        guard canApply, let plan else { return }
        guard let api = apiProvider() else {
            applyState = .failure(Self.notConfiguredMessage)
            return
        }
        let request = DailySummaryApplyRequestDTO(
            entryDate: entryDate,
            metrics: zip(plan.metrics, metricEnabled).filter { $0.1 }.map(\.0),
            checklist: zip(plan.checklist, checkEnabled).filter { $0.1 }.map(\.0),
            journal: journalToSend
        )
        applyState = .applying
        mayHaveChangedTheDay = true
        do {
            _ = try await api.applyDailySummary(request, idempotencyKey: applyKey)
            applyIsUnconfirmed = false
            applyState = .applied
            onApplied()
        } catch {
            // The key was already applied: the day holds the plan, and a retry would meet the same 409.
            if case .unexpectedStatus(409)? = error as? APIClientError {
                applyIsUnconfirmed = false
                applyState = .alreadyApplied
                return
            }
            applyIsUnconfirmed = Self.unconfirmedAfter(error, was: applyIsUnconfirmed)
            applyState = .failure(Self.applyMessage(for: error, unconfirmed: applyIsUnconfirmed))
        }
    }

    /// Closing drops the key, and the next retelling would write the day a second time.
    var closeNeedsConfirmation: Bool {
        applyIsUnconfirmed || applyState == .applying
    }

    /// Back to an empty screen for the next day's retelling.
    func reset() {
        stopDictation()
        cancelDraft()
        transcript = ""
        interim = ""
        speechMessage = nil
        draftState = .idle
        applyState = .idle
        applyIsUnconfirmed = false
        metricEnabled = []
        checkEnabled = []
        journalEnabled = true
        journalReplace = false
        entryDate = today
        applyKey = UUID().uuidString
    }

    // MARK: - Messages

    /// Only a 400/422 proves the server wrote nothing. A 401 or a bad address never reached the
    /// write, so they say nothing about an earlier attempt that got no answer: the flag stays as it
    /// was. Any other failure (no answer, a broken answer, a server error) may hide a write that
    /// went through. A 409 is not here: it proves the write landed (see `apply()`).
    private static func unconfirmedAfter(_ error: Error, was unconfirmed: Bool) -> Bool {
        switch error as? APIClientError {
        case .unexpectedStatus(400), .unexpectedStatus(422):
            return false
        case .unauthorized, .invalidBaseURL:
            return unconfirmed
        default:
            return true
        }
    }

    private static func draftMessage(for error: Error) -> String {
        switch error as? APIClientError {
        case .unexpectedStatus(503):
            return "Разбор дня выключен на сервере: у него нет доступа к модели."
        case .unexpectedStatus(502):
            return "Не удалось разобрать день: модель ответила с ошибкой. Текст сохранён, попробуйте ещё раз."
        case .timeout, .transport:
            return "Нет связи с сервером. Текст сохранён, попробуйте ещё раз."
        case .unauthorized, .invalidBaseURL:
            return "Не удалось разобрать день. \(accessProblem(error)) Текст сохранён."
        case .some(let known):
            return "Не удалось разобрать день. \(known.userMessage)"
        case nil:
            return "Не удалось разобрать день"
        }
    }

    private static func accessProblem(_ error: Error) -> String {
        if case .invalidBaseURL? = error as? APIClientError {
            return "Адрес сервера неверный: проверьте его в Settings."
        }
        return "Сервер не принял ключ API: проверьте его в Settings."
    }

    private static func applyMessage(for error: Error, unconfirmed: Bool) -> String {
        switch error as? APIClientError {
        case .unexpectedStatus(400), .unexpectedStatus(422):
            return "Сервер не принял план: категория или поле изменились. Ничего не записано. Разберите день заново."
        case .some(.unauthorized), .some(.invalidBaseURL):
            let reason = accessProblem(error)
            return unconfirmed
                ? "\(reason) Предыдущая попытка могла пройти. Чтобы поправить ключ, придётся закрыть экран; перед новым рассказом проверьте записи за день."
                : "\(reason) Ничего не записано."
        case nil, .some:
            return "Нет ответа от сервера: запись могла пройти. Нажмите «Повторить запись», дубля не будет. Пока ответа нет, план менять нельзя."
        }
    }
}

/// Keeps the model of the More screen alive when the system pops the screen without asking (a second
/// tap on the selected tab): a model that holds a write nobody answered is handed to the next visit,
/// so the idempotency key survives. Only the model the screen really shows is kept — the screen adopts
/// it when it appears — and it is let go after an ordinary exit; the person's own leave calls `release()`.
@MainActor
final class DailySummaryRetainer {
    private let make: @MainActor () -> DailySummaryViewModel
    private var held: DailySummaryViewModel?

    init(make: @escaping @MainActor () -> DailySummaryViewModel = { .live() }) {
        self.make = make
    }

    /// The model for a visit: the one with the unanswered write if there is one, otherwise a new one.
    /// Nothing is stored here, so a model that is asked for and never shown is not mistaken for the shown one.
    func model() -> DailySummaryViewModel {
        if let held, held.closeNeedsConfirmation { return held }
        held = nil
        return make()
    }

    /// The screen shows `model`: it is the one to keep if the screen is taken away.
    func adopt(_ model: DailySummaryViewModel) {
        held = model
    }

    /// The screen went away. A model with nothing to lose goes with it; one with an unanswered write waits for the next visit.
    func screenLeft(_ model: DailySummaryViewModel) {
        if held === model, !model.closeNeedsConfirmation { held = nil }
    }

    func release() {
        held = nil
    }
}
