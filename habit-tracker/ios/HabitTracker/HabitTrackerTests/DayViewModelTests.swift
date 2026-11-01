// [review:need-review] PHASE-01/274
// [review:need-review] PHASE-01/270
// [review:need-review] PHASE-01/211, PHASE-03/226, PHASE-03/231, PHASE-03/248, PHASE-03/256, PHASE-03/263
// summary: PHASE-03/263 — third-text conflict settled by both choices
// summary: PHASE-03/248 — false conflict after A→B→A, a third text in a stale answer, cancelled pull-to-refresh, a re-read answered while another day loads is not shown, the replaced-text card is not restored over the same server text; every hook a test sets must run
// summary: PHASE-03/248 round 2 — a third text survives a quiet re-read as a conflict; tearDown calls super
// summary: Day view model tests — load/failure/not-configured, optimistic mark cycle with rollback, stepping days drops stale answers, category-linked fact record/correct/remove with the done/unmark rule and a stable retry key, notebook dirty tracking and per-day drafts and conflicts with a changed server text, closing fields across days, re-read on foreground and time zone change (a failed pull-to-refresh says so, the others stay quiet), saved notebook text remembered per day against late answers,  two-touch closing with keys and validation
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — a step keeps the loaded day on screen instead of the loader
import Combine
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 — without the outbox a mark holds its line only for the PUT; the re-read after it runs behind, so the tests wait for it
import XCTest
@testable import HabitTracker

@MainActor
final class DayViewModelTests: XCTestCase {
    private var api: MockDayAPI!
    private var viewModel: DayViewModel!

    override func setUp() async throws {
        api = MockDayAPI()
        api.fetchResults = [.success(try DayFixtures.day())]
        viewModel = DayViewModel(api: api)
    }

    /// A hook a test set and the code never reached would leave its assertions vacuous.
    override func tearDown() async throws {
        XCTAssertEqual(api.hooksNeverRun, [], "a hook the test set never ran")
        try await super.tearDown()
    }

    private func factsWrite(total: Double, markState: String?) throws -> PlanFactWriteDTO {
        let day = try DayFixtures.day()
        let base = day.planFacts[0]
        let facts = PlanItemFactsDTO(
            itemId: base.itemId, link: base.link, entries: base.entries, total: total,
            done: true, progress: total >= 300 ? "met" : "partial"
        )
        return PlanFactWriteDTO(entryId: 502, facts: facts, mark: DayFixtures.mark(DayFixtures.pushupsID, markState))
    }

    // MARK: Loading

    func testLoadFillsPlanMarksFactsAndSummary() async {
        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.shownDate, "2026-10-25")
        XCTAssertEqual(viewModel.state(of: DayFixtures.taskID), "done")
        XCTAssertNil(viewModel.state(of: DayFixtures.minimumID))
        XCTAssertEqual(viewModel.facts[DayFixtures.pushupsID]?.total, 100)
        XCTAssertEqual(viewModel.summary?.stage, "open")
        XCTAssertEqual(viewModel.notebook, "Заметка дня")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertEqual(api.fetchedDates.count, 1)
        XCTAssertNil(api.fetchedDates[0], "first load asks for the server's today")
    }

    func testLoadFailureShowsMessage() async {
        api.fetchResults = [.failure(APIClientError.unauthorized)]
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure("Invalid API key (401)"))
    }

    func testNotConfiguredWithoutClient() async {
        viewModel = DayViewModel(apiProvider: { nil })
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .failure(DayViewModel.notConfiguredMessage))
    }

    func testSteppingMovesTheRequestedDay() async throws {
        await viewModel.load()
        api.fetchResults = [.success(try DayFixtures.day())]

        await viewModel.showPreviousDay()
        XCTAssertEqual(api.fetchedDates.count, 2)
        XCTAssertEqual(api.fetchedDates[1], "2026-10-24")

        await viewModel.showToday()
        XCTAssertEqual(api.fetchedDates.count, 3)
        XCTAssertNil(api.fetchedDates[2], "today is requested without a date")
    }

    // MARK: Marks

    func testCycleWalksNoneDoneFailedNoneAndSendsTheTargetState() async throws {
        await viewModel.load()
        api.markResult = .success(DayFixtures.mark(DayFixtures.minimumID, "done"))
        api.fetchResults = [.success(try DayFixtures.day(marks: [
            DayFixtures.mark(DayFixtures.taskID, "done", note: "ок"), DayFixtures.mark(DayFixtures.minimumID, "done"),
        ]))]

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertEqual(api.markCalls.count, 1)
        XCTAssertEqual(api.markCalls[0].id, DayFixtures.minimumID)
        XCTAssertEqual(api.markCalls[0].body.state, "done")
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done")
        XCTAssertEqual(DayFormat.nextMark(after: "done"), "failed")
        XCTAssertNil(DayFormat.nextMark(after: "failed"))
        XCTAssertNil(DayFormat.nextMark(after: "skipped"))
    }

    func testMarkKeepsTheNoteOfTheLine() async {
        await viewModel.load()
        api.markResult = .success(DayFixtures.mark(DayFixtures.taskID, "failed", note: "ок"))

        await viewModel.cycleMark(DayFixtures.taskID)

        XCTAssertEqual(api.markCalls[0].body.state, "failed")
        XCTAssertEqual(api.markCalls[0].body.note, "ок")
    }

    func testRefusedMarkRollsBackAndTellsWhy() async {
        await viewModel.load()
        api.markResult = .failure(APIClientError.transport(code: -1009))

        await viewModel.cycleMark(DayFixtures.taskID)

        XCTAssertEqual(viewModel.state(of: DayFixtures.taskID), "done", "rolled back to the previous mark")
        XCTAssertEqual(viewModel.actionError, "Network error (-1009)")
    }

    func testMarkRereadsTheDayForCounts() async throws {
        await viewModel.load()
        api.markResult = .success(DayFixtures.mark(DayFixtures.taskID, "failed"))
        var recounted = try DayFixtures.day()
        recounted = DayDetailDTO(
            day: recounted.day, rule: recounted.rule, plan: recounted.plan, hasPlan: true,
            marks: [DayFixtures.mark(DayFixtures.taskID, "failed")], planFacts: recounted.planFacts,
            taskCounts: TaskCountsDTO(planned: 1, done: 0, failed: 1, skipped: 0, pending: 0),
            notebook: recounted.notebook, summary: recounted.summary
        )
        api.fetchResults = [.success(recounted)]

        await viewModel.cycleMark(DayFixtures.taskID)
        await waitUntil { api.fetchedDates.count == 2 }

        XCTAssertEqual(viewModel.counts?.failed, 1)
        XCTAssertEqual(api.fetchedDates.count, 2)
    }

    // MARK: Facts

    func testReachingTheTargetRecordsTheFactWithDoneMark() async throws {
        await viewModel.load()
        api.factResult = .success(try factsWrite(total: 300, markState: "done"))
        api.fetchResults = [.success(try doneLine())]

        let saved = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("200"))

        XCTAssertTrue(saved)
        let call = api.recordCalls[0]
        XCTAssertEqual(call.body.mark, "done")
        XCTAssertEqual(call.body.values[0].fieldId, 70)
        XCTAssertEqual(call.body.values[0].value, .number(200))
        XCTAssertEqual(call.body.values[0].unit, "раз")
        XCTAssertEqual(viewModel.facts[DayFixtures.pushupsID]?.total, 300)
        XCTAssertEqual(viewModel.state(of: DayFixtures.pushupsID), "done")
    }

    func testPartialFactDoesNotMarkTheLineDone() async throws {
        await viewModel.load()
        api.factResult = .success(try factsWrite(total: 150, markState: nil))

        _ = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("50"))

        XCTAssertNil(api.recordCalls[0].body.mark)
    }

    func testUnreadableValueNeverReachesTheServer() async {
        await viewModel.load()

        let saved = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("много"))

        XCTAssertFalse(saved)
        XCTAssertTrue(api.recordCalls.isEmpty)
        XCTAssertEqual(viewModel.actionError, DayViewModel.unreadableValueMessage)
    }

    func testRetryAfterALostAnswerReusesTheKeyAndANewValueGetsANewOne() async {
        await viewModel.load()
        api.factResult = .failure(APIClientError.timeout)

        _ = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("50"))
        _ = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("50"))
        _ = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("60"))

        XCTAssertEqual(api.recordCalls.count, 3)
        XCTAssertEqual(api.recordCalls[0].key, api.recordCalls[1].key)
        XCTAssertNotEqual(api.recordCalls[1].key, api.recordCalls[2].key)
    }

    func testBoxFactSendsAFlagWithoutUnit() async throws {
        await viewModel.load()
        api.factResult = .success(try factsWrite(total: 0, markState: "done"))

        _ = await viewModel.saveFact(DayFixtures.readingID, input: .flag(true))

        let call = api.recordCalls[0]
        XCTAssertEqual(call.body.values[0].value, .flag(true))
        XCTAssertNil(call.body.values[0].unit)
        XCTAssertEqual(call.body.mark, "done")
    }

    func testCorrectingBelowTheTargetOfADoneLineUnmarksIt() async throws {
        await viewModel.load()
        // The line is done at 300 (two entries: 100 + 200); correcting 200 -> 150 takes it back.
        let withTwo = try doneLine()
        api.fetchResults = [.success(withTwo)]
        await viewModel.load()
        api.factResult = .success(try factsWrite(total: 250, markState: nil))

        _ = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("150"), correcting: 502)

        XCTAssertEqual(api.correctCalls.count, 1)
        XCTAssertEqual(api.correctCalls[0].entry, 502)
        XCTAssertEqual(api.correctCalls[0].body.mark, "unmark")
    }

    func testRemovingTheLastEntryOfADoneLineAsksForUnmark() async throws {
        api.fetchResults = [.success(try doneLine())]
        await viewModel.load()
        api.factResult = .success(try factsWrite(total: 100, markState: nil))

        await viewModel.removeFact(DayFixtures.pushupsID, entryID: 502)

        XCTAssertEqual(api.removeCalls.count, 1)
        XCTAssertTrue(api.removeCalls[0].unmark)
    }

    func testRemovingAnEntryOfAShortLineLeavesTheMarkAlone() async throws {
        await viewModel.load()
        api.factResult = .success(try factsWrite(total: 0, markState: nil))

        await viewModel.removeFact(DayFixtures.pushupsID, entryID: 501)

        XCTAssertFalse(api.removeCalls[0].unmark)
    }

    /// The fixture's pushups line with a second entry of 200: total 300 = target.
    private func doneLine() throws -> DayDetailDTO {
        let day = try DayFixtures.day()
        let base = day.planFacts[0]
        let second = PlanFactEntryDTO(
            entryId: 502, entryDate: "2026-10-25", values: [PlanFactValueDTO(fieldId: 70, value: "200")]
        )
        let facts = PlanItemFactsDTO(
            itemId: base.itemId, link: base.link, entries: base.entries + [second], total: 300,
            done: true, progress: "met"
        )
        return DayDetailDTO(
            day: day.day, rule: day.rule, plan: day.plan, hasPlan: true,
            marks: day.marks + [DayFixtures.mark(DayFixtures.pushupsID, "done")],
            planFacts: [facts, day.planFacts[1]], taskCounts: day.taskCounts,
            notebook: day.notebook, summary: day.summary
        )
    }

    // MARK: Notebook

    func testNotebookSavesAndClearsTheDirtyFlag() async {
        await viewModel.load()
        viewModel.notebook = "Новое"
        XCTAssertTrue(viewModel.isNotebookDirty)

        await viewModel.saveNotebook()

        XCTAssertEqual(api.notebookCalls, ["Новое"])
        XCTAssertFalse(viewModel.isNotebookDirty)
    }

    func testFailedNotebookSaveKeepsTheTextAndSaysSo() async {
        await viewModel.load()
        api.notebookError = APIClientError.timeout
        viewModel.notebook = "Не потерять"

        await viewModel.saveNotebook()

        XCTAssertTrue(viewModel.isNotebookDirty)
        XCTAssertEqual(viewModel.notebook, "Не потерять")
        XCTAssertEqual(viewModel.actionError, "Блокнот за \(DayFormat.title(of: "2026-10-25")) не сохранился: Connection timed out")
    }

    func testRereadAfterAMarkKeepsUnsavedNotebookText() async {
        await viewModel.load()
        viewModel.notebook = "Ещё не сохранил"
        api.markResult = .success(DayFixtures.mark(DayFixtures.minimumID, "done"))

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertEqual(viewModel.notebook, "Ещё не сохранил")
    }

    func testSteppingAwayKeepsUnsavedNotebookTextAsADraftOfThatDay() async throws {
        await viewModel.load()
        viewModel.notebook = "Не сохранил вчера"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24", notebook: .some("Старая запись")))]

        await viewModel.showPreviousDay()

        XCTAssertEqual(viewModel.shownDate, "2026-10-24")
        XCTAssertEqual(viewModel.notebook, "Старая запись", "the other day shows its own text")
        XCTAssertFalse(viewModel.isNotebookDirty)

        api.fetchResults = [.success(try DayFixtures.day())]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.shownDate, "2026-10-25")
        XCTAssertEqual(viewModel.notebook, "Не сохранил вчера", "the draft came back with its day")
        XCTAssertTrue(viewModel.isNotebookDirty, "still unsaved, the Save button stays live")
    }

    func testSavedNotebookLeavesNoDraftBehind() async throws {
        await viewModel.load()
        viewModel.notebook = "Сохранил"
        await viewModel.saveNotebook()
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24", notebook: .some("Другое")))]
        await viewModel.showPreviousDay()
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Сохранил")))]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.notebook, "Сохранил")
        XCTAssertFalse(viewModel.isNotebookDirty)
    }

    func testADraftBackToTheServerTextIsNotKept() async throws {
        await viewModel.load()
        viewModel.notebook = "Правка"
        viewModel.notebook = "Заметка дня"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Заметка с сервера")))]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.notebook, "Заметка с сервера", "an unchanged text is not a draft")
    }


    func testRereadOfTheSameDayTakesTheServersNotebookWhenNothingIsTypedLocally() async throws {
        await viewModel.load()
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Дописали в вебе")))]

        await viewModel.load()

        XCTAssertEqual(viewModel.notebook, "Дописали в вебе")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testRereadWithUnsavedTextKeepsItAndRaisesAConflictWhenTheServerMovedOn() async throws {
        await viewModel.load()
        viewModel.notebook = "Моя правка"
        api.markResult = .success(DayFixtures.mark(DayFixtures.minimumID, "done"))
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Дописали в вебе")))]

        await viewModel.cycleMark(DayFixtures.minimumID)
        await waitUntil { viewModel.notebookConflict != nil }

        XCTAssertEqual(viewModel.notebook, "Моя правка", "typed text is never replaced silently")
        XCTAssertEqual(viewModel.notebookConflict, "Дописали в вебе")
    }

    func testRereadWithUnsavedTextAndAnUnchangedServerTextRaisesNoConflict() async {
        await viewModel.load()
        viewModel.notebook = "Моя правка"

        await viewModel.load()

        XCTAssertEqual(viewModel.notebook, "Моя правка")
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testADraftTypedOnAnOutdatedServerTextComesBackWithAConflict() async throws {
        await viewModel.load()
        viewModel.notebook = "Правка к старому тексту"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Новый текст из веба")))]

        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.notebook, "Правка к старому тексту")
        XCTAssertEqual(viewModel.notebookConflict, "Новый текст из веба")
        XCTAssertTrue(viewModel.isNotebookDirty)
    }

    func testSavingIsRefusedWhileTheConflictIsOpenAndKeepingMineSettlesIt() async throws {
        await viewModel.load()
        viewModel.notebook = "Моя правка"
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Из веба")))]
        await viewModel.load()

        await viewModel.saveNotebook()
        XCTAssertTrue(api.notebookCalls.isEmpty, "a save over an unseen server text is a silent overwrite")

        viewModel.keepMyNotebook()
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertEqual(viewModel.notebook, "Моя правка")
        await viewModel.saveNotebook()
        XCTAssertEqual(api.notebookCalls, ["Моя правка"])
        XCTAssertFalse(viewModel.isNotebookDirty)
    }

    func testTakingTheServersNotebookDropsTheLocalText() async throws {
        await viewModel.load()
        viewModel.notebook = "Моя правка"
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Из веба")))]
        await viewModel.load()

        viewModel.useServerNotebook()

        XCTAssertEqual(viewModel.notebook, "Из веба")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testSteppingAwayDuringASaveLeavesTheOtherDayClean() async throws {
        await viewModel.load()
        viewModel.notebook = "Пишу про 25-е"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24", notebook: .some("Про 24-е")))]
        api.duringNotebookSave = { [viewModel] in await viewModel!.showPreviousDay() }

        await viewModel.saveNotebook()

        XCTAssertEqual(viewModel.shownDate, "2026-10-24")
        XCTAssertEqual(viewModel.notebook, "Про 24-е")
        XCTAssertFalse(viewModel.isNotebookDirty, "the answer of day A must not mark day B")
        XCTAssertFalse(viewModel.isSavingNotebook)

        api.duringNotebookSave = nil
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Дописали в вебе")))]
        await viewModel.showNextDay()
        XCTAssertEqual(viewModel.notebook, "Дописали в вебе", "the saved text left no draft to stand over the server's")
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertFalse(viewModel.isNotebookDirty)
    }

    func testALateReadThatPredatesTheSaveDoesNotRollTheNotebookBack() async throws {
        await viewModel.load()
        viewModel.notebook = "Новый текст"
        // The answer differs from the loaded day in a mark, so applying the rest of it is provable.
        api.fetchResults = [.success(try DayFixtures.day(marks: [DayFixtures.mark(DayFixtures.taskID, "failed")]))]
        XCTAssertEqual(viewModel.state(of: DayFixtures.taskID), "done")
        // The read left before the save, the save was answered first, then the old answer arrives.
        api.duringFetch = { [viewModel] in await viewModel!.saveNotebook() }

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.notebook, "Новый текст")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertEqual(viewModel.state(of: DayFixtures.taskID), "failed", "the rest of the answer is still applied")
    }

    func testALateReadDoesNotTurnTextTypedAfterTheSaveIntoAFalseConflict() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.duringFetch = { [viewModel] in
            await viewModel!.saveNotebook()
            viewModel!.notebook = "T2"
        }

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.notebook, "T2")
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertTrue(viewModel.isNotebookDirty)
    }

    func testAReadAnsweredWhileTheSaveIsInFlightKeepsTheTextTypedMeanwhile() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.duringNotebookSave = { [viewModel] in
            viewModel!.notebook = "T и ещё"
            await viewModel!.rereadInPlace()
        }

        await viewModel.saveNotebook()

        XCTAssertEqual(viewModel.notebook, "T и ещё")
        XCTAssertNil(viewModel.notebookConflict, "the old answer is not a change made elsewhere")
        XCTAssertTrue(viewModel.isNotebookDirty)
        XCTAssertEqual(api.notebookCalls, ["T"])

        api.duringNotebookSave = nil
        await viewModel.saveNotebook()
        XCTAssertEqual(api.notebookCalls, ["T", "T и ещё"])
    }

    func testASaveThatReplacesAServerTextStillOnScreenSaysSo() async throws {
        await viewModel.load()
        viewModel.notebook = "Мой"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        // Stepping away and back during the save brings the server's text beside the typed one.
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.fetchResults = [.success(try DayFixtures.day(notebook: .some("Чужой")))]
            await viewModel!.showNextDay()
        }

        await viewModel.saveNotebook()

        XCTAssertEqual(viewModel.notebookConflict, "Чужой", "the overwritten text stays in view")
        XCTAssertTrue(viewModel.notebookConflictOverwritten)
        XCTAssertFalse(viewModel.isNotebookSaveBlocked)
        viewModel.dismissNotebookConflict()
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertFalse(viewModel.notebookConflictOverwritten)
    }

    func testAStaleAnswerForTheSavedDayKeepsTheSavedTextAfterSteppingAwayAndBack() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.fetchResults = [
            .success(try DayFixtures.day(date: "2026-10-24", notebook: .some("Про 24-е"))),
            .success(try DayFixtures.day()),
        ]
        var stepBack: Task<Void, Never>?
        var readIsInFlight = false
        var answerGate: CheckedContinuation<Void, Never>?
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            // The return to day A leaves during the save and is answered after it, with the text from before.
            api!.duringFetch = {
                readIsInFlight = true
                await withCheckedContinuation { answerGate = $0 }
            }
            stepBack = Task { await viewModel!.showNextDay() }
            while !readIsInFlight { await Task.yield() }
        }

        await viewModel.saveNotebook()
        XCTAssertEqual(viewModel.shownDate, "2026-10-24", "the save ended while the other day was on screen")
        answerGate?.resume()
        await stepBack?.value

        XCTAssertEqual(viewModel.shownDate, "2026-10-25")
        XCTAssertEqual(viewModel.notebook, "T", "the answer predates the save: the saved text stands")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testASaveThatEndedOnAnotherDayRebasesTheDraftSoComingBackRaisesNoFalseConflict() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        // T2 is typed while the save of T runs, then the person steps away: the save ends on the other day.
        api.duringNotebookSave = { [viewModel] in
            viewModel!.notebook = "T2"
            await viewModel!.showPreviousDay()
        }
        await viewModel.saveNotebook()
        api.duringNotebookSave = nil
        XCTAssertEqual(viewModel.shownDate, "2026-10-24")

        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("T")))]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.notebook, "T2")
        XCTAssertNil(viewModel.notebookConflict, "the server holds the person's own T, typed over by T2")
        XCTAssertTrue(viewModel.isNotebookDirty)
        XCTAssertFalse(viewModel.isNotebookSaveBlocked)
    }

    func testAStaleAnswerWithAThirdTextKeepsTheSavedTextAndRaisesAConflictThatBlocksSaving() async throws {
        try await raiseAThirdTextConflict()
        viewModel.useServerNotebook()
        XCTAssertEqual(viewModel.notebook, "Веб-правка")
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testKeepingMineSettlesAThirdTextConflict() async throws {
        try await raiseAThirdTextConflict()
        viewModel.keepMyNotebook()
        XCTAssertEqual(viewModel.notebook, "T", "the person's text stays")
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertFalse(viewModel.isNotebookSaveBlocked)
        XCTAssertTrue(viewModel.isNotebookDirty, "mine differs from the server text it now stands over, and can be saved")
    }

    /// Saves T on day A, steps away and back while the saved text is being written, and lets a stale answer
    /// with a third text land: the saved text stays, the third one waits beside it, saving is closed.
    private func raiseAThirdTextConflict() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.fetchResults = [
            .success(try DayFixtures.day(date: "2026-10-24", notebook: .some("Про 24-е"))),
            .success(try DayFixtures.day(notebook: .some("Веб-правка"))),
        ]
        var stepBack: Task<Void, Never>?
        var readIsInFlight = false
        var answerGate: CheckedContinuation<Void, Never>?
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.duringFetch = {
                readIsInFlight = true
                await withCheckedContinuation { answerGate = $0 }
            }
            stepBack = Task { await viewModel!.showNextDay() }
            while !readIsInFlight { await Task.yield() }
        }

        await viewModel.saveNotebook()
        answerGate?.resume()
        await stepBack?.value

        XCTAssertEqual(viewModel.shownDate, "2026-10-25")
        XCTAssertEqual(viewModel.notebook, "T", "the saved text stays on screen")
        XCTAssertEqual(viewModel.notebookConflict, "Веб-правка", "a text that is neither the base nor the saved one was written elsewhere")
        XCTAssertTrue(viewModel.isNotebookSaveBlocked)
        let callsBefore = api.notebookCalls.count
        await viewModel.saveNotebook()
        XCTAssertEqual(api.notebookCalls.count, callsBefore, "saving waits until the person picks a side")

        // The next quiet re-read hands over the same third text: the choice is still the person's.
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Веб-правка")))]
        await viewModel.rereadInPlace()
        XCTAssertEqual(viewModel.notebook, "T")
        XCTAssertEqual(viewModel.notebookConflict, "Веб-правка", "a re-read does not choose for the person")
        XCTAssertTrue(viewModel.isNotebookSaveBlocked)
    }

    func testAnAnswerSentAfterTheSaveBringsTheServersTextAgain() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        api.duringNotebookSave = { [viewModel] in await viewModel!.showPreviousDay() }
        await viewModel.saveNotebook()
        api.duringNotebookSave = nil

        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Дописали в вебе")))]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.notebook, "Дописали в вебе", "the remembered text only covers answers sent before the save ended")
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testAReadAnsweredDuringTheSaveWithTheWrittenTextRaisesNoConflictOverTextTypedMeanwhile() async throws {
        await viewModel.load()
        viewModel.notebook = "T"
        api.duringNotebookSave = { [viewModel, api] in
            viewModel!.notebook = "T2"
            api!.fetchResults = [.success(try DayFixtures.day(notebook: .some("T")))]
            await viewModel!.rereadInPlace()
            // The end of the save would clear a conflict over "T" by itself, so look while it is in flight.
            XCTAssertNil(viewModel!.notebookConflict, "the server holds the text being saved, not a change made elsewhere")
            XCTAssertEqual(viewModel!.notebook, "T2")
        }

        await viewModel.saveNotebook()

        XCTAssertEqual(viewModel.notebook, "T2")
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertTrue(viewModel.isNotebookDirty)
    }

    func testTheNoteThatASaveReplacedTheServerTextOutlivesARereadUntilDismissed() async throws {
        await viewModel.load()
        viewModel.notebook = "Мой"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.fetchResults = [.success(try DayFixtures.day(notebook: .some("Чужой")))]
            await viewModel!.showNextDay()
        }
        await viewModel.saveNotebook()
        api.duringNotebookSave = nil

        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Мой")))]
        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.notebook, "Мой")
        XCTAssertEqual(viewModel.notebookConflict, "Чужой")
        XCTAssertTrue(viewModel.notebookConflictOverwritten)
        viewModel.dismissNotebookConflict()
        XCTAssertNil(viewModel.notebookConflict)
        await viewModel.rereadInPlace()
        XCTAssertNil(viewModel.notebookConflict)
    }

    func testTheNoteThatASaveReplacedTheServerTextIsNotRestoredWhenTheServerHoldsThatTextAgain() async throws {
        await viewModel.load()
        viewModel.notebook = "Мой"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.fetchResults = [.success(try DayFixtures.day(notebook: .some("Чужой")))]
            await viewModel!.showNextDay()
        }
        await viewModel.saveNotebook()
        api.duringNotebookSave = nil
        XCTAssertEqual(viewModel.notebookConflict, "Чужой")

        // Somebody put that very text back: there is nothing left that the save replaced.
        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Чужой")))]
        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.notebook, "Чужой")
        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertFalse(viewModel.notebookConflictOverwritten)
    }

    func testTheNoteThatASaveReplacedTheServerTextGoesWithTheDay() async throws {
        await viewModel.load()
        viewModel.notebook = "Мой"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        api.duringNotebookSave = { [viewModel, api] in
            await viewModel!.showPreviousDay()
            api!.fetchResults = [.success(try DayFixtures.day(notebook: .some("Чужой")))]
            await viewModel!.showNextDay()
        }
        await viewModel.saveNotebook()
        api.duringNotebookSave = nil

        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()

        XCTAssertNil(viewModel.notebookConflict)
        XCTAssertFalse(viewModel.notebookConflictOverwritten)
    }

    // MARK: Closing

    func testReviewSendsMinutesAndBodyThenFinalClosesUnderItsOwnKey() async throws {
        await viewModel.load()
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary()))]
        viewModel.closingMinutes = "420"
        viewModel.closingBody = "  Релиз вышел  "
        api.closingResult = .success(DayFixtures.summary(stage: "reviewed", verdict: nil, reason: "not_closed"))

        await viewModel.review()
        api.closingResult = .success(DayFixtures.summary())
        await viewModel.closeDay()

        XCTAssertEqual(api.closingCalls.map(\.touch), ["review", "final"])
        XCTAssertEqual(api.closingCalls[0].body, DayClosingRequestDTO(workMinutes: 420, bodyMd: "Релиз вышел"))
        XCTAssertNotEqual(api.closingCalls[0].key, api.closingCalls[1].key)
        XCTAssertEqual(viewModel.summary?.verdict, "won")
    }

    func testEmptyFieldsAreNotSentSoTheServerKeepsWhatIsRecorded() async {
        await viewModel.load()
        api.closingResult = .success(DayFixtures.summary())

        await viewModel.closeDay()

        XCTAssertEqual(api.closingCalls[0].body, DayClosingRequestDTO(workMinutes: nil, bodyMd: nil))
    }

    func testFailedCloseRetriesUnderTheSameKey() async {
        await viewModel.load()
        api.closingResult = .failure(APIClientError.timeout)

        await viewModel.closeDay()
        await viewModel.closeDay()

        XCTAssertEqual(api.closingCalls.count, 2)
        XCTAssertEqual(api.closingCalls[0].key, api.closingCalls[1].key)
        XCTAssertEqual(viewModel.actionError, "Connection timed out")
    }

    func testMinutesThatAreNotANumberAreRefusedBeforeTheRequest() async {
        await viewModel.load()
        viewModel.closingMinutes = "семь часов"

        await viewModel.closeDay()

        XCTAssertTrue(api.closingCalls.isEmpty)
        XCTAssertEqual(viewModel.actionError, DayViewModel.unreadableMinutesMessage)
    }

    // MARK: Closing fields across days

    func testClosingFieldsSurviveSteppingToANeighbourAndBack() async throws {
        await viewModel.load()
        viewModel.closingMinutes = "95"
        viewModel.closingBody = "Не дописал"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()

        XCTAssertEqual(viewModel.closingMinutes, "", "the other day shows its own summary")
        XCTAssertEqual(viewModel.closingBody, "")

        api.fetchResults = [.success(try DayFixtures.day())]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.closingMinutes, "95")
        XCTAssertEqual(viewModel.closingBody, "Не дописал")
    }

    func testRereadTakesTheServersClosingFieldsWhenNothingIsTyped() async throws {
        await viewModel.load()
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary()))]

        await viewModel.load()

        XCTAssertEqual(viewModel.closingMinutes, "420")
        XCTAssertEqual(viewModel.closingBody, "итог")
    }

    func testRereadKeepsClosingFieldsTheyAreTypingIn() async throws {
        await viewModel.load()
        viewModel.closingBody = "Пишу"
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary()))]

        await viewModel.load()

        XCTAssertEqual(viewModel.closingBody, "Пишу")
        XCTAssertEqual(viewModel.closingMinutes, "420", "an untouched field follows the server")
    }

    func testServerMovingUnderTypedClosingFieldsRaisesAConflictAndBlocksSending() async throws {
        await viewModel.load()
        viewModel.closingBody = "Мой итог"
        viewModel.closingMinutes = "95"
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary(bodyMd: "Из веба", workMinutes: 95)))]
        await viewModel.load()

        XCTAssertEqual(viewModel.closingBody, "Мой итог")
        XCTAssertEqual(viewModel.closingConflict, DayViewModel.ClosingConflict(body: "Из веба", minutes: nil),
                       "minutes already equal the server's: no conflict there")
        api.closingResult = .success(DayFixtures.summary())
        await viewModel.closeDay()
        XCTAssertTrue(api.closingCalls.isEmpty, "sending over an unseen server text is a silent overwrite")

        viewModel.keepMyClosing()
        XCTAssertNil(viewModel.closingConflict)
        await viewModel.closeDay()
        XCTAssertEqual(api.closingCalls.count, 1)
        XCTAssertEqual(api.closingCalls[0].body.bodyMd, "Мой итог")
    }

    func testTakingTheServersClosingFieldsDropsTheTypedOnes() async throws {
        await viewModel.load()
        viewModel.closingBody = "Мой итог"
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary(bodyMd: "Из веба")))]
        await viewModel.load()

        viewModel.useServerClosing()

        XCTAssertEqual(viewModel.closingBody, "Из веба")
        XCTAssertNil(viewModel.closingConflict)
    }

    func testAClosingDraftTypedOnAnOutdatedServerValueComesBackWithAConflict() async throws {
        await viewModel.load()
        viewModel.closingBody = "Правка"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary(bodyMd: "Новый из веба")))]

        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.closingBody, "Правка")
        XCTAssertEqual(viewModel.closingConflict?.body, "Новый из веба")
    }

    func testAnAnswerToTheClosingSettlesAConflictRaisedWhileItWasInFlight() async throws {
        await viewModel.load()
        viewModel.closingBody = "Итог дня"
        api.closingResult = .success(DayFixtures.summary(bodyMd: "Итог дня", workMinutes: nil))
        api.duringClosing = { [viewModel, api] in
            api!.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary(bodyMd: "Из веба", workMinutes: nil)))]
            await viewModel!.rereadInPlace()
            XCTAssertNotNil(viewModel!.closingConflict, "the read raised a conflict under the text being sent")
            api!.fetchResults = [.failure(APIClientError.timeout)]
        }

        await viewModel.closeDay()

        XCTAssertNil(viewModel.closingConflict, "what was sent is what the server holds now")
        XCTAssertEqual(viewModel.closingBody, "Итог дня")
    }

    func testSentClosingFieldsAreTheNewBaseEvenWhenTheRereadAfterThemFails() async throws {
        await viewModel.load()
        viewModel.closingBody = "  Релиз вышел  "
        viewModel.closingMinutes = "420"
        api.closingResult = .success(DayFixtures.summary(stage: "reviewed", verdict: nil, bodyMd: "Релиз вышел", workMinutes: 420))
        api.fetchResults = [.failure(APIClientError.timeout)]

        await viewModel.review()

        XCTAssertEqual(viewModel.closingBody, "Релиз вышел", "snaps to the stored spelling")
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()
        api.fetchResults = [.success(try DayFixtures.day(summary: DayFixtures.summary(bodyMd: "Релиз вышел, дописали", workMinutes: 420)))]
        await viewModel.showNextDay()

        XCTAssertEqual(viewModel.closingBody, "Релиз вышел, дописали", "sent text is not a draft over a later server value")
        XCTAssertNil(viewModel.closingConflict)
    }

    // MARK: Foreground, midnight and time zone

    func testReturningFromTheBackgroundOnTheNextDayShowsTheNewToday() async throws {
        await viewModel.load()
        viewModel.notebook = "Не сохранил вчера"
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-26", notebook: .some("")))]

        await viewModel.rereadInPlace()

        XCTAssertEqual(api.fetchedDates.count, 2)
        XCTAssertNil(api.fetchedDates[1], "a screen following the server's today asks for it again")
        XCTAssertEqual(viewModel.shownDate, "2026-10-26")
        XCTAssertEqual(viewModel.state, .loaded, "no loader flash")
        XCTAssertEqual(viewModel.notebook, "")

        api.fetchResults = [.success(try DayFixtures.day(notebook: .some("Заметка дня")))]
        await viewModel.showPreviousDay()
        XCTAssertEqual(viewModel.notebook, "Не сохранил вчера", "yesterday's unsaved text is kept as its draft")
    }

    func testReturningFromTheBackgroundOnASteppedDayRereadsThatDay() async throws {
        await viewModel.load()
        api.fetchResults = [.success(try DayFixtures.day(date: "2026-10-24"))]
        await viewModel.showPreviousDay()

        await viewModel.rereadInPlace()

        XCTAssertEqual(api.fetchedDates.last, "2026-10-24")
    }

    func testRereadInPlaceSkipsAScreenThatIsNotLoaded() async {
        api.fetchResults = [.failure(APIClientError.timeout)]
        await viewModel.load()
        let before = api.fetchedDates.count

        await viewModel.rereadInPlace()

        XCTAssertEqual(api.fetchedDates.count, before)
    }

    func testAFailedSilentRereadLeavesTheScreenAsItWas() async {
        await viewModel.load()
        api.fetchResults = [.failure(APIClientError.timeout)]

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.shownDate, "2026-10-25")
        XCTAssertNil(viewModel.actionError, "background, midnight and zone re-reads stay quiet")
    }

    func testAFailedPullToRefreshSaysSoAndLeavesTheScreenAsItWas() async {
        await viewModel.load()
        api.fetchResults = [.failure(APIClientError.timeout)]

        await viewModel.rereadInPlace(reportingFailure: true)

        XCTAssertEqual(viewModel.actionError, "\(DayViewModel.refreshFailedMessage): Connection timed out")
        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.shownDate, "2026-10-25")
    }

    func testAPullToRefreshThatWorksSaysNothing() async throws {
        await viewModel.load()
        api.fetchResults = [.success(try DayFixtures.day(marks: [DayFixtures.mark(DayFixtures.taskID, "failed")]))]

        await viewModel.rereadInPlace(reportingFailure: true)

        XCTAssertNil(viewModel.actionError)
        XCTAssertEqual(viewModel.state(of: DayFixtures.taskID), "failed")
    }

    func testACancelledPullToRefreshSaysNothing() async {
        await viewModel.load()
        api.fetchResults = [.failure(CancellationError())]

        // The person let go of the screen: the task is cancelled before the read answers.
        let refresh = Task { await viewModel.rereadInPlace(reportingFailure: true) }
        refresh.cancel()
        await refresh.value

        XCTAssertEqual(api.fetchedDates.count, 2, "the read was attempted")
        XCTAssertNil(viewModel.actionError, "a cancelled refresh is not a failure")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testARereadAnsweredWhileAnotherDayLoadsIsNotShown() async throws {
        await viewModel.load()
        api.fetchResults = [
            .success(try DayFixtures.day(marks: [DayFixtures.mark(DayFixtures.taskID, "failed")])),
            .success(try DayFixtures.day(date: "2026-10-24")),
        ]
        var rereadIsInFlight = false
        var rereadGate: CheckedContinuation<Void, Never>?
        api.duringFetch = {
            rereadIsInFlight = true
            await withCheckedContinuation { rereadGate = $0 }
        }
        let reread = Task { [viewModel] in await viewModel!.rereadInPlace() }
        while !rereadIsInFlight { await Task.yield() }
        var stepIsInFlight = false
        var stepGate: CheckedContinuation<Void, Never>?
        api.duringFetch = {
            stepIsInFlight = true
            await withCheckedContinuation { stepGate = $0 }
        }
        let step = Task { [viewModel] in await viewModel!.showPreviousDay() }
        while !stepIsInFlight { await Task.yield() }

        // The re-read of day A left before the step and is numbered ahead of what is shown, but the
        // screen asked for another day since: its answer is for what was asked earlier.
        rereadGate?.resume()
        await reread.value

        // The loaded day stays on screen through the step (#310): no loader, and the old day's answer changed nothing.
        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.shownDate, DayFixtures.date, "the step to the other day is still the screen's question")
        XCTAssertEqual(viewModel.state(of: DayFixtures.taskID), "done", "the old day's answer changed nothing")

        stepGate?.resume()
        await step.value
        XCTAssertEqual(viewModel.shownDate, "2026-10-24")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testARereadInTheSameZoneDoesNotRepublishIt() async {
        let zone = TimeZone(identifier: "Europe/Berlin")!
        viewModel = DayViewModel(apiProvider: { [api] in api }, timeZoneProvider: { zone })
        await viewModel.load()
        var published = 0
        let subscription = viewModel.$timeZone.sink { _ in published += 1 }

        await viewModel.rereadInPlace()

        XCTAssertEqual(published, 1, "only the initial value: the zone did not change")
        subscription.cancel()
    }

    func testRereadInPlaceFollowsTheDevicesZone() async {
        var zone = TimeZone(identifier: "Europe/Berlin")!
        viewModel = DayViewModel(apiProvider: { [api] in api }, timeZoneProvider: { zone })
        await viewModel.load()

        zone = TimeZone(identifier: "Asia/Tokyo")!
        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.timeZone.identifier, "Asia/Tokyo")
    }

    func testTimeZoneChangeRefreshesTheZoneAndRereads() async {
        var zone = TimeZone(identifier: "Europe/Berlin")!
        viewModel = DayViewModel(apiProvider: { [api] in api }, timeZoneProvider: { zone })
        await viewModel.load()
        XCTAssertEqual(viewModel.timeZone.identifier, "Europe/Berlin")

        zone = TimeZone(identifier: "America/New_York")!
        await viewModel.systemTimeZoneDidChange()

        XCTAssertEqual(viewModel.timeZone.identifier, "America/New_York")
        XCTAssertEqual(api.fetchedDates.count, 2)
    }

    func testShowDateOpensThatDayAndStaysOnItAfterAReload() async throws {
        await viewModel.show(date: "2026-10-20")
        XCTAssertEqual(api.fetchedDates, ["2026-10-20"])
        await viewModel.rereadInPlace()
        XCTAssertEqual(api.fetchedDates, ["2026-10-20", "2026-10-20"], "the reload reads the chosen day, not today")
        await viewModel.load()
        XCTAssertEqual(api.fetchedDates.last, "2026-10-20", "a retry stays on the chosen day too")
    }

    func testABadOrLooseDateIsIgnored() async {
        await viewModel.show(date: "2026-02-30")
        await viewModel.show(date: "2026-2-3")
        await viewModel.show(date: "tomorrow")
        XCTAssertEqual(api.fetchedDates.count, 0)
    }

    func testAJumpAndTheTabsOwnLoadMakeOneRead() async throws {
        XCTAssertTrue(viewModel.select(date: "2026-10-20"))
        var jump: Task<Void, Never>?
        api.duringFetch = { [viewModel] in
            // The jump arrives while the tab's own load is on the wire.
            jump = Task { await viewModel?.show(date: "2026-10-20") }
            await Task.yield()
            await Task.yield()
        }
        await viewModel.load()
        await jump?.value
        XCTAssertEqual(api.fetchedDates, ["2026-10-20"], "one transition, one GET")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testALoadOfAnotherDayIsNotJoined() async throws {
        await viewModel.load()
        await viewModel.show(date: "2026-10-20")
        XCTAssertEqual(api.fetchedDates, [nil, "2026-10-20"])
    }
}
