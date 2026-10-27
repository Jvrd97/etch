// [review:need-review] PHASE-01/213, PHASE-03/227, PHASE-03/230, PHASE-03/250
// summary: tests for DailySummaryViewModel with a faked recognizer and API — the day (today, another day, a key per day), a plan frozen after an unanswered write, a cancellable draft, dictation stopped by a call or the background, dictation lands in the editable text and survives a refusal or a failure, nothing is sent before the person confirms, uncertain rows start off, one Idempotency-Key per plan across retries, journal replace only when asked and possible, ids are named from the catalogue; the on-device flag of the real recognizer request; whether a write ever left the model (a sheet closed without one owes Today no re-read); the retainer keeps only the model the screen adopted and lets it go after an ordinary exit
import Speech
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the day-summary API.
final class MockDailySummaryAPI: DailySummaryAPI {
    var draftResult: Result<DailySummaryDraftDTO, Error> = .success(
        DailySummaryDraftDTO(metrics: [], checklist: [], unresolved: [], journal: nil)
    )
    var applyResult: Result<DailySummaryApplyResponseDTO, Error> = .success(
        DailySummaryApplyResponseDTO(entryIds: [1], journalEntryId: nil)
    )
    var categoriesResult: Result<[CategoryDTO], Error> = .success([])
    /// Makes a request wait, so a test can act while it is in flight; a cancelled wait throws.
    var draftDelay: Duration?
    var applyDelay: Duration?
    private(set) var drafts: [DailySummaryDraftRequestDTO] = []
    private(set) var applies: [(request: DailySummaryApplyRequestDTO, key: String)] = []

    func draftDailySummary(
        _ request: DailySummaryDraftRequestDTO
    ) async throws -> DailySummaryDraftDTO {
        drafts.append(request)
        if let draftDelay { try await Task.sleep(for: draftDelay) }
        return try draftResult.get()
    }

    func applyDailySummary(
        _ request: DailySummaryApplyRequestDTO, idempotencyKey: String
    ) async throws -> DailySummaryApplyResponseDTO {
        applies.append((request, idempotencyKey))
        if let applyDelay { try await Task.sleep(for: applyDelay) }
        return try applyResult.get()
    }

    func fetchCategories() async throws -> [CategoryDTO] {
        try categoriesResult.get()
    }
}

/// A recognizer the test drives by hand: `emit` is the engine hearing words, `stop` ends the stream
/// the way the real one does after its last result.
final class FakeSpeech: SpeechDictating {
    var access: SpeechAccess = .granted
    var startError: Error?
    private(set) var startCount = 0
    private(set) var stopCount = 0
    /// While set, `stop()` leaves the stream open: the recognizer's last phrase "has not landed"
    /// until the test calls `landFinalPhrase`.
    var holdsFinalPhrase = false
    private var continuation: AsyncThrowingStream<String, Error>.Continuation?

    /// While set, the permission prompt "is up" until the test calls `answerPrompt()`.
    var holdsPrompt = false
    private var prompt: CheckedContinuation<Void, Never>?

    func requestAccess() async -> SpeechAccess {
        if holdsPrompt {
            await withCheckedContinuation { prompt = $0 }
        }
        return access
    }

    var promptIsUp: Bool { prompt != nil }

    func answerPrompt() {
        prompt?.resume()
        prompt = nil
    }

    func start() throws -> AsyncThrowingStream<String, Error> {
        startCount += 1
        if let startError { throw startError }
        return AsyncThrowingStream { self.continuation = $0 }
    }

    func stop() {
        stopCount += 1
        if !holdsFinalPhrase { continuation?.finish() }
    }

    func landFinalPhrase(_ text: String) {
        continuation?.yield(text)
        continuation?.finish()
    }

    func emit(_ text: String) { continuation?.yield(text) }
    func fail(_ error: Error) { continuation?.finish(throwing: error) }
}

@MainActor
final class DailySummaryViewModelTests: XCTestCase {
    private struct Boom: Error {}

    private func metric(
        _ source: String = "отжался 30 раз", category: Int = 4, field: Int = 9, value: Double = 30,
        uncertain: Bool = false, implausible: Bool = false, estimated: Bool = false
    ) -> LogMetricOpDTO {
        LogMetricOpDTO(
            categoryId: category, fieldId: field, value: value, sourceText: source,
            uncertain: uncertain, implausible: implausible, estimated: estimated
        )
    }

    private func check(_ source: String = "выпил витамины", uncertain: Bool = false) -> CheckOpDTO {
        CheckOpDTO(categoryId: 7, fieldId: 21, sourceText: source, uncertain: uncertain)
    }

    private func journal(mode: JournalOpDTO.Mode, existing: Int? = nil) -> JournalOpDTO {
        JournalOpDTO(
            title: nil, content: "Хороший день", mood: nil, tags: nil, mode: mode,
            existingEntryId: existing
        )
    }

    private func plan(
        metrics: [LogMetricOpDTO] = [], checklist: [CheckOpDTO] = [],
        unresolved: [UnresolvedMetricDTO] = [], journal: JournalOpDTO? = nil
    ) -> DailySummaryDraftDTO {
        DailySummaryDraftDTO(
            metrics: metrics, checklist: checklist, unresolved: unresolved, journal: journal
        )
    }

    private struct Harness {
        let viewModel: DailySummaryViewModel
        let api: MockDailySummaryAPI
        let speech: FakeSpeech
        let applied: AppliedCounter
    }

    private final class AppliedCounter { var count = 0 }

    private func makeHarness() -> Harness {
        let api = MockDailySummaryAPI()
        let speech = FakeSpeech()
        let applied = AppliedCounter()
        let viewModel = DailySummaryViewModel(
            apiProvider: { api }, speech: speech,
            timeZone: TimeZone(identifier: "UTC")!,
            now: { Date(timeIntervalSince1970: 1_792_918_800) }, // 2026-10-25 09:00 UTC
            onApplied: { applied.count += 1 }
        )
        return Harness(viewModel: viewModel, api: api, speech: speech, applied: applied)
    }

    // MARK: - Dictation

    func testDictationShowsThePhraseWhileFormingAndAppendsItWhenFinished() async {
        let h = makeHarness()
        h.viewModel.transcript = "Утром бегал."

        await h.viewModel.startDictation()
        XCTAssertTrue(h.viewModel.isListening)
        h.speech.emit("съел")
        h.speech.emit("съел борщ")
        h.viewModel.stopDictation()
        await h.viewModel.dictationFinished()

        XCTAssertFalse(h.viewModel.isListening)
        XCTAssertEqual(h.viewModel.interim, "")
        XCTAssertEqual(h.viewModel.transcript, "Утром бегал. съел борщ")
    }

    func testDictationIntoAnEmptyFieldDoesNotLeadWithASpace() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        h.speech.emit("отжался 30 раз")
        h.viewModel.stopDictation()
        await h.viewModel.dictationFinished()
        XCTAssertEqual(h.viewModel.transcript, "отжался 30 раз")
    }

    func testRefusedAccessKeepsTheTypedTextAndSaysWhy() async {
        let h = makeHarness()
        h.viewModel.transcript = "Набрал руками"
        for (access, fragment) in [
            (SpeechAccess.speechDenied, "распознавани"),
            (.microphoneDenied, "микрофон"),
            (.unavailable, "недоступно"),
        ] {
            h.speech.access = access
            await h.viewModel.startDictation()
            XCTAssertFalse(h.viewModel.isListening)
            XCTAssertEqual(h.viewModel.transcript, "Набрал руками")
            XCTAssertTrue(
                h.viewModel.speechMessage?.contains(fragment) == true,
                "\(access): \(h.viewModel.speechMessage ?? "nil")"
            )
        }
        XCTAssertEqual(h.speech.startCount, 0, "no engine is started without access")
    }

    func testEngineThatFailsToStartShowsAMessageAndKeepsTheText() async {
        let h = makeHarness()
        h.viewModel.transcript = "Набрал руками"
        h.speech.startError = Boom()

        await h.viewModel.startDictation()

        XCTAssertFalse(h.viewModel.isListening)
        XCTAssertNotNil(h.viewModel.speechMessage)
        XCTAssertEqual(h.viewModel.transcript, "Набрал руками")
    }

    func testRecognitionFailingMidSentenceKeepsWhatWasHeard() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        h.speech.emit("съел борщ")
        h.speech.fail(Boom())
        await h.viewModel.dictationFinished()

        XCTAssertEqual(h.viewModel.transcript, "съел борщ")
        XCTAssertFalse(h.viewModel.isListening)
        XCTAssertNotNil(h.viewModel.speechMessage)
    }

    func testStartingAgainWhileListeningDoesNotOpenASecondEngine() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        await h.viewModel.startDictation()
        XCTAssertEqual(h.speech.startCount, 1)
    }

    // MARK: - Draft

    func testGenerateSendsTheTrimmedTextForToday() async {
        let h = makeHarness()
        h.viewModel.transcript = "  отжался 30 раз \n"
        h.api.draftResult = .success(plan(metrics: [metric()]))

        await h.viewModel.generate()

        XCTAssertEqual(
            h.api.drafts,
            [DailySummaryDraftRequestDTO(transcript: "отжался 30 раз", entryDate: "2026-10-25")]
        )
    }

    func testBlankTextSendsNothing() async {
        let h = makeHarness()
        h.viewModel.transcript = "  \n "
        await h.viewModel.generate()
        XCTAssertTrue(h.api.drafts.isEmpty)
        XCTAssertEqual(h.viewModel.draftState, .idle)
    }

    func testGenerateWhileListeningStopsTheMicrophoneAndSendsWhatWasHeard() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        h.speech.emit("съел борщ")

        await h.viewModel.generate()

        XCTAssertEqual(h.speech.stopCount, 1)
        XCTAssertEqual(h.api.drafts.first?.transcript, "съел борщ")
    }

    func testDraftNeverWritesAnything() async {
        let h = makeHarness()
        h.viewModel.transcript = "отжался 30 раз"
        h.api.draftResult = .success(plan(metrics: [metric()], journal: journal(mode: .create)))
        await h.viewModel.generate()
        XCTAssertTrue(h.api.applies.isEmpty, "a draft is a preview; only the confirm writes")
        XCTAssertEqual(h.applied.count, 0)
    }

    func testDoubtfulRowsStartOffAndEstimatesStartOn() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(
            metrics: [
                metric("уверенно"), metric("не уверен", uncertain: true),
                metric("300 отжиманий", implausible: true), metric("борщ", estimated: true),
            ],
            checklist: [check("витамины"), check("зарядка?", uncertain: true)],
            journal: journal(mode: .create)
        ))

        await h.viewModel.generate()

        XCTAssertEqual(h.viewModel.metricEnabled, [true, false, false, true])
        XCTAssertEqual(h.viewModel.checkEnabled, [true, false])
        XCTAssertTrue(h.viewModel.journalEnabled)
        XCTAssertFalse(h.viewModel.journalReplace)
    }

    func testDraftFailureKeepsTheTextAndNamesTheCause() async {
        let h = makeHarness()
        h.viewModel.transcript = "отжался 30 раз"
        for (error, fragment) in [
            (APIClientError.unexpectedStatus(503), "выключен"),
            (APIClientError.unexpectedStatus(502), "модель"),
            (APIClientError.timeout, "связи"),
        ] {
            h.api.draftResult = .failure(error)
            await h.viewModel.generate()
            guard case .failure(let message) = h.viewModel.draftState else {
                return XCTFail("expected failure for \(error)")
            }
            XCTAssertTrue(message.contains(fragment), "\(error): \(message)")
            XCTAssertEqual(h.viewModel.transcript, "отжался 30 раз")
        }
    }

    func testNoServerAddressSaysSoWithoutARequest() async {
        let viewModel = DailySummaryViewModel(apiProvider: { nil }, speech: FakeSpeech())
        viewModel.transcript = "день"
        await viewModel.generate()
        XCTAssertEqual(viewModel.draftState, .failure(DailySummaryViewModel.notConfiguredMessage))
    }

    // MARK: - Apply

    func testApplySendsOnlyWhatStaysSwitchedOn() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        let kept = metric("отжался 30 раз")
        h.api.draftResult = .success(plan(
            metrics: [kept, metric("не уверен", uncertain: true)],
            checklist: [check("витамины")], journal: journal(mode: .create)
        ))
        await h.viewModel.generate()
        h.viewModel.setCheck(0, enabled: false)
        h.viewModel.setJournalEnabled(false)

        await h.viewModel.apply()

        let sent = h.api.applies.first?.request
        XCTAssertEqual(sent?.entryDate, "2026-10-25")
        XCTAssertEqual(sent?.metrics, [kept])
        XCTAssertEqual(sent?.checklist, [])
        XCTAssertNil(sent?.journal)
        XCTAssertEqual(h.viewModel.applyState, .applied)
        XCTAssertEqual(h.applied.count, 1)
    }

    func testApplyWithEverythingOffSendsNothing() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()], journal: journal(mode: .create)))
        await h.viewModel.generate()
        h.viewModel.setMetric(0, enabled: false)
        h.viewModel.setJournalEnabled(false)

        XCTAssertFalse(h.viewModel.canApply)
        await h.viewModel.apply()
        XCTAssertTrue(h.api.applies.isEmpty)
    }

    func testARetryAfterAFailureCarriesTheSameKeyAndANewPlanGetsANewOne() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()

        h.api.applyResult = .failure(APIClientError.timeout)
        await h.viewModel.apply()
        guard case .failure = h.viewModel.applyState else { return XCTFail("expected failure") }
        XCTAssertEqual(h.viewModel.draftState, .done(plan(metrics: [metric()])), "the plan survives")

        h.api.applyResult = .success(DailySummaryApplyResponseDTO(entryIds: [1], journalEntryId: nil))
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.count, 2)
        XCTAssertEqual(h.api.applies[0].key, h.api.applies[1].key, "a retry is the same write")
        XCTAssertEqual(h.applied.count, 1)

        h.viewModel.reset()
        h.viewModel.transcript = "день"
        await h.viewModel.generate()
        await h.viewModel.apply()
        XCTAssertNotEqual(h.api.applies[2].key, h.api.applies[0].key, "a fresh plan is a fresh intent")
    }

    func testRefusedApplyExplainsAndKeepsThePlan() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        h.api.applyResult = .failure(APIClientError.unexpectedStatus(400))

        await h.viewModel.apply()

        guard case .failure(let message) = h.viewModel.applyState else {
            return XCTFail("expected failure")
        }
        XCTAssertTrue(message.contains("заново"), message)
        XCTAssertEqual(h.applied.count, 0)
    }

    func testJournalModeIsTheServersUnlessReplaceIsAskedForAndPossible() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(journal: journal(mode: .append, existing: 55)))
        await h.viewModel.generate()

        XCTAssertTrue(h.viewModel.canReplaceJournal)
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.last?.request.journal?.mode, .append)

        h.viewModel.reset()
        h.viewModel.transcript = "день"
        await h.viewModel.generate()
        h.viewModel.setJournalReplace(true)
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.last?.request.journal?.mode, .replace)

        h.viewModel.reset()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(journal: journal(mode: .create)))
        await h.viewModel.generate()
        XCTAssertFalse(h.viewModel.canReplaceJournal)
        h.viewModel.setJournalReplace(true)
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.last?.request.journal?.mode, .create, "no text to replace")
    }

    func testAnAppliedDayCannotBeAppliedTwice() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        await h.viewModel.apply()
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.count, 1)
    }

    func testResetStartsAFreshDay() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        await h.viewModel.apply()

        h.viewModel.reset()

        XCTAssertEqual(h.viewModel.transcript, "")
        XCTAssertEqual(h.viewModel.draftState, .idle)
        XCTAssertEqual(h.viewModel.applyState, .idle)
    }

    // MARK: - Names

    func testIdsAreNamedFromTheCatalogueAndFallBackToTheIds() async {
        let h = makeHarness()
        h.api.categoriesResult = .success([
            CategoryDTO(
                id: 4, name: "Спорт", icon: nil, color: nil, displayMode: "default", isActive: true,
                fields: [FieldDTO(
                    id: 9, name: "Отжимания", fieldType: .number, isRequired: false,
                    defaultValue: nil, options: nil, order: 0
                )]
            )
        ])
        await h.viewModel.loadCategories()

        XCTAssertEqual(h.viewModel.names(categoryId: 4, fieldId: 9), "Спорт · Отжимания")
        XCTAssertEqual(h.viewModel.names(categoryId: 4, fieldId: 99), "Спорт · поле #99")
        XCTAssertEqual(h.viewModel.names(categoryId: 8, fieldId: 1), "категория #8 · поле #1")
    }

    func testACatalogueFailureDoesNotBlockTheDay() async {
        let h = makeHarness()
        h.api.categoriesResult = .failure(Boom())
        await h.viewModel.loadCategories()
        XCTAssertEqual(h.viewModel.names(categoryId: 4, fieldId: 9), "категория #4 · поле #9")
    }

    // MARK: - Helpers for in-flight states

    private func waitUntil(_ condition: () -> Bool) async {
        for _ in 0..<2000 where !condition() {
            await Task.yield()
        }
    }

    // MARK: - Day

    func testTheDayIsTodayUntilMovedAndAKeyBelongsToOneDay() async {
        let h = makeHarness()
        XCTAssertEqual(h.viewModel.entryDate, "2026-10-25")
        XCTAssertTrue(h.viewModel.isToday)
        XCTAssertFalse(h.viewModel.canShowNextDay, "the day cannot be told ahead of time")
        h.viewModel.showNextDay()
        XCTAssertEqual(h.viewModel.entryDate, "2026-10-25")

        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        XCTAssertEqual(h.api.drafts.last?.entryDate, "2026-10-25")

        h.api.applyResult = .failure(APIClientError.unexpectedStatus(400))
        await h.viewModel.apply()
        h.viewModel.showPreviousDay()
        XCTAssertEqual(h.viewModel.entryDate, "2026-10-24")
        await h.viewModel.generate()
        await h.viewModel.apply()

        XCTAssertEqual(h.api.applies.map(\.request.entryDate), ["2026-10-25", "2026-10-24"])
        XCTAssertNotEqual(h.api.applies[0].key, h.api.applies[1].key, "another day is another write")
    }

    func testMovingTheDayDropsAPlanBuiltForAnotherDay() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        h.api.applyResult = .failure(APIClientError.unexpectedStatus(422))
        await h.viewModel.apply()
        XCTAssertNotNil(h.viewModel.plan)

        h.viewModel.showPreviousDay()

        XCTAssertEqual(h.viewModel.entryDate, "2026-10-24")
        XCTAssertEqual(h.viewModel.draftState, .idle)
        XCTAssertEqual(h.viewModel.applyState, .idle)
        XCTAssertEqual(h.viewModel.metricEnabled, [])
        XCTAssertEqual(h.viewModel.transcript, "день", "the retelling stays, only the plan goes")
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.count, 1, "a plan for the other day is not written under this one")
    }

    func testADraftIsFiledUnderTheChosenDay() async {
        let h = makeHarness()
        h.viewModel.showPreviousDay()
        h.viewModel.transcript = "вчера бегал"
        await h.viewModel.generate()
        XCTAssertEqual(h.api.drafts.last?.entryDate, "2026-10-24")
    }

    // MARK: - After an unanswered write

    private func harnessWithPlanAndFailedWrite(_ error: Error) async -> Harness {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(
            metrics: [metric()], journal: journal(mode: .append, existing: 55)
        ))
        await h.viewModel.generate()
        h.api.applyResult = .failure(error)
        await h.viewModel.apply()
        return h
    }

    func testAnUnansweredWriteFreezesThePlanUntilTheRetryIsAnswered() async {
        let h = await harnessWithPlanAndFailedWrite(APIClientError.timeout)

        XCTAssertTrue(h.viewModel.applyIsUnconfirmed)
        guard case .failure(let message) = h.viewModel.applyState else { return XCTFail("expected failure") }
        XCTAssertTrue(message.contains("Повторить запись"), message)

        h.viewModel.setMetric(0, enabled: false)
        h.viewModel.setJournalEnabled(false)
        h.viewModel.setJournalReplace(true)
        h.viewModel.showPreviousDay()
        XCTAssertEqual(h.viewModel.metricEnabled, [true])
        XCTAssertTrue(h.viewModel.journalEnabled)
        XCTAssertFalse(h.viewModel.journalReplace)
        XCTAssertEqual(h.viewModel.entryDate, "2026-10-25")
        XCTAssertFalse(h.viewModel.canGenerate, "rebuilding the plan would orphan the write that may have landed")
        await h.viewModel.generate()
        XCTAssertEqual(h.api.drafts.count, 1)

        h.api.applyResult = .success(DailySummaryApplyResponseDTO(entryIds: [1], journalEntryId: 55))
        await h.viewModel.apply()

        XCTAssertFalse(h.viewModel.applyIsUnconfirmed)
        XCTAssertEqual(h.viewModel.applyState, .applied)
        XCTAssertEqual(h.api.applies.count, 2)
        XCTAssertEqual(h.api.applies[0].key, h.api.applies[1].key)
        XCTAssertEqual(h.api.applies[0].request, h.api.applies[1].request, "the retry is the same write")
    }

    func testABrokenAnswerIsTreatedAsUnconfirmedToo() async {
        let h = await harnessWithPlanAndFailedWrite(APIClientError.invalidResponse)
        XCTAssertTrue(h.viewModel.applyIsUnconfirmed)
        let server = await harnessWithPlanAndFailedWrite(APIClientError.unexpectedStatus(500))
        XCTAssertTrue(server.viewModel.applyIsUnconfirmed)
    }

    func testARefusalThatWroteNothingLeavesThePlanEditable() async {
        let h = await harnessWithPlanAndFailedWrite(APIClientError.unexpectedStatus(422))

        XCTAssertFalse(h.viewModel.applyIsUnconfirmed)
        guard case .failure(let message) = h.viewModel.applyState else { return XCTFail("expected failure") }
        XCTAssertTrue(message.contains("Ничего не записано"), message)
        h.viewModel.setMetric(0, enabled: false)
        XCTAssertEqual(h.viewModel.metricEnabled, [false])
    }

    func testAConflictIsTheEndOfTheWriteNotADeadEnd() async {
        let h = await harnessWithPlanAndFailedWrite(APIClientError.unexpectedStatus(409))

        XCTAssertEqual(h.viewModel.applyState, .alreadyApplied, "the key was applied: the day is written")
        XCTAssertFalse(h.viewModel.applyIsUnconfirmed)
        XCTAssertFalse(h.viewModel.canApply, "a retry under the same key would only meet the same 409")
        XCTAssertFalse(h.viewModel.canGenerate, "a new plan under a new key writes the day twice")
        XCTAssertFalse(h.viewModel.canEditPlan)
        XCTAssertFalse(h.viewModel.closeNeedsConfirmation, "nothing is left to lose")
        XCTAssertEqual(h.applied.count, 0, "the sheet stays open to say so")
        let applies = h.api.applies.count
        await h.viewModel.apply()
        XCTAssertEqual(h.api.applies.count, applies)

        h.viewModel.reset()
        XCTAssertEqual(h.viewModel.applyState, .idle)
        XCTAssertEqual(h.viewModel.draftState, .idle)
        XCTAssertEqual(h.viewModel.transcript, "")
    }

    func testA401AfterATimeoutKeepsThePlanFrozen() async {
        let h = await harnessWithPlanAndFailedWrite(APIClientError.timeout)
        h.api.applyResult = .failure(APIClientError.unauthorized)
        await h.viewModel.apply()

        XCTAssertTrue(h.viewModel.applyIsUnconfirmed, "the first attempt may have landed whatever the retry got")
        XCTAssertFalse(h.viewModel.canGenerate)
        h.viewModel.setMetric(0, enabled: false)
        XCTAssertEqual(h.viewModel.metricEnabled, [true])
        guard case .failure(let message) = h.viewModel.applyState else { return XCTFail("expected failure") }
        XCTAssertTrue(message.contains("могла пройти"), message)
        XCTAssertTrue(message.contains("закрыть экран"), "the key lives in Settings, out of reach of this screen")
        XCTAssertTrue(message.contains("проверьте записи за день"), message)
        XCTAssertFalse(message.contains("дубля не будет"), "leaving the screen drops the idempotency key")
        XCTAssertFalse(message.contains("Повторить запись"), message)
        XCTAssertFalse(message.contains("Invalid"), message)
        XCTAssertFalse(message.contains("(401)"), message)

        h.api.applyResult = .failure(APIClientError.invalidBaseURL)
        await h.viewModel.apply()
        XCTAssertTrue(h.viewModel.applyIsUnconfirmed)
    }

    func testA401OnTheFirstAttemptWroteNothingAndSaysItInRussian() async {
        let h = await harnessWithPlanAndFailedWrite(APIClientError.unauthorized)

        XCTAssertFalse(h.viewModel.applyIsUnconfirmed)
        guard case .failure(let message) = h.viewModel.applyState else { return XCTFail("expected failure") }
        XCTAssertTrue(message.contains("Ничего не записано"), message)
        XCTAssertFalse(message.contains("Invalid"), message)
        h.viewModel.setMetric(0, enabled: false)
        XCTAssertEqual(h.viewModel.metricEnabled, [false])
    }

    func testClosingNeedsAConfirmationWhileAWriteIsUnconfirmedOrInFlight() async {
        let h = makeHarness()
        XCTAssertFalse(h.viewModel.closeNeedsConfirmation)
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        XCTAssertFalse(h.viewModel.closeNeedsConfirmation, "a draft alone has written nothing")

        h.api.applyResult = .failure(APIClientError.timeout)
        await h.viewModel.apply()
        XCTAssertTrue(h.viewModel.closeNeedsConfirmation)

        h.api.applyResult = .success(DailySummaryApplyResponseDTO(entryIds: [1], journalEntryId: nil))
        await h.viewModel.apply()
        XCTAssertFalse(h.viewModel.closeNeedsConfirmation)
    }

    func testClosingNeedsAConfirmationWhileTheWriteIsInFlight() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        h.api.applyDelay = .seconds(30)
        let writing = Task { await h.viewModel.apply() }
        await waitUntil { h.viewModel.applyState == .applying }

        XCTAssertTrue(h.viewModel.closeNeedsConfirmation)

        writing.cancel()
        await writing.value
    }

    // MARK: - A screen the system pops without asking

    func testTheRetainerHandsBackTheModelOfAnUnconfirmedWriteUntilThePersonLeaves() async {
        let held = makeHarness()
        held.viewModel.transcript = "день"
        held.api.draftResult = .success(plan(metrics: [metric()]))
        await held.viewModel.generate()
        held.api.applyResult = .failure(APIClientError.timeout)
        await held.viewModel.apply()
        XCTAssertTrue(held.viewModel.closeNeedsConfirmation)
        let spare = makeHarness()
        var queue = [held.viewModel, spare.viewModel]
        let retainer = DailySummaryRetainer { queue.removeFirst() }

        let first = retainer.model()
        XCTAssertTrue(first === held.viewModel)
        retainer.adopt(first)
        retainer.screenLeft(first)
        XCTAssertTrue(retainer.model() === held.viewModel, "the system popped the screen; the write is still unanswered")

        retainer.release()
        XCTAssertTrue(retainer.model() === spare.viewModel, "the person chose to leave: the next visit starts clean")
    }

    func testTheRetainerLetsGoOfAModelThatHasNothingToLoseWhenTheScreenLeaves() {
        let first = makeHarness()
        let second = makeHarness()
        var queue = [first.viewModel, second.viewModel]
        let retainer = DailySummaryRetainer { queue.removeFirst() }

        let shown = retainer.model()
        XCTAssertTrue(shown === first.viewModel)
        retainer.adopt(shown)
        retainer.screenLeft(shown)

        XCTAssertTrue(retainer.model() === second.viewModel)
    }

    func testAModelAskedForButNeverShownIsNotTheOneTheRetainerKeeps() async {
        // The screen's init may run more than once; only the model it adopts counts.
        let shown = makeHarness()
        shown.viewModel.transcript = "день"
        shown.api.draftResult = .success(plan(metrics: [metric()]))
        await shown.viewModel.generate()
        shown.api.applyResult = .failure(APIClientError.timeout)
        await shown.viewModel.apply()
        let askedOnly = makeHarness()
        var queue = [askedOnly.viewModel]
        let retainer = DailySummaryRetainer { queue.removeFirst() }

        let neverShown = retainer.model()
        XCTAssertTrue(neverShown === askedOnly.viewModel)
        retainer.adopt(shown.viewModel)
        retainer.screenLeft(neverShown)

        XCTAssertTrue(retainer.model() === shown.viewModel, "leaving of a model that was not adopted changes nothing")
    }

    // MARK: - Whether a write ever left the model

    func testASheetThatSentNothingHasNotChangedTheDay() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))

        XCTAssertFalse(h.viewModel.mayHaveChangedTheDay)
        await h.viewModel.generate()

        XCTAssertFalse(h.viewModel.mayHaveChangedTheDay, "a draft writes nothing")
        XCTAssertTrue(h.api.applies.isEmpty)
    }

    func testEveryAnswerToAWriteLeavesTheMarkThatTheDayMayHaveChanged() async {
        let answers: [Result<DailySummaryApplyResponseDTO, Error>] = [
            .success(DailySummaryApplyResponseDTO(entryIds: [1], journalEntryId: nil)),
            .failure(APIClientError.unexpectedStatus(409)),
            .failure(APIClientError.timeout),
            .failure(APIClientError.unexpectedStatus(422)),
        ]
        for answer in answers {
            let h = makeHarness()
            h.viewModel.transcript = "день"
            h.api.draftResult = .success(plan(metrics: [metric()]))
            await h.viewModel.generate()
            h.api.applyResult = answer

            await h.viewModel.apply()

            XCTAssertTrue(h.viewModel.mayHaveChangedTheDay, "\(answer)")
        }
    }

    func testTodayIsToldOfASheetOnlyWhenItSentAWrite() async {
        let silent = makeHarness()
        silent.viewModel.transcript = "день"
        silent.api.draftResult = .success(plan(metrics: [metric()]))
        await silent.viewModel.generate()
        let sent = makeHarness()
        sent.viewModel.transcript = "день"
        sent.api.draftResult = .success(plan(metrics: [metric()]))
        await sent.viewModel.generate()
        sent.api.applyResult = .failure(APIClientError.timeout)
        await sent.viewModel.apply()

        XCTAssertFalse(VoiceDayDismissal.shouldReloadToday(after: silent.viewModel), "a draft and a Close change nothing")
        XCTAssertFalse(VoiceDayDismissal.shouldReloadToday(after: nil), "a sheet that never opened owes nothing")
        XCTAssertTrue(VoiceDayDismissal.shouldReloadToday(after: sent.viewModel), "a write that lost its answer may have landed")
    }

    func testStartingAgainDoesNotForgetThatAWriteLeft() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        await h.viewModel.apply()

        h.viewModel.reset()

        XCTAssertTrue(h.viewModel.mayHaveChangedTheDay)
    }

    func testApplyWithoutAServerAddressSaysSoInsteadOfDoingNothing() async {
        let api = MockDailySummaryAPI()
        var configured = true
        let viewModel = DailySummaryViewModel(
            apiProvider: { configured ? api : nil }, speech: FakeSpeech()
        )
        viewModel.transcript = "день"
        api.draftResult = .success(plan(metrics: [metric()]))
        await viewModel.generate()
        configured = false

        await viewModel.apply()

        XCTAssertEqual(viewModel.applyState, .failure(DailySummaryViewModel.notConfiguredMessage))
        XCTAssertFalse(viewModel.applyIsUnconfirmed, "no request left the phone")
        XCTAssertTrue(api.applies.isEmpty)
    }

    func testTwoTapsOnParseWhileTheLastPhraseLandsSendOneDraft() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        h.viewModel.transcript = "день"
        h.speech.emit("съел борщ")

        let first = Task { await h.viewModel.generate() }
        let second = Task { await h.viewModel.generate() }
        await first.value
        await second.value

        XCTAssertEqual(h.api.drafts.count, 1)
        XCTAssertEqual(h.api.drafts.first?.transcript, "день съел борщ")
    }

    func testBlankTextAfterWaitingForDictationBringsTheOldPlanBack() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        let before = h.viewModel.draftState
        await h.viewModel.startDictation()
        h.viewModel.transcript = ""

        let generating = Task { await h.viewModel.generate() }
        await waitUntil { h.viewModel.draftState == .loading }
        XCTAssertEqual(h.viewModel.draftState, .loading, "busy while the last phrase is awaited, not only after it")
        XCTAssertFalse(h.viewModel.canApply, "the old plan cannot be written while the rebuild waits")
        await generating.value

        XCTAssertEqual(h.viewModel.draftState, before)
        XCTAssertEqual(h.api.drafts.count, 1)
    }

    func testCancellingWhileTheLastPhraseLandsSendsNothing() async {
        let h = makeHarness()
        h.speech.holdsFinalPhrase = true
        await h.viewModel.startDictation()
        h.viewModel.transcript = "день"

        let generating = Task { await h.viewModel.generate() }
        await waitUntil { !h.viewModel.isListening }
        h.viewModel.cancelDraft()
        h.speech.landFinalPhrase("и ещё")
        await generating.value

        XCTAssertTrue(h.api.drafts.isEmpty)
        XCTAssertEqual(h.viewModel.draftState, .idle)
    }

    func testMovingTheDayAlsoClearsADraftFailure() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .failure(APIClientError.timeout)
        await h.viewModel.generate()
        XCTAssertNotEqual(h.viewModel.draftState, .idle)

        h.viewModel.showPreviousDay()

        XCTAssertEqual(h.viewModel.draftState, .idle, "an error about another day's draft does not belong here")
    }

    func testWhileTheWriteIsInFlightThePlanAndRebuildAreLocked() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        h.api.applyDelay = .seconds(30)

        let writing = Task { await h.viewModel.apply() }
        await waitUntil { h.viewModel.applyState == .applying }

        XCTAssertEqual(h.viewModel.applyState, .applying)
        XCTAssertFalse(h.viewModel.canGenerate)
        h.viewModel.setMetric(0, enabled: false)
        XCTAssertEqual(h.viewModel.metricEnabled, [true])
        await h.viewModel.generate()
        XCTAssertEqual(h.api.drafts.count, 1)

        writing.cancel()
        await writing.value
    }

    // MARK: - Cancelling the draft

    func testCancellingTheDraftReturnsToIdleAndKeepsTheText() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftDelay = .seconds(30)

        let drafting = Task { await h.viewModel.generate() }
        await waitUntil { h.viewModel.draftState == .loading }
        h.viewModel.cancelDraft()
        await drafting.value

        XCTAssertEqual(h.viewModel.draftState, .idle)
        XCTAssertEqual(h.viewModel.transcript, "день")
    }

    func testCancellingARebuildBringsTheOldPlanBack() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        let first = plan(metrics: [metric()])
        h.api.draftResult = .success(first)
        await h.viewModel.generate()
        h.api.draftDelay = .seconds(30)

        let drafting = Task { await h.viewModel.generate() }
        await waitUntil { h.viewModel.draftState == .loading }
        h.viewModel.cancelDraft()
        await drafting.value

        XCTAssertEqual(h.viewModel.draftState, .done(first))
    }

    func testAURLCancellationIsNotReportedAsNoConnection() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        for error in [
            URLError(.cancelled) as Error,
            APIClientError.transport(code: URLError.cancelled.rawValue),
            CancellationError(),
        ] {
            h.api.draftResult = .failure(error)
            await h.viewModel.generate()
            XCTAssertEqual(h.viewModel.draftState, .idle, "\(error)")
        }
    }

    // MARK: - Dictation edges

    func testACallDuringDictationKeepsWhatWasHeardAndExplains() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        h.speech.emit("съел борщ")
        h.speech.fail(SpeechDictationError.interrupted)
        await h.viewModel.dictationFinished()

        XCTAssertEqual(h.viewModel.transcript, "съел борщ")
        XCTAssertFalse(h.viewModel.isListening)
        XCTAssertTrue(h.viewModel.speechMessage?.contains("прервалась") == true)
    }

    func testLeavingTheForegroundStopsDictationAndSaysWhy() async {
        let h = makeHarness()
        await h.viewModel.startDictation()
        h.speech.emit("съел борщ")

        h.viewModel.stopDictationForBackground()
        await h.viewModel.dictationFinished()

        XCTAssertEqual(h.speech.stopCount, 1)
        XCTAssertEqual(h.viewModel.transcript, "съел борщ")
        XCTAssertTrue(h.viewModel.speechMessage?.contains("в фон") == true)
    }

    func testTwoTapsOnSpeakDuringThePromptStartOneEngine() async {
        let h = makeHarness()
        h.speech.holdsPrompt = true
        let first = Task { await h.viewModel.startDictation() }
        await waitUntil { h.speech.promptIsUp }
        let second = Task { await h.viewModel.startDictation() }
        await Task.yield()
        h.speech.answerPrompt()
        await first.value
        await second.value

        XCTAssertEqual(h.speech.startCount, 1)
    }

    func testClosingTheScreenDuringThePromptNeverStartsTheMicrophone() async {
        let h = makeHarness()
        h.speech.holdsPrompt = true
        let starting = Task { await h.viewModel.startDictation() }
        await waitUntil { h.speech.promptIsUp }

        h.viewModel.stopDictation()
        h.speech.answerPrompt()
        await starting.value

        XCTAssertEqual(h.speech.startCount, 0)
        XCTAssertFalse(h.viewModel.isListening)
    }

    func testTheWriteWaitsForTheMicrophone() async {
        let h = makeHarness()
        h.viewModel.transcript = "день"
        h.api.draftResult = .success(plan(metrics: [metric()]))
        await h.viewModel.generate()
        XCTAssertTrue(h.viewModel.canApply)

        await h.viewModel.startDictation()
        XCTAssertFalse(h.viewModel.canApply)
        h.viewModel.stopDictation()
        await h.viewModel.dictationFinished()
        XCTAssertTrue(h.viewModel.canApply)
    }

    // MARK: - Wording and numbers

    func testAReplacementSaysTheOldTextIsGone() {
        XCTAssertTrue(DayPlanPreview.journalCaption(for: .append, replacing: true).contains("пропадёт"))
        XCTAssertFalse(DayPlanPreview.journalCaption(for: .append, replacing: true).contains("ничего не пропадёт"))
        XCTAssertTrue(DayPlanPreview.journalTitle(for: .append, replacing: true).contains("Заменить"))
        XCTAssertTrue(DayPlanPreview.journalCaption(for: .append, replacing: false).contains("ничего не пропадёт"))
        XCTAssertEqual(DayPlanPreview.journalTitle(for: .create, replacing: false), "Создать запись дня")
    }

    func testANumberFromTheModelNeverCrashesTheFormatter() {
        XCTAssertEqual(DayPlanPreview.format(30), "30")
        XCTAssertFalse(DayPlanPreview.format(1e20).isEmpty)
        XCTAssertFalse(DayPlanPreview.format(Double.greatestFiniteMagnitude).isEmpty)
        XCTAssertFalse(DayPlanPreview.format(-1e300).isEmpty)
    }

    // MARK: - Real recognizer request

    func testRealRequestIsOnDeviceWhenTheRecognizerCanAndStreamsPartials() {
        let onDevice = SystemSpeechRecognizer.makeRequest(supportsOnDevice: true)
        XCTAssertTrue(onDevice.requiresOnDeviceRecognition)
        XCTAssertTrue(onDevice.shouldReportPartialResults)
        let server = SystemSpeechRecognizer.makeRequest(supportsOnDevice: false)
        XCTAssertFalse(server.requiresOnDeviceRecognition)
    }
}
