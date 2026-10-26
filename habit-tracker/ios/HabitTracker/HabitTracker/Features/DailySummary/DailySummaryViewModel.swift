// [review:need-review] PHASE-01/213
// summary: day-summary flow state — dictation into an editable text, the draft from the server, per-row opt-in (doubtful rows start off), the day's journal text (append/create by default, replace only on request), one idempotent apply per plan; nothing reaches the server except the draft request until the person confirms
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
    @Published private(set) var metricEnabled: [Bool] = []
    @Published private(set) var checkEnabled: [Bool] = []
    /// The day's text ships by default: appending or creating loses nothing.
    @Published var journalEnabled = true
    /// Replacing drops the old text, so it is off until the person turns it on.
    @Published var journalReplace = false
    @Published private(set) var categories: [CategoryDTO] = []

    private let apiProvider: () -> DailySummaryAPI?
    private let speech: SpeechDictating
    private let dateFormatter: DateFormatter
    private let now: () -> Date
    private let onApplied: () -> Void
    private var planDate = ""
    private var applyKey = UUID().uuidString
    private var listenTask: Task<Void, Never>?

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
        guard !isListening else { return }
        speechMessage = nil
        switch await speech.requestAccess() {
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
        guard !isListening else { return }
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
            } catch {
                self?.speechMessage = "Распознавание прервалось. Услышанное сохранено, проверьте текст."
            }
            self?.commitInterim()
            self?.isListening = false
        }
    }

    func stopDictation() {
        guard isListening else { return }
        speech.stop()
        isListening = false
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

    // MARK: - Draft

    var canGenerate: Bool {
        if case .loading = draftState { return false }
        return !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isListening
    }

    func generate() async {
        // A half-said sentence is not a day: finish listening, and let the last phrase land first.
        if isListening {
            stopDictation()
        }
        await dictationFinished()
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        guard let api = apiProvider() else {
            draftState = .failure(Self.notConfiguredMessage)
            return
        }
        draftState = .loading
        applyState = .idle
        let date = dateFormatter.string(from: now())
        do {
            let plan = try await api.draftDailySummary(
                DailySummaryDraftRequestDTO(transcript: text, entryDate: date)
            )
            planDate = date
            metricEnabled = plan.metrics.map { !$0.uncertain && !$0.implausible }
            checkEnabled = plan.checklist.map { !$0.uncertain }
            // A plan is one intent to write one day; a retry of it keeps the key, a new plan does not.
            applyKey = UUID().uuidString
            journalEnabled = true
            journalReplace = false
            draftState = .done(plan)
        } catch {
            draftState = .failure(Self.draftMessage(for: error))
        }
    }

    // MARK: - Preview

    var plan: DailySummaryDraftDTO? {
        if case .done(let plan) = draftState { return plan }
        return nil
    }

    func setMetric(_ index: Int, enabled: Bool) {
        guard metricEnabled.indices.contains(index) else { return }
        metricEnabled[index] = enabled
    }

    func setCheck(_ index: Int, enabled: Bool) {
        guard checkEnabled.indices.contains(index) else { return }
        checkEnabled[index] = enabled
    }

    var canReplaceJournal: Bool {
        plan?.journal?.existingEntryId != nil
    }

    /// The journal operation as it would be sent, or nil when it is off. A replace the day cannot
    /// honour (nothing to replace) changes nothing.
    private var journalToSend: JournalOpDTO? {
        guard journalEnabled, var journal = plan?.journal else { return nil }
        if journalReplace && canReplaceJournal {
            journal.mode = JournalOpDTO.modeReplace
        }
        return journal
    }

    /// Everything the confirm would write: numbers, ticks and the day's text.
    var enabledCount: Int {
        metricEnabled.filter { $0 }.count + checkEnabled.filter { $0 }.count
            + (journalToSend == nil ? 0 : 1)
    }

    var canApply: Bool {
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
        guard canApply, let plan, let api = apiProvider() else { return }
        let request = DailySummaryApplyRequestDTO(
            entryDate: planDate,
            metrics: zip(plan.metrics, metricEnabled).filter { $0.1 }.map(\.0),
            checklist: zip(plan.checklist, checkEnabled).filter { $0.1 }.map(\.0),
            journal: journalToSend
        )
        applyState = .applying
        do {
            _ = try await api.applyDailySummary(request, idempotencyKey: applyKey)
            applyState = .applied
            onApplied()
        } catch {
            applyState = .failure(Self.applyMessage(for: error))
        }
    }

    /// Back to an empty screen for the next day's retelling.
    func reset() {
        stopDictation()
        transcript = ""
        interim = ""
        speechMessage = nil
        draftState = .idle
        applyState = .idle
        metricEnabled = []
        checkEnabled = []
        journalEnabled = true
        journalReplace = false
    }

    // MARK: - Messages

    private static let offlineMessage = "Нет связи с сервером. Текст сохранён, попробуйте ещё раз."

    private static func draftMessage(for error: Error) -> String {
        switch error as? APIClientError {
        case .unexpectedStatus(503):
            return "Разбор дня выключен на сервере: у него нет доступа к модели."
        case .unexpectedStatus(502):
            return "Не удалось разобрать день: модель ответила с ошибкой. Текст сохранён, попробуйте ещё раз."
        case .timeout, .transport:
            return offlineMessage
        case .some(let known):
            return "Не удалось разобрать день. \(known.userMessage)"
        case nil:
            return "Не удалось разобрать день"
        }
    }

    private static func applyMessage(for error: Error) -> String {
        switch error as? APIClientError {
        case .unexpectedStatus(400), .unexpectedStatus(409), .unexpectedStatus(422):
            return "Сервер не принял план: категория или поле изменились. Разберите день заново."
        case .timeout, .transport:
            return "Нет связи с сервером. Ничего не записано или запись уже прошла: повторите, дубля не будет."
        case .some(let known):
            return "Не удалось записать день. \(known.userMessage)"
        case nil:
            return "Не удалось записать день"
        }
    }
}
