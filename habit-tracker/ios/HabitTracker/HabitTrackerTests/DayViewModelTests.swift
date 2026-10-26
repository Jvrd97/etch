// [review:need-review] PHASE-01/211
// summary: Day view model tests — load/failure/not-configured, optimistic mark cycle with rollback, stepping days drops stale answers, category-linked fact record/correct/remove with the done/unmark rule and a stable retry key, notebook dirty tracking and per-day drafts, two-touch closing with keys and validation
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

    private func factsWrite(total: Double, markState: String?) -> PlanFactWriteDTO {
        let day = try! DayFixtures.day()
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

        XCTAssertEqual(viewModel.counts?.failed, 1)
        XCTAssertEqual(api.fetchedDates.count, 2)
    }

    // MARK: Facts

    func testReachingTheTargetRecordsTheFactWithDoneMark() async throws {
        await viewModel.load()
        api.factResult = .success(factsWrite(total: 300, markState: "done"))
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

    func testPartialFactDoesNotMarkTheLineDone() async {
        await viewModel.load()
        api.factResult = .success(factsWrite(total: 150, markState: nil))

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

    func testBoxFactSendsAFlagWithoutUnit() async {
        await viewModel.load()
        api.factResult = .success(factsWrite(total: 0, markState: "done"))

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
        api.factResult = .success(factsWrite(total: 250, markState: nil))

        _ = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("150"), correcting: 502)

        XCTAssertEqual(api.correctCalls.count, 1)
        XCTAssertEqual(api.correctCalls[0].entry, 502)
        XCTAssertEqual(api.correctCalls[0].body.mark, "unmark")
    }

    func testRemovingTheLastEntryOfADoneLineAsksForUnmark() async throws {
        api.fetchResults = [.success(try doneLine())]
        await viewModel.load()
        api.factResult = .success(factsWrite(total: 100, markState: nil))

        await viewModel.removeFact(DayFixtures.pushupsID, entryID: 502)

        XCTAssertEqual(api.removeCalls.count, 1)
        XCTAssertTrue(api.removeCalls[0].unmark)
    }

    func testRemovingAnEntryOfAShortLineLeavesTheMarkAlone() async {
        await viewModel.load()
        api.factResult = .success(factsWrite(total: 0, markState: nil))

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
        XCTAssertEqual(viewModel.actionError, "Connection timed out")
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
}
